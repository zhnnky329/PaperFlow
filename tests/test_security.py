import pytest
from app import arxiv
from fastapi import HTTPException
from test_library import upload


@pytest.mark.parametrize(
    "value",
    [
        "http://arxiv.org/abs/1706.03762",
        "https://evil.test/abs/1706.03762",
        "https://arxiv.org@127.0.0.1/abs/1706.03762",
        "file:///etc/passwd",
        "https://arxiv.org:444/abs/1706.03762",
        "../../etc/passwd",
    ],
)
def test_ssrf_inputs_rejected(value):
    with pytest.raises(HTTPException):
        arxiv.parse(value)


def test_pdf_validation_and_boundaries(client, pdf_bytes, config):
    for body in (b"<script>alert(1)</script>", b"%PDF-broken", b"x" * 2_000_000):
        assert client.post("/api/v1/papers/upload", files={"file": ("fake.pdf", body)}).status_code in (
            422,
            413,
        )
    assert client.get("/api/v1/papers").json()["total"] == 0
    assert (
        client.post(
            "/api/v1/collections", json={"name": "evil"}, headers={"Origin": "https://evil.test"}
        ).status_code
        == 403
    )
    assert client.get("/api/v1/health", headers={"Host": "evil.test:8000"}).status_code == 403
    assert client.get("/api/v1/papers/../../etc/passwd/pdf").status_code == 404
    paper = upload(client, pdf_bytes)
    outside = config.data_dir.parent / "outside.pdf"
    outside.write_bytes(pdf_bytes)
    path = config.path(f"papers/{paper['id']}/original.pdf")
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError):
        config.path(f"papers/{paper['id']}/original.pdf")


def test_chunked_request_is_bounded(client):
    response = client.post(
        "/api/v1/papers/arxiv",
        content=iter([b"x" * 1_000_000] * 4),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_html_asset_symlink_and_key_fields_blocked(client, pdf_bytes, config):
    paper = upload(client, pdf_bytes)
    assert client.patch("/api/v1/settings", json={"api_key": "FAKE_SECRET_ONLY_FOR_TEST"}).status_code == 422
    assert "FAKE_SECRET_ONLY_FOR_TEST" not in client.get("/api/v1/settings").text
    assert client.get("/paper-assets/" + paper["id"] + "/../../etc/passwd").status_code in (404, 422)
    original = config.path(f"papers/{paper['id']}/original.pdf")
    outside = config.data_dir.parent / "outside.pdf"
    outside.write_bytes(pdf_bytes)
    original.unlink()
    original.symlink_to(outside)
    assert client.get("/api/v1/papers/" + paper["id"] + "/pdf").status_code == 403
