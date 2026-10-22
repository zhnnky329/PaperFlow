"""Regression cases found during the final Discovery integration review."""

import pytest
from fastapi.testclient import TestClient

from app import discovery_ai, discovery_feed
from app.db import DiscoveryPaper, DiscoveryRun, Paper, uid

BASE = "/api/v1/discovery"


@pytest.fixture
def review_client(app):
    app.state.config.discovery_online = True
    app.state.config.metadata_online = False
    client = TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        headers={"Origin": "http://127.0.0.1:8000", "X-PaperFlow": "1"},
    )
    try:
        yield client
    finally:
        client.close()
        app.state.sessions.kw["bind"].dispose()


def add_candidate(session, identifier, **overrides):
    row = DiscoveryPaper(
        id=uid(),
        arxiv_id=identifier,
        arxiv_version=1,
        title="Active visual perception for UAV tracking",
        abstract="A robot perception method.",
        categories=["cs.RO"],
        published_at="2026-10-19T10:00:00+00:00",
        updated_at="2026-10-19T10:00:00+00:00",
        source_url=f"https://arxiv.org/abs/{identifier}v1",
        content_hash=identifier,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    session.add(row)
    return row


def test_import_checks_library_for_discovery_aliases(review_client):
    client = review_client
    with client.app.state.sessions() as session:
        existing = Paper(
            id=uid(), title="Existing alias", arxiv_id="2610.00002", arxiv_version=0
        )
        session.add(existing)
        row = add_candidate(
            session, "2610.00001", doi="10.1234/same", arxiv_aliases=["2610.00002"]
        )
        session.commit()
        row_id, existing_id = row.id, existing.id
    response = client.post(BASE + "/papers/" + row_id + "/import")
    assert response.status_code == 202, response.text
    assert response.json()["dedupe"] is True
    assert response.json()["paper"]["id"] == existing_id
    assert client.get("/api/v1/papers").json()["total"] == 1


@pytest.mark.parametrize("disable", ["ai", "key"])
def test_revoking_ai_authorization_stops_remaining_batch_calls(
    review_client, monkeypatch, disable
):
    client = review_client
    assert (
        client.post(
            BASE + "/api-key", json={"api_key": "review-test-secret"}
        ).status_code
        == 200
    )
    assert (
        client.patch(BASE + "/settings", json={"ai_enabled": True}).status_code == 200
    )
    with client.app.state.sessions() as session:
        add_candidate(session, "2610.00001")
        add_candidate(session, "2610.00002")
        session.commit()
    monkeypatch.setattr(
        discovery_ai,
        "fetch_content",
        lambda *a, **kw: {
            "text": "A robot perception method.",
            "basis": "abstract",
            "source_url": None,
        },
    )
    monkeypatch.setattr(discovery_ai, "estimate_tokens", lambda *a, **kw: 1000)
    calls = []

    def analyze(*args, **kwargs):
        calls.append(args[0]["arxiv_id"])
        if len(calls) == 1:
            if disable == "ai":
                response = client.patch(BASE + "/settings", json={"ai_enabled": False})
            else:
                response = client.post(BASE + "/api-key", json={"api_key": ""})
            assert response.status_code == 200
        return {
            "decision": "recommend",
            "score": 80,
            "matched_directions": ["uav"],
            "summary": "协议测试内容。",
            "reason": "方向相关",
            "basis": "abstract",
            "source_url": None,
            "tokens_used": 200,
        }

    monkeypatch.setattr(discovery_ai, "analyze", analyze)
    worker = client.app.state.discovery
    worker.stop_event.clear()
    run, _ = worker.enqueue("manual", {"analysis_only": True})
    worker.execute(run["id"])
    assert len(calls) == 1


def test_clear_key_while_retrieving_body_prevents_paid_call_and_reservation(
    review_client, monkeypatch
):
    client = review_client
    client.post(BASE + "/api-key", json={"api_key": "review-test-secret"})
    client.patch(BASE + "/settings", json={"ai_enabled": True})
    with client.app.state.sessions() as session:
        add_candidate(session, "2610.00001")
        session.commit()

    def retrieve(*args, **kwargs):
        assert client.post(BASE + "/api-key", json={"api_key": ""}).status_code == 200
        return {"text": "Paper body", "basis": "partial_text", "source_url": None}

    monkeypatch.setattr(discovery_ai, "fetch_content", retrieve)
    monkeypatch.setattr(
        discovery_ai,
        "analyze",
        lambda *a, **kw: pytest.fail("authorization was revoked"),
    )
    worker = client.app.state.discovery
    run, _ = worker.enqueue("manual", {"analysis_only": True})
    worker.execute(run["id"])
    with worker.sessions() as session:
        assert session.get(DiscoveryRun, run["id"]).tokens_reserved == 0


def test_orphan_analysis_keeps_reservation_and_requires_explicit_retry(
    review_client, monkeypatch
):
    client = review_client
    client.post(BASE + "/api-key", json={"api_key": "review-test-secret"})
    client.patch(BASE + "/settings", json={"ai_enabled": True})
    worker = client.app.state.discovery
    with worker.sessions() as session:
        interrupted = DiscoveryRun(
            id=uid(), trigger="manual", status="running", tokens_reserved=1200
        )
        row = add_candidate(session, "2610.00001", analysis_status="running")
        session.add(interrupted)
        session.commit()
        run_id, paper_id = interrupted.id, row.id
    # Run the real recovery logic without starting any network loop.
    worker.stop_event.set()
    worker.start()
    worker.thread.join(timeout=2)
    with worker.sessions() as session:
        assert session.get(DiscoveryRun, run_id).status == "failed"
        assert session.get(DiscoveryRun, run_id).tokens_reserved == 1200
        assert session.get(DiscoveryPaper, paper_id).analysis_status == "failed"
    monkeypatch.setattr(
        discovery_feed,
        "fetch_candidates",
        lambda **kw: {
            "candidates": [],
            "complete": True,
            "next_start": None,
        },
    )
    monkeypatch.setattr(
        discovery_ai,
        "fetch_content",
        lambda *a, **kw: {
            "text": "A robot perception method.",
            "basis": "abstract",
            "source_url": None,
        },
    )
    monkeypatch.setattr(discovery_ai, "estimate_tokens", lambda *a, **kw: 1000)
    calls = []

    def analyze(*args, **kwargs):
        calls.append(args[0]["arxiv_id"])
        with worker.sessions() as session:
            assert session.get(DiscoveryPaper, paper_id).analysis_status == "running"
        return {
            "decision": "skip",
            "score": 10,
            "matched_directions": [],
            "summary": "协议测试内容。",
            "reason": "方向不相关",
            "basis": "abstract",
            "source_url": None,
            "tokens_used": 200,
        }

    monkeypatch.setattr(discovery_ai, "analyze", analyze)
    worker.stop_event.clear()
    automatic, _ = worker.enqueue("scheduled")
    worker.execute(automatic["id"])
    assert calls == []
    retry = client.post(BASE + "/runs/" + run_id + "/retry")
    assert retry.status_code == 202
    worker.execute(retry.json()["run"]["id"])
    assert calls == ["2610.00001"]


def test_discovery_import_reuses_verified_metadata_without_queueing_network(
    review_client, monkeypatch
):
    client = review_client
    # Feed metadata and the HTML URL were verified before this explicit import.
    # Import must not repeat them through the Library's serial metadata queue.
    client.app.state.config.metadata_online = True
    from app import metadata

    monkeypatch.setattr(
        metadata, "refresh", lambda *a, **kw: pytest.fail("redundant metadata fetch")
    )
    with client.app.state.sessions() as session:
        row = add_candidate(
            session,
            "2610.00001",
            analysis_status="succeeded",
            analysis={
                "basis": "partial_text",
                "source_url": "https://arxiv.org/html/2610.00001v1",
            },
        )
        session.commit()
        row_id = row.id
    response = client.post(BASE + "/papers/" + row_id + "/import")
    assert response.status_code == 202, response.text
    paper = response.json()["paper"]
    assert paper["metadata_status"] == "ready" and paper["arxiv_version"] == 1
    assert paper["official_html_url"] == "https://arxiv.org/html/2610.00001v1"
    assert paper["title"] == "Active visual perception for UAV tracking"
    assert not paper["has_pdf"]
    assert client.get("/api/v1/papers/" + paper["id"]).json()["metadata_status"] == "ready"
