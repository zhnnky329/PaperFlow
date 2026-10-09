import pytest
import httpx
from app import arxiv
from app.db import Paper, uid

ATOM = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Verified Paper</title><summary>Abstract</summary><published>2024-02-01T00:00:00Z</published><author><name>Ada</name></author></entry></feed>"""


def test_metadata_and_html_checks_are_independent(app, monkeypatch):
    with app.state.sessions() as session:
        paper = Paper(id=uid(), title="Draft", arxiv_id="2402.08954", metadata_status="pending")
        session.add(paper)
        session.commit()
        paper_id = paper.id
    calls = []

    def remote(url, *args, **kwargs):
        calls.append(url)
        if "api/query" in url:
            raise httpx.ConnectError("offline")
        return b"<html><p>Official article</p></html>", "text/html", url

    monkeypatch.setattr(arxiv, "request", remote)
    arxiv.refresh(app.state.sessions, paper_id)
    with app.state.sessions() as session:
        paper = session.get(Paper, paper_id)
        assert paper.metadata_status == "failed"
        assert paper.official_html_url == "https://arxiv.org/html/2402.08954"
    assert len(calls) == 2

    def missing_html(url, *args, **kwargs):
        if "api/query" in url:
            return ATOM, "application/atom+xml", url
        return b"not available", "text/plain", url

    monkeypatch.setattr(arxiv, "request", missing_html)
    arxiv.refresh(app.state.sessions, paper_id)
    with app.state.sessions() as session:
        paper = session.get(Paper, paper_id)
        assert paper.title == "Verified Paper"
        assert paper.authors == ["Ada"] and paper.year == 2024
        assert paper.official_html_url is None


def test_redirect_revalidation_and_stream_limit(monkeypatch):
    monkeypatch.setattr(arxiv, "_last_request", -100)

    def redirect(request):
        return httpx.Response(302, headers={"Location": "http://127.0.0.1:9000/private"})

    original = httpx.Client
    monkeypatch.setattr(
        arxiv.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(redirect))
    )
    with pytest.raises(ValueError, match="Unsafe redirect"):
        arxiv.request("https://arxiv.org/pdf/1706.03762")
    monkeypatch.setattr(arxiv, "_last_request", -100)
    monkeypatch.setattr(
        arxiv.httpx,
        "Client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 100))
        ),
    )
    with pytest.raises(ValueError, match="limit"):
        arxiv.request("https://arxiv.org/pdf/1706.03762", limit=10)


def test_http_429_cooldown(monkeypatch):
    arxiv._cooldown.clear()
    monkeypatch.setattr(arxiv, "_last_request", -100)
    original = httpx.Client
    monkeypatch.setattr(
        arxiv.httpx,
        "Client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda request: httpx.Response(429, headers={"Retry-After": "60"}))
        ),
    )
    with pytest.raises(httpx.HTTPStatusError):
        arxiv.request("https://arxiv.org/html/2402.08954")
    with pytest.raises(ValueError, match="cooldown"):
        arxiv.request("https://arxiv.org/html/2402.08954")
    arxiv._cooldown.clear()
