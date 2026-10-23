"""Peer endpoints require the shared bearer token, never browser cookies."""

import secrets
from uuid import UUID

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .db import Paper, now, uid
from .peer_sync import ConversionRequest, Snapshot


def peer_authorized(config, request):
    expected = config.sync_token.get_secret_value()
    supplied = request.headers.get("authorization", "")
    return (
        config.sync_enabled
        and len(expected) >= 32
        and not request.headers.get("origin")
        and secrets.compare_digest(supplied.encode(), ("Bearer " + expected).encode())
    )


def register_peer(app, peer):
    config, sessions = peer.config, peer.sessions

    @app.get("/api/v1/sync/status")
    def status():
        return peer.status()

    @app.post("/api/v1/sync/now", status_code=202)
    def synchronize():
        if not config.sync_enabled:
            raise HTTPException(409, "请先在 .env 中配置双机同步")
        peer.wake.set()
        return {"status": "queued"}

    @app.get("/api/v1/papers/{paper_id}/device-positions")
    def positions(paper_id: UUID):
        with peer.worker.lock, peer.lock, sessions() as session:
            if not session.get(Paper, str(paper_id)):
                raise HTTPException(404, "论文不存在")
            if not config.sync_enabled:
                return []
            peer.capture(session)
            result = [
                {
                    "device_id": key.split("/")[3],
                    "mode": key.split("/")[2],
                    "position": record.value,
                    "local": key.split("/")[3] == peer.device,
                }
                for key, record in peer.winners(session).items()
                if key.startswith(f"position/{paper_id}/") and record.value
            ]
            session.commit()
            return result

    @app.get("/peer/v1/snapshot")
    def snapshot():
        with peer.worker.lock, peer.lock, sessions() as session:
            result = peer.snapshot(session)
            session.commit()
            return result

    @app.post("/peer/v1/exchange")
    def exchange(packet: Snapshot):
        with peer.worker.lock, peer.lock, sessions() as session:
            peer.merge(session, packet)
            needed = [
                asset.model_dump()
                for asset in packet.assets
                if not peer.asset_path(session, asset.kind, asset.digest)
            ]
            result = peer.snapshot(session)
            peer.commit(session)
        peer.online, peer.error, peer.last_success = True, None, now()
        peer.folders.request()
        return {"snapshot": result, "needed": needed}

    @app.get("/peer/v1/assets/{kind}/{digest}")
    def download(kind: str, digest: str):
        with sessions() as session:
            path = peer.asset_path(session, kind, digest)
            if not path:
                raise HTTPException(404, "资源不存在")
            return FileResponse(path, media_type="application/octet-stream")

    @app.put("/peer/v1/assets/{kind}/{digest}")
    async def upload(kind: str, digest: str, request: Request):
        peer.blob_path(kind, digest)
        stage = config.path("staging/peer-upload-" + uid())
        stage.parent.mkdir(parents=True, exist_ok=True)
        try:
            size = 0
            with stage.open("wb") as output:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > config.max_upload_mb * 1024**2:
                        raise HTTPException(413, "同步资源超过大小限制")
                    output.write(chunk)
            peer.receive_asset(kind, digest, stage)
            # Blocking file work/locks run in a worker thread, not the ASGI loop.
            from starlette.concurrency import run_in_threadpool

            def install():
                with peer.worker.lock, peer.lock, sessions() as session:
                    peer.capture(session)
                    peer.materialize_assets(session)
                    peer.baseline(session, peer.values(session))
                    session.commit()
                peer.folders.request()

            await run_in_threadpool(install)
            return {"stored": True}
        finally:
            stage.unlink(missing_ok=True)

    @app.post("/peer/v1/conversions")
    def conversion(body: ConversionRequest):
        with peer.worker.lock, peer.lock, sessions() as session:
            return peer.accept_conversion(session, body)


def rejected_peer():
    return JSONResponse({"error": {"code": "PEER_UNAUTHORIZED", "message": "设备未配对或请求来源无效"}}, 403)
