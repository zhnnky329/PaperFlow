"""Isolated protocol fixtures verify persistence; no fixture is a live AI result."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError

from app.config import ROOT
from app.db import DiscoveryRun, Paper, uid
from app import discovery_ai, discovery_feed
from app.main import create_app

BASE = "/api/v1/discovery"
HEADERS = {"Origin": "http://127.0.0.1:8000", "X-PaperFlow": "1"}


@pytest.fixture
def discovery_client(app):
    # No lifespan: control this queue synchronously and never access the network.
    app.state.config.discovery_online = True
    client = TestClient(app, base_url="http://127.0.0.1:8000", headers=HEADERS)
    yield client
    client.close()
    app.state.sessions.kw["bind"].dispose()


def candidate(identifier="2610.00001", version=1, doi=None):
    return {
        "arxiv_id": identifier,
        "arxiv_version": version,
        "doi": doi,
        "title": "Active visual perception for UAV tracking",
        "authors": ["Research Author"],
        "abstract": "A method for identity-aware tracking in dynamic scenes.",
        "categories": ["cs.RO"],
        "published_at": "2026-10-19T10:00:00+00:00",
        "updated_at": "2026-10-19T10:00:00+00:00",
        "source_url": f"https://arxiv.org/abs/{identifier}v{version}",
        "venue": None,
        "content_hash": hashlib.sha256(
            (identifier + str(version) + str(doi)).encode()
        ).hexdigest(),
    }


def feed_stub(monkeypatch, *rows):
    calls = []

    def fetch(**kwargs):
        calls.append(kwargs)
        return {"candidates": list(rows), "complete": True, "next_start": None}

    monkeypatch.setattr(discovery_feed, "fetch_candidates", fetch)
    return calls


def execute(client):
    response = client.post(BASE + "/check")
    assert response.status_code == 202, response.text
    run = response.json()["run"]
    client.app.state.discovery.execute(run["id"])
    return next(
        item for item in client.get(BASE + "/runs").json() if item["id"] == run["id"]
    )


def ai_stub(client, monkeypatch, result=None):
    calls = []
    assert (
        client.post(BASE + "/api-key", json={"api_key": "test-only-secret"}).status_code
        == 200
    )
    assert (
        client.patch(BASE + "/settings", json={"ai_enabled": True}).status_code == 200
    )
    monkeypatch.setattr(
        discovery_ai,
        "fetch_content",
        lambda *args, **kwargs: {
            "text": "Article abstract",
            "basis": "abstract",
            "source_url": "https://arxiv.org/abs/2610.00001",
        },
    )
    monkeypatch.setattr(discovery_ai, "estimate_tokens", lambda *args, **kwargs: 1000)

    def analyze(*args, **kwargs):
        calls.append(args[0]["arxiv_id"])
        if isinstance(result, Exception):
            raise result
        return result or {
            "decision": "recommend",
            "score": 88,
            "matched_directions": ["uav"],
            "summary": "协议测试用中文总结，不是真实AI推荐。",
            "reason": "符合跟踪兴趣",
            "basis": "abstract",
            "source_url": args[0]["source_url"],
            "tokens_used": 200,
        }

    monkeypatch.setattr(discovery_ai, "analyze", analyze)
    return calls


def test_default_settings_validation_secret_and_backup_exclusion(
    discovery_client, config, tmp_path
):
    client = discovery_client
    initial = client.get(BASE + "/settings").json()
    assert (
        initial["interval_hours"] == 48
        and initial["auto_update"]
        and not initial["ai_enabled"]
    )
    assert len(initial["interests"]) == 3
    for patch in (
        {"interval_hours": 0},
        {"min_score": 101},
        {"token_budget": 10},
        {"api_key": "oops"},
        {"interests": [initial["interests"][0]] * 2},
    ):
        assert client.patch(BASE + "/settings", json=patch).status_code == 422
    response = client.post(BASE + "/api-key", json={"api_key": "test-only-secret"})
    assert response.status_code == 200
    assert (
        response.json()["api_key_source"] == "local"
        and "test-only-secret" not in response.text
    )
    assert config.path("discovery-api-key").stat().st_mode & 0o777 == 0o600
    assert "test-only-secret" not in client.get("/api/v1/settings").text
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from backup import backup
    import zipfile

    output = backup(config.data_dir, tmp_path / "backup.zip")
    with zipfile.ZipFile(output) as archive:
        assert "discovery-api-key" not in archive.namelist()
    assert client.post(BASE + "/api-key", json={"api_key": ""}).status_code == 200
    assert not config.path("discovery-api-key").exists()


def test_environment_key_never_returned_and_local_clear_preserves_environment(
    discovery_client,
):
    from pydantic import SecretStr

    client = discovery_client
    client.app.state.config.deepseek_api_key = SecretStr("environment-test-secret")
    response = client.post(BASE + "/api-key", json={"api_key": ""})
    assert response.json()["api_key_source"] == "environment"
    assert "environment-test-secret" not in response.text


def test_discovery_is_separate_and_dedupes_unchanged_candidates(
    discovery_client, monkeypatch
):
    client = discovery_client
    calls = feed_stub(monkeypatch, candidate())
    first = execute(client)
    second = execute(client)
    assert first["new_count"] == 1 and second["new_count"] == 0
    assert client.get("/api/v1/papers").json()["total"] == 0
    assert client.get(BASE + "/papers").json()["items"] == []
    history = client.get(BASE + "/papers?view=history").json()
    assert history["total"] == 1 and history["items"][0]["analysis_status"] == "pending"
    assert client.get(BASE + "/status").json()["pending_count"] == 1
    assert len(calls) == 2 and calls[1]["start"] == 0
    assert not list(client.app.state.config.data_dir.rglob("*.pdf"))


def test_window_continuation_persisted_and_budget_shared(discovery_client, monkeypatch):
    client = discovery_client
    starts = []

    def feed(**kwargs):
        starts.append(kwargs)
        complete = kwargs["start"] != 0
        return {
            "candidates": [candidate("2610.00002" if complete else "2610.00001")],
            "complete": complete,
            "next_start": None if complete else 100,
        }

    monkeypatch.setattr(discovery_feed, "fetch_candidates", feed)
    run = execute(client)
    assert [item["start"] for item in starts] == [0, 100]
    assert (
        starts[0]["since"] == starts[1]["since"]
        and starts[0]["until"] == starts[1]["until"]
    )
    assert run["fetched_count"] == 2 and run["status"] == "succeeded"
    assert client.get(BASE + "/status").json()["last_checked_at"] == starts[0]["until"]


def test_interrupted_paging_does_not_advance_watermark_and_retry_resumes(
    discovery_client, monkeypatch
):
    client = discovery_client
    starts = []

    def feed(**kwargs):
        starts.append(kwargs["start"])
        if kwargs["start"]:
            raise ValueError("network secret that must not be exposed")
        return {"candidates": [candidate()], "complete": False, "next_start": 100}

    monkeypatch.setattr(discovery_feed, "fetch_candidates", feed)
    run = execute(client)
    assert run["status"] == "failed" and "secret" not in str(run)
    assert client.get(BASE + "/status").json()["last_checked_at"] is None
    calls = feed_stub(monkeypatch)
    retry = client.post(BASE + "/runs/" + run["id"] + "/retry").json()
    client.app.state.discovery.execute(retry["run"]["id"])
    assert calls[0]["start"] == 100
    assert client.get(BASE + "/papers?view=history").json()["total"] == 1


def test_single_active_run_for_concurrent_manual_and_scheduler(discovery_client):
    worker = discovery_client.app.state.discovery
    with ThreadPoolExecutor(max_workers=8) as pool:
        queued = list(pool.map(lambda _: worker.enqueue(), range(8)))
    worker.schedule_due()
    assert len({result[0]["id"] for result in queued}) == 1
    assert sum(not result[1] for result in queued) == 1
    with worker.sessions() as session:
        assert len(list(session.scalars(select(DiscoveryRun)))) == 1
        session.add(DiscoveryRun(trigger="other"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_automatic_due_and_restart_orphan_recovery(config):
    config.discovery_online = False
    app = create_app(config)
    with app.state.sessions() as session:
        run = DiscoveryRun(
            id=uid(), trigger="manual", status="running", tokens_reserved=1200
        )
        session.add(run)
        session.commit()
        run_id = run.id
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        status = client.get(BASE + "/status").json()
        assert status["last_run"]["id"] == run_id
        assert status["last_run"]["error_code"] == "INTERRUPTED"
        assert status["usage"]["tokens_reserved"] == 1200
    second = create_app(config)
    second.state.config.discovery_online = True
    with second.state.sessions() as session:
        row = session.get(DiscoveryRun, run_id)
        row.created_at = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
        session.commit()
    second.state.discovery.schedule_due()
    with second.state.sessions() as session:
        assert (
            session.scalar(
                select(DiscoveryRun).where(DiscoveryRun.status == "queued")
            ).trigger
            == "scheduled"
        )
    second.state.sessions.kw["bind"].dispose()


def test_ai_cache_content_change_and_explicit_reanalysis(discovery_client, monkeypatch):
    client = discovery_client
    feed_stub(monkeypatch, candidate())
    calls = ai_stub(client, monkeypatch)
    first = execute(client)
    assert first["tokens_used"] == 200 and first["tokens_reserved"] == 0
    row = client.get(BASE + "/papers").json()["items"][0]
    assert row["analysis"]["basis"] == "abstract" and row["is_new"]
    assert client.get(BASE + "/papers?interest_id=uav").json()["total"] == 1
    assert client.get(BASE + "/papers?interest_id=navigation").json()["total"] == 0
    assert client.get(BASE + "/papers?min_score=90").json()["total"] == 0
    assert client.get(BASE + "/papers?view=latest").json()["total"] == 1
    execute(client)
    assert len(calls) == 1
    reanalysis = client.post(BASE + "/papers/" + row["id"] + "/reanalyze")
    assert reanalysis.status_code == 202, reanalysis.text
    client.app.state.discovery.execute(reanalysis.json()["run"]["id"])
    assert len(calls) == 2
    feed_stub(monkeypatch, candidate(version=2))
    execute(client)
    assert len(calls) == 3
    client.post(BASE + "/seen")
    assert client.get(BASE + "/status").json()["new_count"] == 0


def test_ai_budget_reservation_precedes_call_and_unknown_failure_persists(
    discovery_client, monkeypatch
):
    client = discovery_client
    feed_stub(monkeypatch, candidate(), candidate("2610.00002"))
    ai_stub(client, monkeypatch)

    def fail(*args, **kwargs):
        with client.app.state.sessions() as session:
            run = session.scalar(
                select(DiscoveryRun).where(DiscoveryRun.status == "queued")
            )
            assert run.tokens_reserved == 1000
        raise discovery_ai.AIError("timeout", "固定脱敏错误", True)

    monkeypatch.setattr(discovery_ai, "analyze", fail)
    run = execute(client)
    assert run["status"] == "failed" and run["tokens_reserved"] == 1000
    assert run["tokens_used"] == 0
    assert client.get(BASE + "/papers?view=history").json()["total"] == 2


def test_budget_blocks_calls_and_max_analyses_limits_batch(
    discovery_client, monkeypatch
):
    client = discovery_client
    feed_stub(monkeypatch, candidate(), candidate("2610.00002"))
    calls = ai_stub(client, monkeypatch)
    client.patch(BASE + "/settings", json={"max_analyses": 1})
    assert execute(client)["analyzed_count"] == 1
    assert len(calls) == 1
    monkeypatch.setattr(
        discovery_ai, "estimate_tokens", lambda *args, **kwargs: 9999999
    )
    run = execute(client)
    assert run["error_code"] == "BUDGET_LIMIT" and run["tokens_reserved"] == 0
    assert len(calls) == 1


def test_feedback_survives_restart_and_only_explicit_import_adds_library(
    discovery_client, monkeypatch, config
):
    client = discovery_client
    config.metadata_online = False
    feed_stub(monkeypatch, candidate(doi="10.1234/example"))
    ai_stub(client, monkeypatch)
    execute(client)
    row = client.get(BASE + "/papers").json()["items"][0]
    endpoint = BASE + "/papers/" + row["id"]
    assert (
        client.post(endpoint + "/feedback", json={"feedback": "dismissed"}).status_code
        == 200
    )
    assert client.get(BASE + "/papers").json()["total"] == 0
    assert client.get(BASE + "/papers?view=dismissed").json()["total"] == 1
    second = create_app(config)
    restarted = TestClient(second, base_url="http://127.0.0.1:8000", headers=HEADERS)
    assert (
        restarted.get(BASE + "/papers?view=dismissed").json()["items"][0]["feedback"]
        == "dismissed"
    )
    client.post(endpoint + "/feedback", json={"feedback": "later"})
    assert client.get(BASE + "/papers?view=interested").json()["total"] == 1
    imported = client.post(endpoint + "/import").json()
    duplicate = client.post(endpoint + "/import").json()
    assert duplicate["dedupe"] and imported["paper"]["id"] == duplicate["paper"]["id"]
    assert client.get("/api/v1/papers").json()["total"] == 1
    assert client.get(BASE + "/papers").json()["total"] == 0
    assert not imported["paper"]["has_pdf"]
    assert imported["paper"]["title"] == candidate()["title"]
    restarted.close()
    second.state.sessions.kw["bind"].dispose()


def test_dedupes_existing_library_by_any_version_doi_and_alias(
    discovery_client, monkeypatch
):
    client = discovery_client
    with client.app.state.sessions() as session:
        paper = Paper(
            id=uid(),
            title="Library",
            arxiv_id="2610.00001",
            arxiv_version=2,
            doi="10.1234/EXAMPLE",
        )
        session.add(paper)
        session.commit()
    feed_stub(monkeypatch, candidate(), candidate("2610.00002", doi="10.1234/example"))
    calls = ai_stub(client, monkeypatch)
    execute(client)
    assert not calls and client.get(BASE + "/papers").json()["total"] == 0
    history = client.get(BASE + "/papers?view=history").json()["items"]
    assert all(item["paper_id"] == paper.id for item in history)
    response = client.post(BASE + "/papers/" + history[0]["id"] + "/import").json()
    assert response["dedupe"] and response["paper"]["id"] == paper.id


def test_doi_later_merge_preserves_canonical_fields_feedback_and_aliases(
    discovery_client, monkeypatch
):
    client = discovery_client
    first, second = candidate(), candidate("2610.00002")
    feed_stub(monkeypatch, first, second)
    execute(client)
    rows = client.get(BASE + "/papers?view=history").json()["items"]
    client.post(
        BASE + "/papers/" + rows[0]["id"] + "/feedback", json={"feedback": "dismissed"}
    )
    first, second = (
        candidate(doi="10.1234/same"),
        candidate("2610.00002", doi="10.1234/same"),
    )
    feed_stub(monkeypatch, first, second)
    execute(client)
    rows = client.get(BASE + "/papers?view=history").json()["items"]
    assert len(rows) == 1 and rows[0]["feedback"] == "dismissed"
    row = rows[0]
    assert row["source_url"] == f"https://arxiv.org/abs/{row['arxiv_id']}v1"
    assert len(row["arxiv_aliases"]) == 1
    execute(client)
    assert client.get(BASE + "/papers?view=history").json()["total"] == 1


def test_exclusions_can_be_reconsidered_without_reanalyzing_successes(
    discovery_client, monkeypatch
):
    client = discovery_client
    feed_stub(monkeypatch, candidate())
    interests = client.get(BASE + "/settings").json()["interests"]
    for item in interests:
        item["exclude_keywords"] = ["UAV"]
    client.patch(BASE + "/settings", json={"interests": interests})
    execute(client)
    assert (
        client.get(BASE + "/papers?view=history").json()["items"][0]["analysis_status"]
        == "filtered"
    )
    for item in interests:
        item["exclude_keywords"] = []
    client.patch(BASE + "/settings", json={"interests": interests})
    calls = ai_stub(client, monkeypatch)
    execute(client)
    assert len(calls) == 1


def test_new_migration_preserves_existing_library_positions_and_links(config):
    config.data_dir.mkdir(parents=True)
    engine = create_engine("sqlite:///" + str(config.data_dir / "paperflow.sqlite3"))
    migration = AlembicConfig(str(ROOT / "backend/alembic.ini"))
    migration.set_main_option("script_location", str(ROOT / "backend/alembic"))
    with engine.begin() as connection:
        migration.attributes["connection"] = connection
        command.upgrade(migration, "0003")
        connection.execute(
            text(
                "INSERT INTO papers (id,title,authors,abstract,arxiv_version,read_status,metadata_status,created_at,updated_at,affiliations,metadata_sources,metadata_candidates) VALUES ('preserved','Research','[]','',0,'reading','ready','a','b','[]','{}','[]')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO reading_positions (paper_id,mode,pdf_page,pdf_scale,html_anchor,scroll_ratio,updated_at) VALUES ('preserved','pdf',7,1.25,'',0.4,'a')"
            )
        )
        command.upgrade(migration, "head")
        assert (
            connection.execute(
                text("SELECT title FROM papers WHERE id='preserved'")
            ).scalar()
            == "Research"
        )
        assert (
            connection.execute(text("SELECT pdf_page FROM reading_positions")).scalar()
            == 7
        )
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            == "0004"
        )
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()


def test_api_security_offline_and_key_path_boundaries(
    discovery_client, config, tmp_path
):
    client = discovery_client
    assert client.post(BASE + "/check", headers={"X-PaperFlow": "0"}).status_code == 403
    assert client.get(BASE + "/papers?min_score=101").status_code == 422
    assert client.get(BASE + "/papers?sort=unknown").status_code == 422
    config.discovery_online = False
    assert client.post(BASE + "/check").status_code == 409
    outside = tmp_path / "private-secret"
    outside.write_text("do-not-touch")
    (config.data_dir / "discovery-api-key").symlink_to(outside)
    response = client.post(BASE + "/api-key", json={"api_key": "replacement-secret"})
    assert response.status_code in (403, 500)
    assert (
        outside.read_text() == "do-not-touch"
        and "replacement-secret" not in response.text
    )


def test_interrupted_migration_rolls_back_new_tables_and_can_retry(config, monkeypatch):
    from alembic.operations import Operations

    config.data_dir.mkdir(parents=True)
    engine = create_engine("sqlite:///" + str(config.data_dir / "paperflow.sqlite3"))
    migration = AlembicConfig(str(ROOT / "backend/alembic.ini"))
    migration.set_main_option("script_location", str(ROOT / "backend/alembic"))
    with engine.begin() as connection:
        migration.attributes["connection"] = connection
        command.upgrade(migration, "0003")
    original = Operations.create_table

    def interrupt(operation, name, *args, **kwargs):
        if name == "discovery_runs":
            raise RuntimeError("Injected interruption")
        return original(operation, name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Operations, "create_table", interrupt)
        with pytest.raises(RuntimeError, match="Injected interruption"):
            create_app(config)
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
            == "0003"
        )
        assert (
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE name LIKE 'discovery_%'")
            ).all()
            == []
        )
    restarted = create_app(config)
    with restarted.state.sessions() as session:
        assert (
            session.execute(text("SELECT version_num FROM alembic_version")).scalar()
            == "0004"
        )
    restarted.state.sessions.kw["bind"].dispose()
    engine.dispose()


def test_metadata_enrichment_keeps_successful_analysis_cache(
    discovery_client, monkeypatch
):
    client = discovery_client
    original = candidate()
    feed_stub(monkeypatch, original)
    calls = ai_stub(client, monkeypatch)
    execute(client)
    enriched = dict(
        original,
        doi="10.1234/new",
        venue="Robotics Journal",
        authors=["Updated Author"],
    )
    feed_stub(monkeypatch, enriched)
    execute(client)
    assert len(calls) == 1
    row = client.get(BASE + "/papers?view=history").json()["items"][0]
    assert row["doi"] == "10.1234/new" and row["venue"] == "Robotics Journal"
    assert (
        row["authors"] == ["Updated Author"] and row["analysis_status"] == "succeeded"
    )
