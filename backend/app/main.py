import fcntl
import json
import logging
import logging.handlers
import os
import re
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID
from fastapi import FastAPI, HTTPException, Request, UploadFile, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, delete, or_
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from .config import Config, ROOT, UnsafePath
from .db import (
    database,
    Paper,
    Tag,
    Collection,
    Job,
    Position,
    Setting,
    paper_tags,
    paper_collections,
    now,
    uid,
)
from .schemas import PaperPatch, ArxivInput, NameInput, ReadingPosition, SettingsPatch, ConvertInput
from .storage import ingest, delete_assets
from .worker import Worker, settings, job_dict
from .html import reader_document
from . import arxiv
from .folders import FolderSync, FolderConflict, folder_name


def create_app(config=None):
    config = config or Config()
    engine, sessions = database(config)
    worker = Worker(config, sessions)
    folder_sync = FolderSync(config, sessions)
    import_lock = threading.RLock()
    metadata_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="arxiv")
    metadata_pending = set()
    metadata_lock = threading.Lock()

    def schedule_metadata(paper_id):
        with metadata_lock:
            if paper_id in metadata_pending or len(metadata_pending) >= 30:
                return
            metadata_pending.add(paper_id)
        future = metadata_pool.submit(arxiv.refresh, sessions, paper_id)

        def finish(_):
            with metadata_lock:
                metadata_pending.discard(paper_id)
            folder_sync.request()

        future.add_done_callback(finish)

    @asynccontextmanager
    async def lifespan(app):
        lock_file = (config.data_dir / "server.lock").open("a+")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_file.close()
            raise RuntimeError("此数据目录已有 PaperFlow 实例，请先停止旧实例")
        log_dir = config.data_dir / "logs"
        log_dir.mkdir(exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_dir / "paperflow.log", maxBytes=1_000_000, backupCount=3
        )
        logger = logging.getLogger("paperflow")
        logger.addHandler(handler)
        with sessions() as session:
            for paper in session.scalars(select(Paper).where(Paper.metadata_status == "pending")):
                paper.metadata_status = "failed"
            session.commit()
        worker.start()
        folder_sync.start()
        try:
            yield
        finally:
            worker.stop()
            folder_sync.stop()
            metadata_pool.shutdown(wait=True, cancel_futures=True)
            logger.removeHandler(handler)
            handler.close()
            engine.dispose()
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()

    app = FastAPI(title="PaperFlow", version="0.1.0", lifespan=lifespan)
    app.state.sessions, app.state.worker, app.state.config = sessions, worker, config
    app.state.folder_sync = folder_sync

    @app.middleware("http")
    async def security(request: Request, call_next):
        allowed_hosts = {
            f"127.0.0.1:{config.port}",
            f"localhost:{config.port}",
            "127.0.0.1:5173",
            "localhost:5173",
        }
        host = request.headers.get("host", "")
        if host not in allowed_hosts:
            return JSONResponse(
                {"error": {"code": "HOST_REJECTED", "message": "仅允许本地 PaperFlow 地址"}}, 403
            )
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origins = {"http://" + h for h in allowed_hosts}
            if request.headers.get("origin") not in origins or request.headers.get("x-paperflow") != "1":
                return JSONResponse({"error": {"code": "CSRF_REJECTED", "message": "请求来源不受信任"}}, 403)
        try:
            length = int(request.headers.get("content-length", 0))
        except ValueError:
            return JSONResponse({"error": {"code": "INVALID_LENGTH", "message": "请求长度不合法"}}, 400)
        if length > (config.max_upload_mb * 1024 * 1024 + 1024 * 1024):
            return JSONResponse({"error": {"code": "TOO_LARGE", "message": "文件超过大小限制"}}, 413)
        receive = request._receive
        received = 0

        async def bounded_receive():
            nonlocal received
            event = await receive()
            received += len(event.get("body", b""))
            if received > config.max_upload_mb * 1024 * 1024 + 1024 * 1024:
                raise HTTPException(413, "请求超过上传限制")
            return event

        request._receive = bounded_receive
        try:
            response = await call_next(request)
        except Exception as exc:
            # Handle here so ServerErrorMiddleware cannot re-raise to Uvicorn,
            # which would log an unfiltered exception message and traceback.
            response = await unexpected(request, exc)
        if received > config.max_upload_mb * 1024 * 1024 + 1024 * 1024:
            response = JSONResponse({"error": {"code": "TOO_LARGE", "message": "请求超过上传限制"}}, 413)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; font-src 'self'; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            {"error": {"code": f"HTTP_{exc.status_code}", "message": str(exc.detail), "request_id": uid()}},
            exc.status_code,
        )

    @app.exception_handler(UnsafePath)
    async def unsafe_path(request, exc):
        return JSONResponse({"error": {"code": "UNSAFE_PATH", "message": "资源路径不安全，访问已拒绝"}}, 403)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "输入不合法，请检查字段范围和格式",
                    "request_id": uid(),
                }
            },
            422,
        )

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        request_id = uid()
        logging.getLogger("paperflow").error(
            "request=%s exception=%s frames=%s",
            request_id,
            type(exc).__name__,
            [
                (os.path.basename(frame.filename), frame.lineno, frame.name)
                for frame in traceback.extract_tb(exc.__traceback__)
            ],
        )
        return JSONResponse(
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "操作未完成，请重试或查看本地诊断记录",
                    "request_id": request_id,
                }
            },
            500,
        )

    def paper_or_404(session, paper_id):
        paper = session.get(Paper, str(paper_id))
        if not paper:
            raise HTTPException(404, "论文不存在")
        return paper

    def taxonomy(session, paper, model, association):
        key = "tag_id" if model == Tag else "collection_id"
        return [
            {"id": row.id, "name": row.name}
            for row in session.scalars(
                select(model)
                .join(association, model.id == association.c[key])
                .where(association.c.paper_id == paper.id)
            )
        ]

    def serialize(session, paper):
        result = {
            c.name: getattr(paper, c.name)
            for c in Paper.__table__.columns
            if c.name not in ("pdf_path", "html_path")
        }
        result["has_pdf"] = bool(paper.pdf_path and config.path(paper.pdf_path).is_file())
        result["has_html"] = bool(paper.html_path and config.path(paper.html_path).is_file())
        result["tags"] = taxonomy(session, paper, Tag, paper_tags)
        result["collections"] = taxonomy(session, paper, Collection, paper_collections)
        latest = session.scalar(select(Job).where(Job.paper_id == paper.id).order_by(Job.created_at.desc()))
        result["conversion"] = job_dict(latest) if latest else None
        return result

    @app.get("/api/v1/health")
    def health():
        with sessions() as session:
            session.execute(select(Setting).limit(1))
        return {"status": "ok", "database": "ok", "marker_available": bool(worker.executable())}

    @app.get("/api/v1/papers")
    def list_papers(
        q: str = Query("", max_length=500),
        status: Literal["unread", "reading", "finished"] | None = None,
        collection: str | None = None,
        unfiled: bool = False,
        tag: str | None = None,
        sort: Literal["recent", "read", "year", "title"] = "recent",
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=100),
    ):
        with sessions() as session:
            stmt = select(Paper)
            if q:
                pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                tagged = select(paper_tags.c.paper_id).join(Tag).where(Tag.name.ilike(pattern, escape="\\"))
                stmt = stmt.where(
                    or_(
                        Paper.title.ilike(pattern, escape="\\"),
                        Paper.authors.cast(__import__("sqlalchemy").String).ilike(pattern, escape="\\"),
                        Paper.arxiv_id.ilike(pattern, escape="\\"),
                        Paper.id.in_(tagged),
                    )
                )
            if status:
                stmt = stmt.where(Paper.read_status == status)
            if collection:
                stmt = stmt.where(
                    Paper.id.in_(
                        select(paper_collections.c.paper_id).where(
                            paper_collections.c.collection_id == collection
                        )
                    )
                )
            if unfiled:
                stmt = stmt.where(~Paper.id.in_(select(paper_collections.c.paper_id)))
            if tag:
                stmt = stmt.where(
                    Paper.id.in_(select(paper_tags.c.paper_id).where(paper_tags.c.tag_id == tag))
                )
            order = {
                "recent": Paper.created_at.desc(),
                "read": Paper.last_read_at.desc(),
                "year": Paper.year.desc(),
                "title": Paper.title.asc(),
            }[sort]
            total = len(list(session.scalars(stmt)))
            rows = session.scalars(
                stmt.order_by(order, Paper.id).offset((page - 1) * page_size).limit(page_size)
            )
            return {"items": [serialize(session, p) for p in rows], "total": total, "page": page}

    @app.post("/api/v1/papers/upload")
    def upload(file: UploadFile):
        stage = config.path(f"staging/upload-{uid()}.pdf")
        stage.parent.mkdir(parents=True, exist_ok=True)
        try:
            size = 0
            with stage.open("wb") as output:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > config.max_upload_mb * 1024 * 1024:
                        raise HTTPException(413, "PDF 超过大小限制")
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            with import_lock, sessions() as session:
                paper, dedupe = ingest(config, session, stage, file.filename or "Untitled.pdf")
                if not dedupe and settings(session)["auto_convert_on_import"] and worker.executable():
                    worker.enqueue(session, paper)
                return {"paper": serialize(session, paper), "dedupe": dedupe}
        finally:
            stage.unlink(missing_ok=True)
            file.file.close()

    @app.post("/api/v1/papers/arxiv", status_code=202)
    def import_arxiv(body: ArxivInput):
        canonical, version = arxiv.parse(body.input)
        with import_lock, sessions() as session:
            paper = session.scalar(
                select(Paper).where(Paper.arxiv_id == canonical, Paper.arxiv_version == version)
            )
            dedupe = bool(paper)
            if not paper:
                paper = Paper(
                    id=uid(),
                    title=canonical,
                    arxiv_id=canonical,
                    arxiv_version=version,
                    source_url="https://arxiv.org/abs/" + canonical + (f"v{version}" if version else ""),
                    metadata_status="pending",
                )
                session.add(paper)
                session.commit()
            result = serialize(session, paper)
        if not dedupe:
            schedule_metadata(paper.id)
        return {"paper": result, "dedupe": dedupe}

    @app.get("/api/v1/papers/{paper_id}")
    def get_paper(paper_id: UUID):
        with sessions() as session:
            return serialize(session, paper_or_404(session, paper_id))

    @app.patch("/api/v1/papers/{paper_id}")
    def update_paper(paper_id: UUID, body: PaperPatch):
        with import_lock, sessions() as session:
            paper = paper_or_404(session, paper_id)
            for key, value in body.model_dump(exclude_unset=True).items():
                if key in ("tags", "collections"):
                    if value is None:
                        continue
                    model, association, fk = (
                        (Tag, paper_tags, "tag_id")
                        if key == "tags"
                        else (Collection, paper_collections, "collection_id")
                    )
                    session.execute(delete(association).where(association.c.paper_id == paper.id))
                    names = {}
                    for item in value:
                        if item.strip():
                            name = folder_name(item) if model == Collection else item.strip().casefold()
                            names[name.casefold()] = name
                    for name in names.values():
                        if len(name) > 80:
                            raise HTTPException(422, "标签或集合名称过长")
                        row = next(
                            (
                                r
                                for r in session.scalars(select(model))
                                if r.name.casefold() == name.casefold()
                            ),
                            None,
                        )
                        if not row:
                            row = model(id=uid(), name=name)
                            session.add(row)
                            session.flush()
                        session.execute(association.insert().values(paper_id=paper.id, **{fk: row.id}))
                elif value is not None or key in ("year", "source_url"):
                    setattr(paper, key, value)
            paper.updated_at = now()
            session.commit()
            folder_sync.request()
            return serialize(session, paper)

    @app.delete("/api/v1/papers/{paper_id}")
    def remove_paper(paper_id: UUID, confirm: bool = False):
        if not confirm:
            raise HTTPException(409, "需要明确确认删除此条目与所属本地文件")
        with worker.lock, import_lock, sessions() as session:
            paper = paper_or_404(session, paper_id)
            active = session.scalar(
                select(Job).where(Job.paper_id == paper.id, Job.status.in_(["queued", "running"]))
            )
            if active:
                raise HTTPException(409, "请先取消转换任务再删除")
            delete_assets(config, paper.id)
            session.delete(paper)
            session.commit()
        folder_sync.request()
        return {"deleted": True}

    @app.post("/api/v1/papers/{paper_id}/fetch-metadata", status_code=202)
    def fetch_metadata(paper_id: UUID):
        with sessions() as session:
            paper = paper_or_404(session, paper_id)
            if not paper.arxiv_id:
                raise HTTPException(409, "此论文没有 arXiv ID")
            paper.metadata_status = "pending"
            session.commit()
        schedule_metadata(str(paper_id))
        return {"status": "pending"}

    @app.post("/api/v1/papers/{paper_id}/download-pdf")
    def download_pdf(paper_id: UUID):
        with sessions() as session:
            paper = paper_or_404(session, paper_id)
            if paper.pdf_path:
                return {"paper": serialize(session, paper), "dedupe": True}
            if not paper.arxiv_id:
                raise HTTPException(409, "无可下载的 arXiv PDF")
            canonical = paper.arxiv_id + (f"v{paper.arxiv_version}" if paper.arxiv_version else "")
        stage = config.path(f"staging/download-{uid()}.pdf")
        stage.parent.mkdir(parents=True, exist_ok=True)
        try:
            with stage.open("wb") as output:
                arxiv.request(
                    "https://arxiv.org/pdf/" + canonical, config.max_upload_mb * 1024 * 1024, output
                )
            with import_lock, sessions() as session:
                paper = paper_or_404(session, paper_id)
                paper, dedupe = ingest(config, session, stage, canonical + ".pdf", paper)
                folder_sync.request()
                return {"paper": serialize(session, paper), "dedupe": dedupe}
        except (ValueError, __import__("httpx").HTTPError) as exc:
            raise HTTPException(502, "PDF 下载失败，请检查网络或稍后重试") from exc
        finally:
            stage.unlink(missing_ok=True)

    @app.get("/api/v1/papers/{paper_id}/pdf")
    def pdf(paper_id: UUID):
        with sessions() as session:
            paper = paper_or_404(session, paper_id)
            if not paper.pdf_path or not config.path(paper.pdf_path).is_file():
                raise HTTPException(404, "本地 PDF 不存在，请下载或重新导入")
            return FileResponse(
                config.path(paper.pdf_path),
                media_type="application/pdf",
                filename="paper.pdf",
                content_disposition_type="inline",
            )

    @app.post("/api/v1/papers/{paper_id}/open-official")
    def open_official(paper_id: UUID):
        with sessions() as session:
            paper = paper_or_404(session, paper_id)
            if not paper.official_html_url:
                raise HTTPException(409, "尚无经过验证的官方 HTML")
            paper.last_read_at = now()
            if paper.read_status == "unread":
                paper.read_status = "reading"
            session.commit()
            return {"official_html_url": paper.official_html_url, "progress_tracking": False}

    @app.get("/api/v1/papers/{paper_id}/html-status")
    def html_status(paper_id: UUID):
        with sessions() as session:
            paper = paper_or_404(session, paper_id)
            return {"official_html_url": paper.official_html_url, "has_local_html": bool(paper.html_path)}

    @app.post("/api/v1/papers/{paper_id}/conversions", status_code=202)
    def convert(paper_id: UUID, body: ConvertInput):
        with sessions() as session:
            job, cached = worker.enqueue(session, paper_or_404(session, paper_id), body.force_rebuild)
            return {"job": job_dict(job), "cached": cached}

    @app.get("/api/v1/conversions/{job_id}")
    def job_status(job_id: UUID):
        with sessions() as session:
            job = session.get(Job, str(job_id))
            if not job:
                raise HTTPException(404, "任务不存在")
            return job_dict(job)

    @app.post("/api/v1/conversions/{job_id}/{action}")
    def job_action(job_id: UUID, action: Literal["retry", "cancel"]):
        with sessions() as session:
            job = session.get(Job, str(job_id))
            if not job:
                raise HTTPException(404, "任务不存在")
            if action == "cancel":
                worker.cancel(session, job)
                return {"job": job_dict(job)}
            if job.status not in ("failed", "canceled"):
                raise HTTPException(409, "只能重试失败或已取消任务")
            new_job, cached = worker.enqueue(
                session, paper_or_404(session, job.paper_id), force=True, attempt=job.attempt + 1
            )
            return {"job": job_dict(new_job), "cached": cached}

    @app.get("/api/v1/papers/{paper_id}/reading-position")
    def read_position(paper_id: UUID, mode: Literal["pdf", "local_html"]):
        with sessions() as session:
            paper_or_404(session, paper_id)
            row = session.get(Position, (str(paper_id), mode))
            return ReadingPosition(
                **({c.name: getattr(row, c.name) for c in Position.__table__.columns} if row else {})
            )

    @app.put("/api/v1/papers/{paper_id}/reading-position")
    def save_position(paper_id: UUID, mode: Literal["pdf", "local_html"], body: ReadingPosition):
        with sessions() as session:
            paper = paper_or_404(session, paper_id)
            row = session.get(Position, (paper.id, mode)) or Position(paper_id=paper.id, mode=mode)
            for key, value in body.model_dump().items():
                setattr(row, key, value)
            row.updated_at = paper.last_read_at = now()
            if paper.read_status == "unread":
                paper.read_status = "reading"
            session.add(row)
            session.commit()
            return body

    def register_taxonomy(kind, model):
        def listing():
            with sessions() as session:
                return [
                    {
                        "id": row.id,
                        "name": row.name,
                        **(
                            {
                                "paper_count": len(
                                    list(
                                        session.scalars(
                                            select(paper_collections.c.paper_id).where(
                                                paper_collections.c.collection_id == row.id
                                            )
                                        )
                                    )
                                ),
                                "finder_path": str(folder_sync.directory(row)),
                            }
                            if model == Collection
                            else {}
                        ),
                    }
                    for row in session.scalars(select(model).order_by(model.name))
                ]

        def create(body: NameInput):
            with import_lock, sessions() as session:
                name = folder_name(body.name) if model == Collection else body.name.strip().casefold()
                if not name:
                    raise HTTPException(422, "名称不能为空")
                row = next(
                    (r for r in session.scalars(select(model)) if r.name.casefold() == name.casefold()), None
                )
                if not row:
                    row = model(id=uid(), name=name)
                    session.add(row)
                    session.commit()
                    if model == Collection:
                        folder_sync.request()
                return {"id": row.id, "name": row.name}

        def rename(item_id: UUID, body: NameInput):
            with import_lock, sessions() as session:
                row = session.get(model, str(item_id))
                if not row:
                    raise HTTPException(404, "分类不存在")
                name = folder_name(body.name) if model == Collection else body.name.strip().casefold()
                if any(
                    r.id != row.id and r.name.casefold() == name.casefold()
                    for r in session.scalars(select(model))
                ):
                    raise HTTPException(409, "名称已存在")
                row.name = name
                if not row.name:
                    raise HTTPException(422, "名称不能为空")
                try:
                    session.commit()
                except IntegrityError as exc:
                    raise HTTPException(409, "名称已存在") from exc
                if model == Collection:
                    folder_sync.request()
                return {"id": row.id, "name": row.name}

        def remove(item_id: UUID):
            with sessions() as session:
                row = session.get(model, str(item_id))
                if not row:
                    raise HTTPException(404, "分类不存在")
                session.delete(row)
                session.commit()
                if model == Collection:
                    folder_sync.request()
                return {"deleted": True}

        app.add_api_route("/api/v1/" + kind, listing, methods=["GET"])
        app.add_api_route("/api/v1/" + kind, create, methods=["POST"])
        app.add_api_route("/api/v1/" + kind + "/{item_id}", rename, methods=["PATCH"])
        app.add_api_route("/api/v1/" + kind + "/{item_id}", remove, methods=["DELETE"])

    register_taxonomy("tags", Tag)
    register_taxonomy("collections", Collection)

    @app.exception_handler(FolderConflict)
    async def invalid_folder(request, exc):
        return JSONResponse({"error": {"code": "FOLDER_CONFLICT", "message": str(exc)}}, 422)

    @app.post("/api/v1/collections/sync")
    def retry_folder_sync():
        folder_sync.request()
        return {"status": "queued"}

    @app.post("/api/v1/collections/{item_id}/reveal")
    def reveal_folder(item_id: UUID):
        import subprocess
        import sys

        with sessions() as session:
            row = session.get(Collection, str(item_id))
            if not row:
                raise HTTPException(404, "文件夹不存在")
            folder_sync.root  # Refuse a symlinked root before revealing any path.
            path = folder_sync.directory(row)
            if path.is_symlink() or not path.is_dir() or folder_sync.manifest(path)["id"] != row.id:
                raise HTTPException(409, "Finder 文件夹尚未同步，请等待或重试同步")
        if sys.platform != "darwin":
            raise HTTPException(501, "自动打开 Finder 仅支持 macOS")
        try:
            subprocess.run(["/usr/bin/open", str(path)], check=True, timeout=5, capture_output=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(503, "无法打开 Finder，请按显示的路径手动打开") from exc
        return {"opened": True}

    @app.get("/api/v1/settings")
    def get_settings():
        with sessions() as session:
            return settings(session) | {
                "marker_available": bool(worker.executable()),
                "data_dir": str(config.data_dir),
                "folders_root": str(config.data_dir / "folders"),
                "folder_sync": (
                    session.get(Setting, "folder_sync").value
                    if session.get(Setting, "folder_sync")
                    else {"status": "queued", "error": None}
                ),
            }

    @app.patch("/api/v1/settings")
    def patch_settings(body: SettingsPatch):
        with sessions() as session:
            for key, value in body.model_dump(exclude_none=True).items():
                row = session.get(Setting, key) or Setting(key=key)
                row.value = value
                session.add(row)
            session.commit()
            return settings(session)

    @app.get("/read/{paper_id}/html", response_class=HTMLResponse)
    def html_reader(paper_id: UUID):
        with sessions() as session:
            paper = paper_or_404(session, paper_id)
            if not paper.html_path or not config.path(paper.html_path).is_file():
                raise HTTPException(404, "尚无本地 HTML，请先转换")
            path = config.path(paper.html_path)
            manifest = json.loads((path.parent / "manifest.json").read_text())
            return HTMLResponse(reader_document(paper, path.read_text(), manifest, settings(session)))

    @app.get("/paper-assets/{paper_id}/{asset_id}")
    def asset(paper_id: UUID, asset_id: str):
        with sessions() as session:
            paper = paper_or_404(session, paper_id)
            if not paper.html_path:
                raise HTTPException(404, "资源不存在")
            base = config.path(paper.html_path).parent
            manifest = json.loads((base / "manifest.json").read_text())
            if asset_id not in manifest["assets"]:
                raise HTTPException(404, "资源不存在")
            path = (base / manifest["assets"][asset_id]).resolve()
            if not path.is_relative_to(base.resolve()) or not path.is_file():
                raise HTTPException(404, "资源不可用")
            return FileResponse(path, media_type="image/png")

    app.mount(
        "/reader-static", StaticFiles(directory=ROOT / "backend/app/reader_static"), name="reader-static"
    )
    dist = ROOT / "frontend/dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith(("api/", "paper-assets/", "read/")):
            raise HTTPException(404, "路由不存在")
        if path not in ("", "settings") and not re.fullmatch(r"papers/[0-9a-f-]{36}/pdf", path):
            raise HTTPException(404, "页面不存在")
        if (dist / "index.html").is_file():
            return FileResponse(dist / "index.html")
        return HTMLResponse("<h1>PaperFlow API ready</h1><p>Run make build or make dev to open Library.</p>")

    return app
