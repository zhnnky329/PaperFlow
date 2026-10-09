from fastapi.testclient import TestClient
from app.main import create_app
from app import arxiv
import pytest


def upload(client, data):
    response = client.post("/api/v1/papers/upload", files={"file": ("paper.pdf", data, "application/pdf")})
    assert response.status_code == 200, response.text
    return response.json()["paper"]


def test_health_empty_and_missing_marker(client):
    assert client.get("/api/v1/health").json() == {
        "status": "ok",
        "database": "ok",
        "marker_available": False,
    }
    assert client.get("/api/v1/papers").json()["items"] == []


def test_upload_dedupe_search_classification_restart(client, pdf_bytes, config):
    paper = upload(client, pdf_bytes)
    assert paper["title"] == "Test Research"
    duplicate = client.post("/api/v1/papers/upload", files={"file": ("renamed.pdf", pdf_bytes)}).json()
    assert duplicate["dedupe"] and duplicate["paper"]["id"] == paper["id"]
    base = "/api/v1/papers/" + paper["id"]
    edited = client.patch(
        base,
        json={
            "title": "SLAM Study",
            "tags": ["Robotics", "robotics"],
            "collections": ["Planning"],
            "read_status": "finished",
            "year": 2025,
        },
    )
    assert edited.status_code == 200
    assert len(edited.json()["tags"]) == 1
    assert client.get("/api/v1/papers?q=robotics").json()["total"] == 1
    assert client.get("/api/v1/papers?status=unread").json()["total"] == 0
    assert (
        client.put(base + "/reading-position?mode=pdf", json={"pdf_page": 6, "pdf_scale": 1.25}).status_code
        == 200
    )
    assert client.get(base).json()["read_status"] == "finished"
    # Independent engine over same persisted DB (no lifespan; don't start competing worker).
    second = create_app(config)
    restarted = TestClient(second, base_url="http://127.0.0.1:8000")
    assert restarted.get(base).json()["title"] == "SLAM Study"
    assert restarted.get(base + "/reading-position?mode=pdf").json()["pdf_page"] == 6
    response = client.get(base + "/pdf", headers={"Range": "bytes=0-9"})
    assert response.status_code == 206 and response.content.startswith(b"%PDF-")
    assert client.delete(base).status_code == 409
    assert client.delete(base + "?confirm=true").status_code == 200
    assert client.get(base).status_code == 404


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1706.03762", ("1706.03762", 0)),
        ("https://arxiv.org/pdf/1706.03762v2.pdf", ("1706.03762", 2)),
        ("https://arxiv.org/html/2402.08954v1", ("2402.08954", 1)),
        ("hep-th/9901001", ("hep-th/9901001", 0)),
    ],
)
def test_arxiv_parser(value, expected):
    assert arxiv.parse(value) == expected


def test_arxiv_import_offline_and_duplicates(client, monkeypatch):
    def offline(*args, **kwargs):
        raise ValueError("offline")

    monkeypatch.setattr(arxiv, "request", offline)
    first = client.post("/api/v1/papers/arxiv", json={"input": "1706.03762"}).json()
    second = client.post("/api/v1/papers/arxiv", json={"input": "https://arxiv.org/abs/1706.03762"}).json()
    assert second["dedupe"] and second["paper"]["id"] == first["paper"]["id"]
    assert first["paper"]["official_html_url"] is None
    assert client.get("/api/v1/papers").json()["total"] == 1


def test_taxonomy_and_settings(client):
    row = client.post("/api/v1/collections", json={"name": "SLAM"}).json()
    assert (
        client.patch("/api/v1/collections/" + row["id"], json={"name": "Motion"}).json()["name"] == "motion"
    )
    assert client.delete("/api/v1/collections/" + row["id"]).status_code == 200
    assert (
        client.patch("/api/v1/settings", json={"theme": "dark", "marker_mode": "fast"}).json()["theme"]
        == "dark"
    )
    assert client.patch("/api/v1/settings", json={"reader_width": 9000}).status_code == 422


def test_pending_metadata_is_recoverable_after_restart(config):
    from app.db import Paper, uid

    app = create_app(config)
    with app.state.sessions() as session:
        paper = Paper(id=uid(), title="Draft", arxiv_id="2402.08954", metadata_status="pending")
        session.add(paper)
        session.commit()
        paper_id = paper.id
    with TestClient(app, base_url="http://127.0.0.1:8000") as restarted:
        result = restarted.get("/api/v1/papers/" + paper_id).json()
        assert result["metadata_status"] == "failed"
        assert result["title"] == "Draft"
