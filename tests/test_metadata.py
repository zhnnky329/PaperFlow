import io
import threading
import time

import httpx
import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from sqlalchemy import create_engine, text

from app import arxiv, metadata
from app.config import ROOT
from app.db import Paper, uid
from app.main import create_app
from test_library import upload


RECORD = {
    "DOI": "10.1234/test.1",
    "title": ["A Reliable Robotics Study"],
    "type": "proceedings-article",
    "container-title": ["Conference Proceedings"],
    "event": {"name": "International Robotics Conference"},
    "published": {"date-parts": [[2025, 5]]},
    "author": [{"given": "Ada", "family": "Scientist", "affiliation": [{"name": "Test University"}]}],
}


def text_pdf(lines):
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        ("BT /F1 12 Tf 60 750 Td " + " ".join(f"({line}) Tj 0 -18 Td" for line in lines) + " ET").encode()
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata({"/Title": "A Reliable Robotics Study", "/Author": "Ada Scientist"})
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def settled(client, paper_id):
    for _ in range(250):
        paper = client.get("/api/v1/papers/" + paper_id).json()
        if paper["metadata_status"] != "pending":
            return paper
        time.sleep(0.03)
    pytest.fail("Metadata task did not finish")


def test_pdf_identifier_enrichment_cache_manual_protection_and_restart(client, config, monkeypatch):
    calls = []

    def crossref(path, params=None):
        calls.append(path)
        return RECORD

    monkeypatch.setattr(metadata, "request_crossref", crossref)
    paper = upload(
        client,
        text_pdf(
            [
                "A Reliable Robotics Study",
                "Ada Scientist",
                "Test University",
                "doi: 10.1234/test.1",
                "Abstract",
                "Content",
            ]
        ),
    )
    paper = settled(client, paper["id"])
    assert paper["metadata_status"] == "ready"
    assert paper["venue"] == "International Robotics Conference" and paper["venue_kind"] == "conference"
    assert paper["affiliations"] == [{"name": "Test University", "authors": ["Ada Scientist"]}]
    endpoint = "/api/v1/papers/" + paper["id"]
    assert (
        client.patch(
            endpoint, json={"venue": "My Correction", "affiliations": [], "title": "My Title"}
        ).status_code
        == 200
    )
    assert client.post(endpoint + "/fetch-metadata").status_code == 202
    updated = settled(client, paper["id"])
    assert updated["venue"] == "My Correction" and updated["title"] == "My Title"
    assert updated["affiliations"] == [] and updated["metadata_sources"]["venue"] == "manual"
    assert calls == ["/10.1234%2Ftest.1"]  # cache is durable
    assert client.get("/api/v1/papers?q=My%20Correction").json()["total"] == 1
    restarted = TestClient(create_app(config), base_url="http://127.0.0.1:8000")
    assert restarted.get(endpoint).json()["venue"] == "My Correction"


def test_title_match_requires_choice_and_rejects_arbitrary_doi(client, pdf_bytes, monkeypatch):
    paper = upload(client, pdf_bytes)
    settled(client, paper["id"])
    endpoint = "/api/v1/papers/" + paper["id"]
    candidate = dict(RECORD, title=["Test Research"])
    monkeypatch.setattr(
        metadata,
        "request_crossref",
        lambda *args: {
            "items": [candidate, dict(RECORD, DOI="10.1234/other", title=["Unrelated Astronomy"])]
        },
    )
    client.post(endpoint + "/fetch-metadata")
    found = settled(client, paper["id"])
    assert found["metadata_status"] == "needs_review" and found["doi"] is None
    assert len(found["metadata_candidates"]) == 1
    assert client.post(endpoint + "/metadata-choice", json={"doi": "10.1234/evil"}).status_code == 409
    chosen = client.post(endpoint + "/metadata-choice", json={"doi": "10.1234/test.1"}).json()
    assert chosen["doi"] == "10.1234/test.1" and chosen["metadata_candidates"] == []
    assert chosen["metadata_sources"]["venue"] == "crossref-confirmed"


def test_local_affiliation_and_offline_retry_keep_pdf(client, monkeypatch):
    def offline(*args):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(metadata, "request_crossref", offline)
    paper = upload(client, text_pdf(["Ada Scientist", "Test University", "doi: 10.1234/test.1", "Abstract"]))
    result = settled(client, paper["id"])
    assert result["metadata_status"] == "failed"
    assert result["doi"] == "10.1234/test.1" and result["affiliations"][0]["name"] == "Test University"
    assert client.get("/api/v1/papers/" + paper["id"] + "/pdf").status_code == 200
    monkeypatch.setattr(metadata, "request_crossref", lambda *args: RECORD)
    client.post("/api/v1/papers/" + paper["id"] + "/fetch-metadata")
    assert settled(client, paper["id"])["metadata_status"] == "ready"


def test_arxiv_reads_optional_fields_and_author_associations(app, monkeypatch):
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom" xmlns:a="http://arxiv.org/schemas/atom"><entry><title>Research</title><published>2025-01-01</published><author><name>Ada</name><a:affiliation>Test University</a:affiliation></author><a:doi>10.1234/test.1</a:doi><a:journal_ref>Journal of Testing 10 (2025)</a:journal_ref></entry></feed>"""
    monkeypatch.setattr(
        arxiv,
        "request",
        lambda url, *args, **kwargs: (
            atom if "api/query" in url else b"<html>Article</html>",
            "application/atom+xml" if "api/query" in url else "text/html",
            url,
        ),
    )
    result = arxiv.lookup("2501.00001")
    assert result["doi"] == "10.1234/test.1"
    assert result["venue"] == "Journal of Testing 10 (2025)"
    assert result["affiliations"] == [{"name": "Test University", "authors": ["Ada"]}]


def test_concurrent_manual_edit_wins(client, pdf_bytes, monkeypatch):
    paper = upload(client, pdf_bytes)
    settled(client, paper["id"])
    endpoint = "/api/v1/papers/" + paper["id"]
    client.patch(endpoint, json={"doi": "10.1234/test.1"})
    started, release = threading.Event(), threading.Event()

    def blocked(*args):
        started.set()
        assert release.wait(5)
        return RECORD

    monkeypatch.setattr(metadata, "request_crossref", blocked)
    client.post(endpoint + "/fetch-metadata")
    assert started.wait(5)
    try:
        client.patch(endpoint, json={"venue": "Edited While Fetching", "title": "Keep This"})
    finally:
        release.set()
    result = settled(client, paper["id"])
    assert result["venue"] == "Edited While Fetching" and result["title"] == "Keep This"


def test_migration_preserves_existing_library_and_positions(config):
    config.data_dir.mkdir()
    engine = create_engine("sqlite:///" + str(config.data_dir / "paperflow.sqlite3"))
    alembic = AlembicConfig(str(ROOT / "backend/alembic.ini"))
    alembic.set_main_option("script_location", str(ROOT / "backend/alembic"))
    paper_id = uid()
    with engine.begin() as connection:
        alembic.attributes["connection"] = connection
        command.upgrade(alembic, "0001")
        connection.execute(
            text(
                "INSERT INTO papers (id,title,authors,abstract,arxiv_version,read_status,metadata_status,created_at,updated_at) VALUES (:id,'Personal Title','[\"Ada\"]','',0,'reading','local','2025','2025')"
            ),
            {"id": paper_id},
        )
        connection.execute(
            text(
                "INSERT INTO reading_positions (paper_id,mode,pdf_page,updated_at) VALUES (:id,'pdf',8,'2025')"
            ),
            {"id": paper_id},
        )
    app = create_app(config)
    with app.state.sessions() as session:
        paper = session.get(Paper, paper_id)
        metadata.apply_values(paper, {"title": "Overwrite", "venue": "New Journal"}, "crossref")
        session.commit()
        assert paper.title == "Personal Title" and paper.venue == "New Journal"
        assert session.execute(text("SELECT pdf_page FROM reading_positions")).scalar() == 8
        assert paper.affiliations == []
    engine.dispose()


def test_extractor_ignores_reference_doi_and_search_unrelated(tmp_path):
    path = tmp_path / "sample.pdf"
    path.write_bytes(
        text_pdf(["Ada", "Test University", "Abstract", "References", "doi: 10.1234/not-this-paper"])
    )
    values = metadata.extract_pdf(path)
    assert "doi" not in values and values["affiliations"][0]["name"] == "Test University"
    assert metadata.match_records([metadata.crossref_record(RECORD)], "Unrelated Astronomy", []) == []
    path.write_bytes(
        text_pdf(
            [
                "Abstract",
                "Body",
                "1All authors are with Department of Engineering, Univer-",
                "sity of Hong Kong.",
                "References",
            ]
        )
    )
    assert metadata.extract_pdf(path)["affiliations"] == [
        {"name": "Department of Engineering, University of Hong Kong", "authors": [], "all_authors": True}
    ]


def test_crossref_bounds_and_redirect_rejection(monkeypatch):
    original = httpx.Client
    monkeypatch.setattr(metadata, "_last_request", -100)
    monkeypatch.setattr(
        metadata.httpx,
        "Client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
            )
        ),
    )
    with pytest.raises(ValueError, match="redirect"):
        metadata.request_crossref("/10.1234%2Ftest")
    monkeypatch.setattr(metadata, "_last_request", -100)
    monkeypatch.setattr(
        metadata.httpx,
        "Client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 1_000_001))
        ),
    )
    with pytest.raises(ValueError, match="large"):
        metadata.request_crossref("/10.1234%2Ftest")


def test_doi_from_citation_is_a_candidate_not_accepted(client, monkeypatch):
    unrelated = dict(RECORD, title=["A Completely Different Paper"])
    monkeypatch.setattr(metadata, "request_crossref", lambda *args: unrelated)
    paper = upload(
        client, text_pdf(["A Reliable Robotics Study", "Abstract", "Related study doi: 10.1234/test.1"])
    )
    result = settled(client, paper["id"])
    assert result["metadata_status"] == "needs_review"
    assert result["doi"] is None and result["venue"] is None
    assert result["metadata_candidates"][0]["title"] == "A Completely Different Paper"


def test_offline_setting_never_calls_external_services(config, monkeypatch):
    config.metadata_online = False

    def unexpected(*args, **kwargs):
        pytest.fail("Offline configuration made an external request")

    monkeypatch.setattr(metadata, "request_crossref", unexpected)
    monkeypatch.setattr(arxiv, "request", unexpected)
    with TestClient(
        create_app(config),
        base_url="http://127.0.0.1:8000",
        headers={"Origin": "http://127.0.0.1:8000", "X-PaperFlow": "1"},
    ) as client:
        paper = upload(client, text_pdf(["Test University", "doi: 10.1234/test.1", "Abstract"]))
        result = settled(client, paper["id"])
        assert result["doi"] == "10.1234/test.1" and result["affiliations"]
        assert client.post("/api/v1/papers/" + paper["id"] + "/fetch-metadata").status_code == 409


def test_metadata_validation_and_clearing_are_persistent(client, pdf_bytes):
    paper = upload(client, pdf_bytes)
    settled(client, paper["id"])
    endpoint = "/api/v1/papers/" + paper["id"]
    assert client.patch(endpoint, json={"doi": "http://127.0.0.1/private"}).status_code == 422
    assert client.patch(endpoint, json={"venue_kind": "invented"}).status_code == 422
    assert client.patch(endpoint, json={"affiliations": [{"name": ""}]}).status_code == 422
    result = client.patch(endpoint, json={"doi": "https://doi.org/10.1234/TEST.1", "venue": "Journal"}).json()
    assert result["doi"] == "10.1234/test.1"
    result = client.patch(endpoint, json={"doi": None, "venue": None}).json()
    assert result["doi"] is None and result["venue"] is None
    assert result["metadata_sources"]["doi"] == "manual"


def test_saving_unfilled_fields_does_not_lock_out_future_enrichment(client, pdf_bytes):
    paper = upload(client, pdf_bytes)
    settled(client, paper["id"])
    response = client.patch(
        "/api/v1/papers/" + paper["id"],
        json={"title": "Corrected Title", "doi": None, "venue": None, "venue_kind": None, "affiliations": []},
    )
    sources = response.json()["metadata_sources"]
    assert sources["title"] == "manual"
    assert all(field not in sources for field in ("doi", "venue", "venue_kind", "affiliations"))
