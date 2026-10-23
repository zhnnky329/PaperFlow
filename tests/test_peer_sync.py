"""Exercise two independent libraries over the real peer HTTP protocol."""

import hashlib
import io
import json
import time
import zipfile
from contextlib import contextmanager

import httpx
import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.operations import Operations
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select, text

from app.config import Config, ROOT
from app.db import Job, Paper, PeerReceipt, RemoteConversion, Setting, SyncRecord, uid
from app.main import create_app
from app.peer_sync import ConversionRequest, PeerSync, Snapshot
from test_worker_html import fake_cli

TOKEN = "test-pair-secret-" + "x" * 40
LOCAL = {"Origin": "http://127.0.0.1:8000", "X-PaperFlow": "1"}
PEER = {"Authorization": "Bearer " + TOKEN}


@contextmanager
def devices(tmp_path, monkeypatch, executable="/missing/marker"):
    # Scheduling is driven explicitly; subprocess conversion remains real.
    monkeypatch.setattr(PeerSync, "start", lambda self: None)
    common = dict(
        sync_enabled=True,
        sync_token=TOKEN,
        max_upload_mb=2,
        metadata_online=False,
        discovery_online=False,
        sync_interval=3600,
    )
    mac = create_app(
        Config(
            data_dir=tmp_path / "mac",
            marker_executable="/missing/marker",
            sync_peer_url="http://127.0.0.1:8001",
            **common,
        )
    )
    ubuntu = create_app(
        Config(
            data_dir=tmp_path / "ubuntu",
            marker_executable=str(executable),
            sync_accept_conversions=True,
            **common,
        )
    )
    with TestClient(mac, base_url="http://127.0.0.1:8000") as left:
        with TestClient(ubuntu, base_url="http://127.0.0.1:8000") as right:

            def transport(request):
                response = right.request(
                    request.method,
                    request.url.path,
                    content=request.read(),
                    headers=dict(request.headers),
                )
                return httpx.Response(
                    response.status_code,
                    content=response.content,
                    headers=response.headers,
                )

            mac.state.peer.transport = httpx.MockTransport(transport)
            yield left, right, mac.state.peer, ubuntu.state.peer


def upload(client, content):
    response = client.post(
        "/api/v1/papers/upload", files={"file": ("paper.pdf", content)}, headers=LOCAL
    )
    assert response.status_code == 200, response.text
    return response.json()["paper"]


def patch(client, paper_id, **values):
    response = client.patch(f"/api/v1/papers/{paper_id}", json=values, headers=LOCAL)
    assert response.status_code == 200, response.text
    return response.json()


def papers(client):
    return client.get("/api/v1/papers").json()["items"]


def wait_remote(peer, client, job_id):
    for _ in range(40):
        peer.once()
        job = client.get(f"/api/v1/conversions/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.03)
    raise AssertionError("Remote conversion did not finish")


def test_bidirectional_library_fields_edges_and_deletion(
    tmp_path, monkeypatch, pdf_bytes
):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        parent = mac.post(
            "/api/v1/collections", json={"name": "Robotics"}, headers=LOCAL
        ).json()
        child = mac.post(
            "/api/v1/collections",
            json={"name": "SLAM", "parent_id": parent["id"]},
            headers=LOCAL,
        ).json()
        patch(mac, paper["id"], tags=["navigation"], collection_ids=[child["id"]])
        peer.once()
        mirrored = papers(ubuntu)[0]
        assert mirrored["id"] == paper["id"] and mirrored["has_pdf"]
        assert mirrored["tags"][0]["name"] == "navigation"
        assert mirrored["collections"][0]["path"] == "Robotics/SLAM"
        assert ubuntu.get(f"/api/v1/papers/{paper['id']}/pdf").content == pdf_bytes
        # Independent offline changes to different fields survive the exchange.
        patch(mac, paper["id"], title="Mac title")
        patch(ubuntu, paper["id"], read_status="finished")
        peer.once()
        assert papers(mac)[0]["read_status"] == "finished"
        assert papers(ubuntu)[0]["title"] == "Mac title"
        response = ubuntu.delete(
            f"/api/v1/papers/{paper['id']}?confirm=true", headers=LOCAL
        )
        assert response.status_code == 200
        peer.once()
        peer.once()
        assert papers(mac) == papers(ubuntu) == []
        assert not peer.config.path(f"papers/{paper['id']}").exists()
        assert peer.device != other.device


def test_existing_duplicate_pdfs_keep_local_ids_and_rewrite_html(
    tmp_path, monkeypatch, pdf_bytes
):
    executable = tmp_path / "marker"
    fake_cli(executable)
    with devices(tmp_path, monkeypatch, executable) as (mac, ubuntu, peer, other):
        left, right = upload(mac, pdf_bytes), upload(ubuntu, pdf_bytes)
        assert left["id"] != right["id"]
        peer.once()
        assert len(papers(mac)) == len(papers(ubuntu)) == 1
        assert papers(mac)[0]["id"] == left["id"]
        assert papers(ubuntu)[0]["id"] == right["id"]
        patch(mac, left["id"], title="Deduplicated")
        peer.once()
        assert papers(ubuntu)[0]["title"] == "Deduplicated"
        job = mac.post(
            f"/api/v1/papers/{left['id']}/conversions",
            json={"target": "ubuntu"},
            headers=LOCAL,
        ).json()["job"]
        assert wait_remote(peer, mac, job["id"])["status"] == "succeeded"
        assert mac.get(f"/read/{left['id']}/html").status_code == 200


def test_remote_conversion_without_local_marker_is_durable_and_idempotent(
    tmp_path, monkeypatch, pdf_bytes
):
    executable = tmp_path / "marker"
    fake_cli(executable, slow=True)
    with devices(tmp_path, monkeypatch, executable) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        local = mac.post(
            f"/api/v1/papers/{paper['id']}/conversions", json={}, headers=LOCAL
        )
        assert local.status_code == 503
        remote = mac.post(
            f"/api/v1/papers/{paper['id']}/conversions",
            json={"target": "ubuntu"},
            headers=LOCAL,
        )
        assert remote.status_code == 202
        job = remote.json()["job"]
        with peer.sessions() as session:
            assert session.get(RemoteConversion, job["id"]).status == "queued"
        # Repeat delivery over HTTP; both responses refer to one persisted job.
        peer.once()
        peer.once()
        with other.sessions() as session:
            assert len(list(session.scalars(select(Job)))) == 1
            assert session.get(PeerReceipt, job["id"])
        canceled = mac.post(
            f"/api/v1/conversions/{job['id']}/cancel", headers=LOCAL
        ).json()["job"]
        assert canceled["cancel_requested"] and canceled["status"] != "canceled"
        assert wait_remote(peer, mac, job["id"])["status"] == "canceled"
        # Retrying uses Ubuntu again, even though Mac has no Marker.
        fake_cli(executable)
        retry = mac.post(
            f"/api/v1/conversions/{job['id']}/retry", headers=LOCAL
        ).json()["job"]
        assert retry["execution_target"] == "ubuntu" and retry["attempt"] == 2
        assert wait_remote(peer, mac, retry["id"])["status"] == "succeeded"
        assert papers(mac)[0]["has_html"]
        assert "Safe Article" in mac.get(f"/read/{paper['id']}/html").text


def test_cancel_before_first_delivery_never_starts_marker(
    tmp_path, monkeypatch, pdf_bytes
):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        job = mac.post(
            f"/api/v1/papers/{paper['id']}/conversions",
            json={"target": "ubuntu"},
            headers=LOCAL,
        ).json()["job"]
        mac.post(f"/api/v1/conversions/{job['id']}/cancel", headers=LOCAL)
        assert wait_remote(peer, mac, job["id"])["status"] == "canceled"
        with other.sessions() as session:
            assert not list(session.scalars(select(Job)))


def test_positions_preserve_zoom_and_reject_stale_reader(
    tmp_path, monkeypatch, pdf_bytes
):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        peer.once()
        endpoint = f"/api/v1/papers/{paper['id']}/reading-position?mode=pdf"
        initial = mac.get(endpoint).json()
        mac.put(
            endpoint,
            json={"pdf_page": 3, "pdf_scale": 1.8, "revision": initial["revision"]},
            headers=LOCAL,
        )
        peer.once()
        assert ubuntu.get(endpoint).json()["pdf_page"] == 3
        assert ubuntu.get(endpoint).json()["pdf_scale"] == 1
        before = mac.get(endpoint).json()
        ubuntu.put(endpoint, json={"pdf_page": 10}, headers=LOCAL)
        peer.once()
        assert mac.get(endpoint).json()["pdf_page"] == 10
        assert mac.get(endpoint).json()["pdf_scale"] == 1.8
        assert (
            mac.put(
                endpoint,
                json={"pdf_page": 3, "revision": before["revision"]},
                headers=LOCAL,
            ).status_code
            == 409
        )
        positions = mac.get(f"/api/v1/papers/{paper['id']}/device-positions").json()
        assert {p["position"]["pdf_page"] for p in positions} == {3, 10}


def test_sync_excludes_settings_discovery_and_keys(tmp_path, monkeypatch, pdf_bytes):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        upload(mac, pdf_bytes)
        with peer.sessions() as session:
            session.add(
                Setting(key="research_discovery", value={"interests": ["private"]})
            )
            session.add(Setting(key="theme", value="dark"))
            session.commit()
            packet = peer.snapshot(session)
            session.commit()
        assert "private" not in json.dumps(packet)
        peer.once()
        with other.sessions() as session:
            assert session.get(Setting, "research_discovery") is None
            assert session.get(Setting, "theme") is None
        assert TOKEN not in json.dumps(mac.get("/api/v1/sync/status").json())


def test_peer_auth_host_isolation_and_invalid_records(tmp_path, monkeypatch):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        assert ubuntu.get("/peer/v1/snapshot").status_code == 403
        assert (
            ubuntu.get(
                "/peer/v1/snapshot", headers={**PEER, "Origin": "https://evil.test"}
            ).status_code
            == 403
        )
        assert (
            ubuntu.get(
                "/api/v1/papers", headers={**PEER, "Host": "ubuntu.example"}
            ).status_code
            == 403
        )
        packet = ubuntu.get(
            "/peer/v1/snapshot", headers={**PEER, "Host": "ubuntu.example"}
        ).json()
        assert packet["device"] == other.device
        packet["device"] = peer.device
        packet["records"] = [
            {
                "key": f"paper/{uid()}/pdf_path",
                "clock": 1,
                "device": peer.device,
                "value": "/etc/passwd",
            }
        ]
        assert (
            ubuntu.post("/peer/v1/exchange", json=packet, headers=PEER).status_code
            == 422
        )
        digest = "0" * 64
        assert (
            ubuntu.put(
                f"/peer/v1/assets/pdf/{digest}", content=b"wrong", headers=PEER
            ).status_code
            == 422
        )


def test_html_zip_path_traversal_and_image_rewrite(tmp_path, monkeypatch, pdf_bytes):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        stage = tmp_path / "bundle.zip"
        with zipfile.ZipFile(stage, "w") as archive:
            archive.writestr("article.html", "<p>long enough readable article text</p>")
            archive.writestr("manifest.json", '{"assets":{}}')
            archive.writestr("../escape", "no")
        with pytest.raises(HTTPException):
            peer.install_html(stage, tmp_path / "bad", paper["id"])
        image = io.BytesIO()
        Image.new("RGB", (10, 10), "red").save(image, "PNG")
        with zipfile.ZipFile(stage, "w") as archive:
            archive.writestr(
                "article.html",
                f"<h1>Article with images</h1><p>Readable paper content.</p>"
                f'<img src="/paper-assets/{uid()}/asset-0.png">',
            )
            archive.writestr(
                "manifest.json", '{"assets":{"asset-0.png":"asset-0.png"}}'
            )
            archive.writestr("asset-0.png", image.getvalue())
        peer.install_html(stage, tmp_path / "good", paper["id"])
        assert (
            f"/paper-assets/{paper['id']}/asset-0.png"
            in (tmp_path / "good/article.html").read_text()
        )


def test_late_result_cannot_replace_newer_generation(tmp_path, monkeypatch, pdf_bytes):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        raw = tmp_path / "result"
        raw.mkdir()
        (raw / "article.html").write_text("<p>Already sanitized conversion output.</p>")
        (raw / "manifest.json").write_text('{"assets":{},"toc":[]}')
        with peer.sessions() as session:
            row = session.get(Paper, paper["id"])
            peer.capture(session)
            old = Job(id=uid(), paper_id=row.id, fingerprint="old", settings={})
            new = Job(id=uid(), paper_id=row.id, fingerprint="new", settings={})
            peer.reserve(session, row, old)
            peer.reserve(session, row, new)
            assert peer.complete(session, row, new, raw)
            assert not peer.complete(session, row, old, raw)
            session.rollback()


def test_configuration_and_same_device_detection(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        Config(sync_enabled=True, sync_token="short")
    with pytest.raises(ValueError):
        Config(sync_peer_url="http://public.example")
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        packet = ubuntu.get("/peer/v1/snapshot", headers=PEER).json()
        assert (
            ubuntu.post("/peer/v1/exchange", json=packet, headers=PEER).status_code
            == 409
        )
        with peer.sessions() as session:
            clock = peer.clock(session)
            session.add(
                SyncRecord(
                    key=f"paper/{uid()}/title",
                    value="future",
                    clock=clock + 100,
                    device=other.device,
                    phase=0,
                )
            )
            session.commit()
            assert peer.clock(session) > clock + 100
        with pytest.raises(ValueError):
            Snapshot.model_validate({"protocol": 2, "device": uid()})


def test_content_hash_identity_is_checked(tmp_path, monkeypatch, pdf_bytes):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        peer.once()
        request = ConversionRequest(
            id=uid(),
            paper_id=paper["id"],
            pdf_sha256=hashlib.sha256(b"other").hexdigest(),
            mode="fast",
            clock=100,
            device=peer.device,
        )
        assert (
            ubuntu.post(
                "/peer/v1/conversions",
                json=request.model_dump(mode="json"),
                headers=PEER,
            ).status_code
            == 409
        )


def test_offline_outbox_and_device_identity_survive_restart(
    tmp_path, monkeypatch, pdf_bytes
):
    executable = tmp_path / "marker"
    fake_cli(executable)
    with devices(tmp_path, monkeypatch, executable) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        device_id = peer.device
        job = mac.post(
            f"/api/v1/papers/{paper['id']}/conversions",
            json={"target": "ubuntu"},
            headers=LOCAL,
        ).json()["job"]
        assert papers(ubuntu) == []
    with devices(tmp_path, monkeypatch, executable) as (mac, ubuntu, peer, other):
        assert peer.device == device_id
        assert wait_remote(peer, mac, job["id"])["status"] == "succeeded"
        assert len(papers(ubuntu)) == 1
        with other.sessions() as session:
            assert len(list(session.scalars(select(Job)))) == 1


def test_executor_finishes_without_client_polling_and_reuses_cache(
    tmp_path, monkeypatch, pdf_bytes
):
    executable = tmp_path / "marker"
    fake_cli(executable)
    with devices(tmp_path, monkeypatch, executable) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        first = mac.post(
            f"/api/v1/papers/{paper['id']}/conversions",
            json={"target": "ubuntu"},
            headers=LOCAL,
        ).json()["job"]
        peer.once()
        for _ in range(100):
            with other.sessions() as session:
                receipt = session.get(PeerReceipt, first["id"])
                actual = session.get(Job, receipt.job_id or first["id"])
                finished = actual.status == "succeeded"
            if finished:
                break
            time.sleep(0.02)
        assert finished
        assert wait_remote(peer, mac, first["id"])["status"] == "succeeded"
        second = mac.post(
            f"/api/v1/papers/{paper['id']}/conversions",
            json={"target": "ubuntu"},
            headers=LOCAL,
        ).json()["job"]
        assert wait_remote(peer, mac, second["id"])["status"] == "succeeded"
        with other.sessions() as session:
            assert len(list(session.scalars(select(Job)))) == 1


def test_concurrent_same_field_converges_without_clock_ping_pong(
    tmp_path, monkeypatch, pdf_bytes
):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        peer.once()
        patch(mac, paper["id"], title="Mac concurrent title")
        patch(ubuntu, paper["id"], title="Ubuntu concurrent title")
        for device in (peer, other):
            with device.sessions() as session:
                device.capture(session)
                session.commit()
        peer.once()
        assert papers(mac)[0]["title"] == papers(ubuntu)[0]["title"]
        with peer.sessions() as session:
            before = max(session.scalars(select(SyncRecord.clock)))
        peer.once()
        peer.once()
        with peer.sessions() as session:
            assert max(session.scalars(select(SyncRecord.clock))) == before


def test_edit_during_asset_upload_is_not_absorbed_into_baseline(tmp_path, monkeypatch, pdf_bytes):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        original = peer.transport

        def edit_while_uploading(request):
            if request.method == "PUT" and "/assets/pdf/" in request.url.path:
                patch(ubuntu, paper["id"], title="Edited during PDF transfer")
            return original.handle_request(request)

        peer.transport = httpx.MockTransport(edit_while_uploading)
        peer.once()
        assert papers(mac)[0]["title"] == "Edited during PDF transfer"
        peer.once()
        assert papers(ubuntu)[0]["title"] == "Edited during PDF transfer"


def test_interrupted_sync_migration_rolls_back_and_can_restart(tmp_path, monkeypatch):
    config = Config(data_dir=tmp_path / "migration", discovery_online=False)
    config.data_dir.mkdir()
    engine = create_engine("sqlite:///" + str(config.data_dir / "paperflow.sqlite3"))
    migration = AlembicConfig(str(ROOT / "backend/alembic.ini"))
    migration.set_main_option("script_location", str(ROOT / "backend/alembic"))
    with engine.begin() as connection:
        migration.attributes["connection"] = connection
        command.upgrade(migration, "0004")
    original = Operations.create_table

    def interrupt(operation, name, *args, **kwargs):
        if name == "sync_aliases":
            raise RuntimeError("Injected peer migration interruption")
        return original(operation, name, *args, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(Operations, "create_table", interrupt)
        with pytest.raises(RuntimeError, match="Injected peer"):
            create_app(config)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0004"
        assert connection.execute(text("SELECT name FROM sqlite_master WHERE name LIKE 'sync_%'")).all() == []
    restarted = create_app(config)
    with restarted.state.sessions() as session:
        assert session.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0005"
    restarted.state.sessions.kw["bind"].dispose()
    engine.dispose()
