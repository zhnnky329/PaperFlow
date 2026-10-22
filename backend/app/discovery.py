"""Local discovery settings, durable queue, bounded analysis and scheduler."""

import hashlib
import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select, func, or_, cast, String

from .db import DiscoveryPaper, DiscoveryRun, Paper, Setting, now, uid
from . import discovery_ai, discovery_feed


class Interest(BaseModel):
    model_config = {"extra": "forbid"}
    id: str = Field(min_length=1, max_length=80, pattern=r"^[\w-]+$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=3000)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    exclude_keywords: list[str] = Field(default_factory=list, max_length=50)
    priority: int = Field(default=2, ge=1, le=3)

    @field_validator("keywords", "exclude_keywords")
    @classmethod
    def bounded_terms(cls, values):
        if any(not word.strip() or len(word) > 150 for word in values):
            raise ValueError("Invalid keyword")
        return list(dict.fromkeys(word.strip() for word in values))


class DiscoverySettings(BaseModel):
    model_config = {"extra": "forbid"}
    auto_update: bool = True
    interval_hours: int = Field(default=48, ge=1, le=720)
    min_score: int = Field(default=70, ge=0, le=100)
    max_analyses: int = Field(default=10, ge=1, le=100)
    try_full_text: bool = True
    ai_enabled: bool = False
    model: str = Field(
        default="deepseek-flash", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    token_budget: int = Field(default=50000, ge=2000, le=2000000)
    max_output_tokens: int = Field(default=800, ge=300, le=4000)
    interest_description: str = Field(
        default=(
            "关注无人机在动态场景中的主动视觉感知、长期目标跟踪和身份保持，尤其是与三维场景理解相结合的方法。"
        ),
        max_length=5000,
    )
    interests: list[Interest] = Field(
        default_factory=lambda: [
            Interest(
                id="uav",
                name="无人机视觉感知",
                priority=3,
                description="无人机主动视觉感知、长期目标跟踪与身份保持、语言引导目标定位。",
                keywords=[
                    "Active Visual Perception",
                    "Visual Object Tracking",
                    "Language-Guided Object Grounding",
                    "Long-term Object Tracking",
                    "Re-identification",
                    "UAV Visual Perception",
                    "Active Perception and Tracking",
                ],
            ),
            Interest(
                id="3d",
                name="三维视觉与空间感知",
                priority=3,
                description="主动三维重建、场景理解、空间智能及协作式三维感知。",
                keywords=[
                    "Active 3D Reconstruction",
                    "3D Gaussian Splatting",
                    "NeRF",
                    "Visual SLAM",
                    "Dense Mapping",
                    "3D Scene Understanding",
                    "Spatial Intelligence",
                    "Collaborative 3D Perception",
                ],
            ),
            Interest(
                id="navigation",
                name="机器人自主定位与导航",
                priority=2,
                description="自主探索、感知驱动规划、动态避障、激光里程计与多机器人导航。",
                keywords=[
                    "Autonomous Exploration",
                    "Motion Planning",
                    "Dynamic Obstacle Avoidance",
                    "Perception-aware Planning",
                    "LiDAR Odometry",
                    "Localization",
                    "Multi-robot Navigation",
                ],
            ),
        ],
        max_length=30,
    )

    @model_validator(mode="after")
    def unique_interests(self):
        if len({item.id for item in self.interests}) != len(self.interests):
            raise ValueError("Duplicate interest IDs")
        if self.ai_enabled and not self.interests and not self.interest_description.strip():
            raise ValueError("Research interests required")
        if self.max_output_tokens >= self.token_budget:
            raise ValueError("Output must fit budget")
        return self


class FeedbackInput(BaseModel):
    model_config = {"extra": "forbid"}
    feedback: Literal["none", "interested", "later", "dismissed"]


class KeyInput(BaseModel):
    model_config = {"extra": "forbid"}
    api_key: str = Field(max_length=500)

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value):
        value = value.strip()
        if value and (len(value) < 8 or not re.fullmatch(r"[\x21-\x7e]+", value)):
            raise ValueError("Invalid API key")
        return value


def read_settings(session):
    row = session.get(Setting, "research_discovery")
    return DiscoverySettings.model_validate(row.value if row else {}).model_dump()


def put_setting(session, key, value):
    row = session.get(Setting, key) or Setting(key=key)
    row.value = value
    session.add(row)


def run_dict(run):
    return {c.name: getattr(run, c.name) for c in DiscoveryRun.__table__.columns if c.name != "options"}


def library_match(session, candidate):
    linked_id = getattr(candidate, "paper_id", None)
    found = session.get(Paper, linked_id) if linked_id else None
    if not found:
        found = session.scalar(
            select(Paper).where(
                Paper.arxiv_id.in_([candidate.arxiv_id] + (getattr(candidate, "arxiv_aliases", None) or []))
            )
        )
    if not found and candidate.doi:
        found = session.scalar(select(Paper).where(func.lower(Paper.doi) == candidate.doi.casefold()))
    return found


class DiscoveryWorker:
    def __init__(self, config, sessions):
        self.config, self.sessions = config, sessions
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.thread = threading.Thread(target=self.run, name="discovery", daemon=True)

    def api_key(self):
        environment = self.config.deepseek_api_key.get_secret_value()
        if environment:
            return environment, "environment"
        if (self.config.data_dir / "discovery-api-key").is_symlink():
            raise ValueError("Symlinked API key refused")
        path = self.config.path("discovery-api-key")
        if not path.is_file():
            return "", None
        # Refuse a key readable by other local users.
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            if os.fstat(descriptor).st_mode & 0o077:
                raise ValueError("API key permissions must be 0600")
            with os.fdopen(descriptor, "r", closefd=False) as handle:
                return handle.read(1001).strip(), "local"
        finally:
            os.close(descriptor)

    def save_key(self, value):
        with self.lock:
            if (self.config.data_dir / "discovery-api-key").is_symlink():
                raise ValueError("Symlinked API key refused")
            path = self.config.path("discovery-api-key")
            if not value:
                path.unlink(missing_ok=True)
                return
            stage = self.config.path("staging/discovery-key-" + uid())
            stage.parent.mkdir(parents=True, exist_ok=True)
            try:
                with os.fdopen(os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
                    handle.write(value)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(stage, path)
            finally:
                stage.unlink(missing_ok=True)

    def start(self):
        with self.sessions() as session:
            for run in session.scalars(select(DiscoveryRun).where(DiscoveryRun.status == "running")):
                run.status, run.stage = "failed", "interrupted"
                run.error_code, run.error_message = "INTERRUPTED", "上次检查中断；已保存结果，可手动重试。"
                run.finished_at = now()
            for paper in session.scalars(
                select(DiscoveryPaper).where(DiscoveryPaper.analysis_status == "running")
            ):
                paper.analysis_status = "failed"
                paper.analysis_error = "上次 AI 分析中断，可能已产生用量；请核对后手动重试。"
            session.commit()
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        # Keep the data-directory lock until in-flight bounded requests finish.
        if self.thread.is_alive():
            self.thread.join()

    def enqueue(self, trigger="manual", options=None):
        with self.lock, self.sessions() as session:
            active = session.scalar(
                select(DiscoveryRun).where(DiscoveryRun.status.in_(["queued", "running"]))
            )
            if active:
                return run_dict(active), True
            if not self.config.discovery_online:
                raise HTTPException(409, "发现联网已关闭，请启用 PAPERFLOW_DISCOVERY_ONLINE 后重试")
            run = DiscoveryRun(id=uid(), trigger=trigger, options=options or {})
            session.add(run)
            session.commit()
            result = run_dict(run)
        self.wake.set()
        return result, False

    def schedule_due(self):
        if not self.config.discovery_online or self.stop_event.is_set():
            return
        with self.lock, self.sessions() as session:
            cfg = read_settings(session)
            if not cfg["auto_update"]:
                return
            last = session.scalar(select(DiscoveryRun).order_by(DiscoveryRun.created_at.desc()))
            if last:
                if last.status in ("queued", "running"):
                    return
                delay = cfg["interval_hours"] if last.status == "succeeded" else max(1, cfg["interval_hours"])
                if datetime.fromisoformat(last.created_at) + timedelta(hours=delay) > datetime.now(
                    timezone.utc
                ):
                    return
            self.enqueue("scheduled")

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.schedule_due()
                if not self.config.discovery_online:
                    self.wake.wait(2)
                    self.wake.clear()
                    continue
                with self.lock, self.sessions() as session:
                    run = session.scalar(select(DiscoveryRun).where(DiscoveryRun.status == "queued"))
                    run_id = run.id if run else None
                    if run:
                        run.status, run.stage, run.started_at = "running", "fetching", now()
                        session.commit()
                if run_id:
                    self.execute(run_id)
                    continue
            except Exception as exc:
                logging.getLogger("paperflow").error("discovery_loop exception=%s", type(exc).__name__)
            self.wake.wait(2)
            self.wake.clear()

    def fail(self, run_id, code, message):
        with self.sessions() as session:
            run = session.get(DiscoveryRun, run_id)
            run.status, run.stage = "failed", "failed"
            run.error_code, run.error_message, run.finished_at = code, message, now()
            for paper in session.scalars(
                select(DiscoveryPaper).where(DiscoveryPaper.analysis_status == "running")
            ):
                paper.analysis_status = "failed"
                paper.analysis_error = "分析未完成，可能已产生用量；请核对后手动重试。"
            session.commit()
        logging.getLogger("paperflow").warning("discovery run=%s code=%s", run_id, code)

    def execute(self, run_id):
        try:
            with self.sessions() as session:
                cfg = read_settings(session)
                run = session.get(DiscoveryRun, run_id)
                options = dict(run.options)
                cursor_row = session.get(Setting, "discovery_cursor")
                cursor = cursor_row.value if cursor_row else {}
            if not options.get("analysis_only"):
                until = cursor.get("until") or now()
                since = cursor.get("since") or (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
                start = cursor.get("start", 0)
                while not self.stop_event.is_set():
                    feed = discovery_feed.fetch_candidates(
                        since=since, until=until, max_results=100, start=start
                    )
                    if self.stop_event.is_set():
                        return
                    with self.sessions() as session:
                        run = session.get(DiscoveryRun, run_id)
                        for candidate in feed["candidates"]:
                            self.store_candidate(session, candidate, run)
                        run.fetched_count += len(feed["candidates"])
                        if feed["complete"]:
                            next_cursor = {
                                "since": (datetime.fromisoformat(until) - timedelta(hours=24)).isoformat()
                            }
                            put_setting(session, "discovery_last_checked", until)
                        else:
                            if feed["next_start"] is None or feed["next_start"] <= start:
                                raise ValueError("Discovery pagination did not advance")
                            next_cursor = {"since": since, "until": until, "start": feed["next_start"]}
                        put_setting(session, "discovery_cursor", next_cursor)
                        session.commit()
                    if feed["complete"]:
                        break
                    start = feed["next_start"]
            if self.stop_event.is_set():
                return
            self.analyze_pending(run_id, cfg, options)
            if self.stop_event.is_set():
                return
            with self.sessions() as session:
                run = session.get(DiscoveryRun, run_id)
                if run.status == "failed":
                    return
                run.status, run.stage, run.finished_at = "succeeded", "done", now()
                session.commit()
        except Exception as exc:
            # Neither exception messages nor response/request bodies enter logs.
            logging.getLogger("paperflow").warning("discovery exception=%s", type(exc).__name__)
            self.fail(run_id, "DISCOVERY_FAILED", "检查未完成；已保存结果，请检查网络后重试。")

    def store_candidate(self, session, candidate, run):
        row = session.scalar(
            select(DiscoveryPaper).where(
                or_(
                    DiscoveryPaper.arxiv_id == candidate["arxiv_id"],
                    cast(DiscoveryPaper.arxiv_aliases, String).contains(json.dumps(candidate["arxiv_id"])),
                )
            )
        )
        by_doi = (
            session.scalar(select(DiscoveryPaper).where(DiscoveryPaper.doi == candidate["doi"]))
            if candidate.get("doi")
            else None
        )
        if row and by_doi and row.id != by_doi.id:
            # Coalesce identifiers without mixing one arXiv ID with another's
            # version/URL/body. Keep the record already holding useful feedback.
            def rank(item):
                return (bool(item.paper_id), item.feedback != "none", item.analysis_status == "succeeded")

            survivor, other = (row, by_doi) if rank(row) >= rank(by_doi) else (by_doi, row)
            survivor.arxiv_aliases = sorted(
                set((survivor.arxiv_aliases or []) + (other.arxiv_aliases or []) + [other.arxiv_id])
                - {survivor.arxiv_id}
            )
            if other.feedback == "dismissed" or survivor.feedback == "none":
                survivor.feedback = other.feedback
            survivor.paper_id = survivor.paper_id or other.paper_id
            session.delete(other)
            session.flush()
            row = survivor
        elif row is None:
            row = by_doi
        if row and candidate["arxiv_id"] != row.arxiv_id:
            row.arxiv_aliases = sorted(set((row.arxiv_aliases or []) + [candidate["arxiv_id"]]))
            row.doi = row.doi or candidate.get("doi")
        if not row:
            row = DiscoveryPaper(
                id=uid(),
                **{
                    key: candidate[key]
                    for key in (
                        "arxiv_id",
                        "arxiv_version",
                        "doi",
                        "title",
                        "authors",
                        "abstract",
                        "categories",
                        "published_at",
                        "updated_at",
                        "source_url",
                        "venue",
                        "content_hash",
                    )
                },
            )
            session.add(row)
            run.new_count += 1
        elif candidate["arxiv_id"] == row.arxiv_id and candidate["updated_at"] >= row.updated_at:
            changed = candidate["content_hash"] != row.content_hash
            for key in (
                "arxiv_version",
                "doi",
                "title",
                "authors",
                "abstract",
                "categories",
                "updated_at",
                "source_url",
                "venue",
                "content_hash",
            ):
                setattr(row, key, candidate[key])
            if changed:
                row.analysis_status, row.analysis_error = "pending", None
        row.last_seen_at = now()
        match = library_match(session, row)
        if match:
            row.paper_id = match.id
        session.flush()

    def analyze_pending(self, run_id, cfg, options):
        with self.sessions() as session:
            stmt = select(DiscoveryPaper).where(DiscoveryPaper.paper_id.is_(None))
            identifiers = options.get("paper_ids")
            if identifiers:
                stmt = stmt.where(DiscoveryPaper.id.in_(identifiers))
            else:
                statuses = ["pending", "failed"] if options.get("retry_failed") else ["pending"]
                stmt = stmt.where(DiscoveryPaper.analysis_status.in_(statuses))
            candidates = list(session.scalars(stmt.order_by(DiscoveryPaper.updated_at.desc())))
            ranked = []
            for row in candidates:
                if library_match(session, row) or row.feedback == "dismissed":
                    continue
                paper = {c.name: getattr(row, c.name) for c in DiscoveryPaper.__table__.columns}
                result = discovery_feed.prefilter(
                    paper, cfg["interests"], interest_description=cfg["interest_description"]
                )
                if not result["eligible"]:
                    row.analysis_status, row.analysis_error = "filtered", result["reason"]
                else:
                    ranked.append((result["priority_score"], paper))
            session.commit()
        if not cfg["ai_enabled"]:
            return
        api_key, _ = self.api_key()
        if not api_key:
            return
        for _, paper in sorted(ranked, key=lambda item: item[0], reverse=True)[: cfg["max_analyses"]]:
            if self.stop_event.is_set():
                return
            # Cached successes are untouched; changing interests does not silently spend again.
            fingerprint = hashlib.sha256(
                (paper["content_hash"] + cfg["model"] + "discovery-v1").encode()
            ).hexdigest()
            if (
                paper["analyzed_hash"] == fingerprint
                and paper["analysis_status"] == "succeeded"
                and not options.get("analysis_only")
            ):
                continue
            with self.sessions() as session:
                if not read_settings(session)["ai_enabled"]:
                    return
                row = session.get(DiscoveryPaper, paper["id"])
                if library_match(session, row) or row.feedback == "dismissed":
                    continue
                run = session.get(DiscoveryRun, run_id)
                run.stage = "reading"
                session.commit()
            content = discovery_ai.fetch_content(
                paper, try_full_text=cfg["try_full_text"], max_chars=24000, stop_event=self.stop_event
            )
            if self.stop_event.is_set():
                return
            estimate = discovery_ai.estimate_tokens(
                paper, cfg["interests"], content, cfg["max_output_tokens"], cfg["interest_description"]
            )
            with self.sessions() as session:
                if not read_settings(session)["ai_enabled"]:
                    return
                api_key, _ = self.api_key()
                if not api_key:
                    return
                row = session.get(DiscoveryPaper, paper["id"])
                if library_match(session, row) or row.feedback == "dismissed":
                    continue
                run = session.get(DiscoveryRun, run_id)
                if run.tokens_used + run.tokens_reserved + estimate > cfg["token_budget"]:
                    # Fall back to the abstract before declining a long candidate.
                    content = discovery_ai.fetch_content(paper, try_full_text=False, max_chars=12000)
                    estimate = discovery_ai.estimate_tokens(
                        paper,
                        cfg["interests"],
                        content,
                        cfg["max_output_tokens"],
                        cfg["interest_description"],
                    )
                if run.tokens_used + run.tokens_reserved + estimate > cfg["token_budget"]:
                    run.error_code, run.error_message = (
                        "BUDGET_LIMIT",
                        "本次 Token 预算已用完，其余候选保留待下次分析。",
                    )
                    session.commit()
                    break
                run.tokens_reserved += estimate
                run.stage = "analyzing"
                row.analysis_status = "running"
                row.analysis_error = None
                session.commit()
            try:
                result = discovery_ai.analyze(
                    paper,
                    cfg["interests"],
                    content,
                    api_key=api_key,
                    model=cfg["model"],
                    max_output_tokens=cfg["max_output_tokens"],
                    interest_description=cfg["interest_description"],
                )
                with self.sessions() as session:
                    row, run = session.get(DiscoveryPaper, paper["id"]), session.get(DiscoveryRun, run_id)
                    if row.content_hash != paper["content_hash"]:
                        raise ValueError("Candidate changed")
                    row.analysis = result
                    row.analysis_status, row.analysis_error = "succeeded", None
                    row.analyzed_hash, row.analyzed_at = fingerprint, now()
                    run.tokens_reserved -= estimate
                    run.tokens_used += result["tokens_used"]
                    run.analyzed_count += 1
                    if result["decision"] == "recommend" and result["score"] >= cfg["min_score"]:
                        row.recommendation_run_id = run_id
                        run.recommended_count += 1
                    session.commit()
            except discovery_ai.AIError as exc:
                with self.sessions() as session:
                    row, run = session.get(DiscoveryPaper, paper["id"]), session.get(DiscoveryRun, run_id)
                    row.analysis_status, row.analysis_error = "failed", exc.message
                    if exc.tokens_used:
                        run.tokens_reserved -= estimate
                        run.tokens_used += exc.tokens_used
                    run.error_code, run.error_message = exc.code, exc.message
                    session.commit()
                self.fail(run_id, exc.code, exc.message)
                return
