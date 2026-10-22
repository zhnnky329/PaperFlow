"""Discovery endpoints share the application's local Host/Origin protection."""

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, Query
from pydantic import ValidationError
from sqlalchemy import select, func, or_, exists, update, cast, String

from .db import DiscoveryPaper, DiscoveryRun, Paper, Setting, now
from .discovery import (
    DiscoverySettings,
    FeedbackInput,
    KeyInput,
    library_match,
    put_setting,
    read_settings,
    run_dict,
)


def register_discovery(app, worker, sessions, import_arxiv, import_lock):
    def public_settings(session):
        _, source = worker.api_key()
        return read_settings(session) | {"api_key_configured": bool(source), "api_key_source": source}

    def seen_at(session):
        row = session.get(Setting, "discovery_seen_at")
        return row.value if row else ""

    def linked_clause():
        return exists(
            select(Paper.id).where(
                or_(
                    Paper.id == DiscoveryPaper.paper_id,
                    Paper.arxiv_id == DiscoveryPaper.arxiv_id,
                    cast(DiscoveryPaper.arxiv_aliases, String).contains('"' + Paper.arxiv_id + '"'),
                    (DiscoveryPaper.doi.is_not(None))
                    & (func.lower(Paper.doi) == func.lower(DiscoveryPaper.doi)),
                )
            )
        )

    def recommended(cfg):
        return select(DiscoveryPaper).where(
            DiscoveryPaper.analysis_status == "succeeded",
            DiscoveryPaper.analysis["decision"].as_string() == "recommend",
            DiscoveryPaper.analysis["score"].as_integer() >= cfg["min_score"],
            DiscoveryPaper.feedback != "dismissed",
            ~linked_clause(),
        )

    def paper_dict(session, row):
        match = library_match(session, row)
        result = {
            c.name: getattr(row, c.name)
            for c in DiscoveryPaper.__table__.columns
            if c.name not in ("content_hash", "analyzed_hash", "last_seen_at", "recommendation_run_id")
        }
        result["paper_id"] = match.id if match else None
        result["is_new"] = bool(row.analyzed_at and row.analyzed_at > seen_at(session))
        return result

    def paper_or_404(session, paper_id):
        row = session.get(DiscoveryPaper, str(paper_id))
        if not row:
            raise HTTPException(404, "发现记录不存在")
        return row

    @app.get("/api/v1/discovery/settings")
    def get_settings():
        with sessions() as session:
            return public_settings(session)

    @app.patch("/api/v1/discovery/settings")
    def patch_settings(body: dict):
        with worker.lock, sessions() as session:
            try:
                cfg = DiscoverySettings.model_validate(read_settings(session) | body).model_dump()
            except ValidationError as exc:
                raise HTTPException(422, "发现配置不合法，请检查方向、频率、评分与预算范围") from exc
            put_setting(session, "research_discovery", cfg)
            session.execute(
                update(DiscoveryPaper)
                .where(DiscoveryPaper.analysis_status == "filtered")
                .values(analysis_status="pending", analysis_error=None)
            )
            session.commit()
            result = public_settings(session)
        worker.wake.set()
        return result

    @app.post("/api/v1/discovery/api-key")
    def save_key(body: KeyInput):
        worker.save_key(body.api_key)
        with sessions() as session:
            return public_settings(session)

    @app.get("/api/v1/discovery/status")
    def status():
        with sessions() as session:
            cfg = read_settings(session)
            last = session.scalar(select(DiscoveryRun).order_by(DiscoveryRun.created_at.desc()))
            active = session.scalar(
                select(DiscoveryRun).where(DiscoveryRun.status.in_(["queued", "running"]))
            )
            checked = session.get(Setting, "discovery_last_checked")
            new_count = session.scalar(
                select(func.count()).select_from(
                    recommended(cfg).where(DiscoveryPaper.analyzed_at > seen_at(session)).subquery()
                )
            )
            usage = session.execute(
                select(
                    func.coalesce(func.sum(DiscoveryRun.tokens_used), 0),
                    func.coalesce(func.sum(DiscoveryRun.tokens_reserved), 0),
                )
            ).one()
            next_check = (
                (datetime.fromisoformat(last.created_at) + timedelta(hours=cfg["interval_hours"])).isoformat()
                if cfg["auto_update"] and last and not active
                else None
            )
            return {
                "active_run": run_dict(active) if active else None,
                "last_run": run_dict(last) if last else None,
                "last_checked_at": checked.value if checked else None,
                "next_check_at": next_check,
                "new_count": new_count,
                "pending_count": session.scalar(
                    select(func.count())
                    .select_from(DiscoveryPaper)
                    .where(
                        DiscoveryPaper.analysis_status == "pending",
                        ~linked_clause(),
                        DiscoveryPaper.feedback != "dismissed",
                    )
                ),
                "key_configured": bool(worker.api_key()[0]),
                "usage": {"tokens_used": usage[0], "tokens_reserved": usage[1]},
                "online": worker.config.discovery_online,
            }

    @app.post("/api/v1/discovery/check", status_code=202)
    def check():
        run, dedupe = worker.enqueue()
        return {"run": run, "dedupe": dedupe}

    @app.get("/api/v1/discovery/runs")
    def runs():
        with sessions() as session:
            return [
                run_dict(row)
                for row in session.scalars(
                    select(DiscoveryRun).order_by(DiscoveryRun.created_at.desc()).limit(50)
                )
            ]

    @app.post("/api/v1/discovery/runs/{run_id}/retry", status_code=202)
    def retry(run_id: UUID):
        with sessions() as session:
            row = session.get(DiscoveryRun, str(run_id))
            if not row:
                raise HTTPException(404, "检查记录不存在")
            if row.status != "failed":
                raise HTTPException(409, "只能重试失败的检查")
            options = dict(row.options) | {"retry_failed": True}
        run, dedupe = worker.enqueue("retry", options)
        return {"run": run, "dedupe": dedupe}

    @app.post("/api/v1/discovery/seen")
    def mark_seen():
        with sessions() as session:
            put_setting(session, "discovery_seen_at", now())
            session.commit()
        return {"seen": True}

    @app.get("/api/v1/discovery/papers")
    def papers(
        sort: Literal["score", "recent"] = "score",
        view: Literal["recommended", "latest", "history", "interested", "dismissed"] = "recommended",
        interest_id: str | None = Query(None, max_length=80, pattern=r"^[\w-]+$"),
        min_score: int | None = Query(None, ge=0, le=100),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ):
        with sessions() as session:
            cfg = read_settings(session)
            if min_score is not None:
                cfg["min_score"] = min_score
            stmt = recommended(cfg) if view in ("recommended", "latest") else select(DiscoveryPaper)
            if view == "latest":
                last = session.scalar(
                    select(DiscoveryRun)
                    .where(DiscoveryRun.recommended_count > 0)
                    .order_by(DiscoveryRun.created_at.desc())
                )
                stmt = stmt.where(DiscoveryPaper.recommendation_run_id == (last.id if last else ""))
            elif view == "interested":
                stmt = stmt.where(DiscoveryPaper.feedback.in_(["interested", "later"]))
            elif view == "dismissed":
                stmt = stmt.where(DiscoveryPaper.feedback == "dismissed")
            if min_score is not None and view not in ("recommended", "latest"):
                stmt = stmt.where(DiscoveryPaper.analysis["score"].as_integer() >= min_score)
            if interest_id:
                # IDs are validated and JSON-escaped; match an entire JSON string.
                import json

                stmt = stmt.where(
                    DiscoveryPaper.analysis["matched_directions"]
                    .as_string()
                    .contains(json.dumps(interest_id, ensure_ascii=False))
                )
            total = session.scalar(select(func.count()).select_from(stmt.subquery()))
            order = (
                [DiscoveryPaper.analysis["score"].as_integer().desc(), DiscoveryPaper.updated_at.desc()]
                if sort == "score"
                else [DiscoveryPaper.updated_at.desc()]
            )
            rows = session.scalars(stmt.order_by(*order).offset((page - 1) * page_size).limit(page_size))
            return {
                "items": [paper_dict(session, row) for row in rows],
                "total": total,
                "page": page,
                "page_size": page_size,
            }

    @app.post("/api/v1/discovery/papers/{paper_id}/feedback")
    def feedback(paper_id: UUID, body: FeedbackInput):
        with sessions() as session:
            row = paper_or_404(session, paper_id)
            row.feedback = body.feedback
            session.commit()
            return paper_dict(session, row)

    @app.post("/api/v1/discovery/papers/{paper_id}/import", status_code=202)
    def import_paper(paper_id: UUID):
        with import_lock, sessions() as session:
            row = paper_or_404(session, paper_id)
            seed = {c.name: getattr(row, c.name) for c in DiscoveryPaper.__table__.columns}
        # Uses the same arXiv creation/metadata path as Add Paper.
        result = import_arxiv(row.arxiv_id, seed)
        with sessions() as session:
            row = paper_or_404(session, paper_id)
            row.paper_id = result["paper"]["id"]
            session.commit()
        return result

    @app.post("/api/v1/discovery/papers/{paper_id}/reanalyze", status_code=202)
    def reanalyze(paper_id: UUID):
        with worker.lock, sessions() as session:
            cfg = read_settings(session)
            row = paper_or_404(session, paper_id)
            if not cfg["ai_enabled"] or not worker.api_key()[0]:
                raise HTTPException(409, "请先在 Settings 配置密钥并启用 AI 分析")
            active = session.scalar(
                select(DiscoveryRun).where(DiscoveryRun.status.in_(["queued", "running"]))
            )
            if active:
                raise HTTPException(409, "请等待当前检查完成，再重新分析")
            if library_match(session, row):
                raise HTTPException(409, "论文已在 Library，无需重新推荐")
            run, dedupe = worker.enqueue("reanalyze", {"analysis_only": True, "paper_ids": [str(paper_id)]})
        return {"run": run, "dedupe": dedupe}
