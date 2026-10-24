"""Remote conversion completion must refer to the installed result generation."""

import httpx
import pytest

from app.db import Job, Paper, PeerReceipt, RemoteConversion, now
from app.worker import Worker
from test_peer_sync import LOCAL, PEER, devices, upload
from test_worker_html import fake_cli


def request_remote(client, paper_id, force=False):
    response = client.post(
        f"/api/v1/papers/{paper_id}/conversions",
        json={"target": "ubuntu", "force_rebuild": force},
        headers=LOCAL,
    )
    assert response.status_code == 202, response.text
    return response.json()["job"]["id"]


def finish_on_executor(peer, request_id):
    # Drive the real subprocess synchronously, without timing-sensitive polling.
    with peer.sessions() as session:
        receipt = session.get(PeerReceipt, request_id)
        job = session.get(Job, receipt.job_id)
        assert job.status == "queued"
        identifier = job.id
        job.status, job.started_at = "running", now()
        session.commit()
    peer.worker.convert(identifier)
    with peer.sessions() as session:
        assert session.get(Job, identifier).status == "succeeded"


def observe_completion(peer):
    # A task can finish between the first exchange and its status request.
    with httpx.Client(
        base_url=peer.config.sync_peer_url, transport=peer.transport, headers=PEER
    ) as client:
        peer.process_requests(client)


def test_rebuild_download_failure_keeps_old_html_until_new_result_is_installed(
    tmp_path, monkeypatch, pdf_bytes
):
    monkeypatch.setattr(Worker, "run", lambda self: None)
    executable = tmp_path / "marker"
    fake_cli(executable)
    with devices(tmp_path, monkeypatch, executable) as (mac, ubuntu, peer, other):
        paper_id = upload(mac, pdf_bytes)["id"]
        first = request_remote(mac, paper_id)
        peer.once()
        finish_on_executor(other, first)
        observe_completion(peer)
        peer.once()
        peer.once()
        assert mac.get(f"/api/v1/conversions/{first}").json()["status"] == "succeeded"
        old_html = mac.get(f"/read/{paper_id}/html").text
        assert "Safe Article" in old_html
        with peer.sessions() as session:
            old_path = session.get(Paper, paper_id).html_path

        executable.write_text(executable.read_text().replace("Safe Article", "Rebuilt Article"))
        rebuilt = request_remote(mac, paper_id, force=True)
        peer.once()
        finish_on_executor(other, rebuilt)
        observe_completion(peer)
        with other.sessions() as session:
            result = other.winners(session)[f"html/{paper_id}"].value
        assert result["digest"] not in old_path
        original_transport = peer.transport
        failed_downloads = []

        def fail_new_html(request):
            if request.method == "GET" and request.url.path == f"/peer/v1/assets/html/{result['digest']}":
                failed_downloads.append(request.url.path)
                return httpx.Response(503)
            return original_transport.handle_request(request)

        peer.transport = httpx.MockTransport(fail_new_html)
        with pytest.raises(httpx.HTTPStatusError):
            peer.once()
        assert failed_downloads
        state = mac.get(f"/api/v1/conversions/{rebuilt}").json()
        assert (state["status"], state["progress_stage"]) == ("running", "downloading")
        assert state["finished_at"] is None
        assert mac.get(f"/read/{paper_id}/html").text == old_html
        assert mac.get(f"/api/v1/papers/{paper_id}/pdf").content == pdf_bytes
        with peer.sessions() as session:
            assert session.get(Paper, paper_id).html_path == old_path

        peer.transport = original_transport
        peer.once()
        peer.once()
        state = mac.get(f"/api/v1/conversions/{rebuilt}").json()
        assert (state["status"], state["progress_stage"]) == ("succeeded", "complete")
        assert state["finished_at"]
        reader = mac.get(f"/read/{paper_id}/html")
        assert reader.status_code == 200 and "Rebuilt Article" in reader.text
        assert "Safe Article" not in reader.text
        with peer.sessions() as session:
            paper = session.get(Paper, paper_id)
            job = session.get(RemoteConversion, rebuilt)
            assert paper.html_path == f"papers/{paper_id}/derivatives/peer/{result['digest']}/article.html"
            assert paper.pdf_sha256 == result["pdf_sha256"] == job.payload["pdf_sha256"]


def test_newer_conversion_still_supersedes_result_waiting_for_download(
    tmp_path, monkeypatch, pdf_bytes
):
    monkeypatch.setattr(Worker, "run", lambda self: None)
    executable = tmp_path / "marker"
    fake_cli(executable)
    with devices(tmp_path, monkeypatch, executable) as (mac, ubuntu, peer, other):
        paper_id = upload(mac, pdf_bytes)["id"]
        remote = request_remote(mac, paper_id)
        peer.once()
        finish_on_executor(other, remote)
        observe_completion(peer)
        # A later local rebuild owns the generation before the Mac downloads the old result.
        response = ubuntu.post(
            f"/api/v1/papers/{paper_id}/conversions",
            json={"force_rebuild": True},
            headers=LOCAL,
        )
        assert response.status_code == 202, response.text
        newer = response.json()["job"]["id"]
        peer.once()
        state = mac.get(f"/api/v1/conversions/{remote}").json()
        assert (state["status"], state["progress_stage"]) == ("succeeded", "superseded")
        assert state["finished_at"]
        assert ubuntu.get(f"/api/v1/conversions/{newer}").json()["status"] == "queued"
