"""Real public-arXiv discovery/storage/API validation, without any AI call.

Run from the repository root:
    .venv/bin/python scripts/validate_discovery.py

Every run creates and removes its own temporary PaperFlow data directory. The
two discovered metadata records are real; the generated baseline PDF is only a
copyright-free fixture for checking preservation of existing Library state.
API requests use the real FastAPI ASGI app through TestClient, not a browser or
a listening HTTP server. The separate fixed HTML sample proves body retrieval,
not that the two newly discovered papers have readable HTML or AI summaries.
"""

import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time

from fastapi.testclient import TestClient
from pypdf import PdfWriter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import discovery_ai, discovery_feed  # noqa: E402
from app.config import Config  # noqa: E402
from app.db import DiscoveryRun, now, uid  # noqa: E402
from app.main import create_app  # noqa: E402

BODY_SAMPLE_ID = "2406.11944"
BASE_URL = "http://127.0.0.1:8000"
HEADERS = {"Origin": BASE_URL, "X-PaperFlow": "1"}


class ValidationFailure(RuntimeError):
    def __init__(self, check):
        self.check = check
        super().__init__(check)


def require(condition, check):
    if not condition:
        raise ValidationFailure(check)


def api(client, method, path, expected=200, **kwargs):
    response = client.request(method, "/api/v1" + path, **kwargs)
    require(response.status_code == expected, method + " " + path.split("?")[0])
    return response.json()


def baseline_pdf():
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=595, height=842)
    writer.add_metadata(
        {"/Title": "Discovery validation baseline", "/Author": "Generated fixture"}
    )
    target = io.BytesIO()
    writer.write(target)
    return target.getvalue()


def library_snapshot(client, paper_id):
    paper = api(client, "GET", "/papers/" + paper_id)
    document = client.get("/api/v1/papers/" + paper_id + "/pdf")
    require(document.status_code == 200, "baseline_pdf_readable")
    return {
        "title": paper["title"],
        "read_status": paper["read_status"],
        "tags": sorted((row["id"], row["name"]) for row in paper["tags"]),
        "collections": sorted((row["id"], row["name"]) for row in paper["collections"]),
        "position": api(
            client, "GET", "/papers/" + paper_id + "/reading-position?mode=pdf"
        ),
        "pdf_sha256": hashlib.sha256(document.content).hexdigest(),
    }


def validate():
    started = time.monotonic()
    batch = discovery_feed.fetch_candidates(
        categories=["cs.RO"], max_results=2, page_size=2
    )
    candidates = batch["candidates"]
    require(len(candidates) == 2, "two_real_discovery_candidates")
    body = discovery_ai.fetch_content(
        {"arxiv_id": BODY_SAMPLE_ID, "arxiv_version": 1, "abstract": ""},
        try_full_text=True,
        max_chars=24_000,
    )
    require(
        body["basis"] in ("full_text", "partial_text"), "official_html_body_available"
    )
    require(
        body["source_url"] == f"https://arxiv.org/html/{BODY_SAMPLE_ID}v1",
        "official_html_sample_source",
    )
    require(len(body["text"]) >= 500, "official_html_body_nonempty")

    with tempfile.TemporaryDirectory(
        prefix="paperflow-discovery-validation-"
    ) as folder:
        config = Config(
            _env_file=None,
            data_dir=Path(folder) / "data",
            marker_executable="/missing/marker",
            metadata_online=False,
            discovery_online=False,
            deepseek_api_key="",
        )
        app = create_app(config)
        with TestClient(app, base_url=BASE_URL, headers=HEADERS) as client:
            api(
                client,
                "PATCH",
                "/discovery/settings",
                json={"auto_update": False, "ai_enabled": False},
            )
            fixture = baseline_pdf()
            baseline = api(
                client,
                "POST",
                "/papers/upload",
                files={
                    "file": (
                        "discovery-validation-baseline.pdf",
                        fixture,
                        "application/pdf",
                    ),
                },
            )["paper"]
            baseline_id = baseline["id"]
            api(
                client,
                "PATCH",
                "/papers/" + baseline_id,
                json={
                    "title": "Preserve this existing Library record",
                    "read_status": "finished",
                    "tags": ["validation"],
                    "collections": ["Existing papers"],
                },
            )
            api(
                client,
                "PUT",
                "/papers/" + baseline_id + "/reading-position?mode=pdf",
                json={
                    "pdf_page": 2,
                    "pdf_scale": 1.25,
                    "scroll_ratio": 0.4,
                },
            )
            before = library_snapshot(client, baseline_id)
            require(
                before["pdf_sha256"] == hashlib.sha256(fixture).hexdigest(),
                "baseline_pdf_hash",
            )

            # Persist the real upstream batch twice through the production
            # storage service; no recommendation result is manufactured.
            with app.state.sessions() as session:
                run = DiscoveryRun(
                    id=uid(),
                    trigger="validation",
                    status="succeeded",
                    stage="validation",
                    finished_at=now(),
                )
                session.add(run)
                session.flush()
                for _ in range(2):
                    for candidate in candidates:
                        app.state.discovery.store_candidate(session, candidate, run)
                run.fetched_count = len(candidates)
                require(
                    run.new_count == len(candidates), "candidate_storage_deduplication"
                )
                session.commit()

            history = api(client, "GET", "/discovery/papers?view=history")
            require(history["total"] == len(candidates), "discovery_history_count")
            require(
                api(client, "GET", "/papers")["total"] == 1,
                "discovery_library_separation",
            )
            require(
                all(row["analysis"] is None for row in history["items"]),
                "no_fake_ai_results",
            )
            by_arxiv = {row["arxiv_id"]: row for row in history["items"]}
            selected = by_arxiv[candidates[0]["arxiv_id"]]
            ignored = by_arxiv[candidates[1]["arxiv_id"]]
            api(
                client,
                "POST",
                "/discovery/papers/" + selected["id"] + "/feedback",
                json={"feedback": "later"},
            )
            api(
                client,
                "POST",
                "/discovery/papers/" + ignored["id"] + "/feedback",
                json={"feedback": "dismissed"},
            )
            imported = api(
                client,
                "POST",
                "/discovery/papers/" + selected["id"] + "/import",
                expected=202,
            )
            repeated = api(
                client,
                "POST",
                "/discovery/papers/" + selected["id"] + "/import",
                expected=202,
            )
            require(
                not imported["dedupe"] and repeated["dedupe"],
                "library_import_deduplication",
            )
            require(
                imported["paper"]["id"] == repeated["paper"]["id"],
                "library_import_same_id",
            )
            require(not imported["paper"]["has_pdf"], "no_candidate_pdf_download")
            require(api(client, "GET", "/papers")["total"] == 2, "explicit_import_only")
            require(
                library_snapshot(client, baseline_id) == before,
                "existing_library_preserved",
            )

        # Start a new app/engine/lifespan against the same temporary database.
        restarted = create_app(config)
        with TestClient(restarted, base_url=BASE_URL, headers=HEADERS) as client:
            after_history = api(client, "GET", "/discovery/papers?view=history")
            require(
                after_history["total"] == len(candidates), "discovery_restart_count"
            )
            after = {row["arxiv_id"]: row for row in after_history["items"]}
            selected_after, ignored_after = (
                after[selected["arxiv_id"]],
                after[ignored["arxiv_id"]],
            )
            require(
                selected_after["feedback"] == "later"
                and ignored_after["feedback"] == "dismissed",
                "feedback_restart",
            )
            require(
                selected_after["paper_id"] == imported["paper"]["id"],
                "library_link_restart",
            )
            require(
                api(client, "GET", "/papers")["total"] == 2, "library_restart_count"
            )
            require(
                library_snapshot(client, baseline_id) == before,
                "existing_library_restart_preserved",
            )
            status = api(client, "GET", "/discovery/status")
            require(
                status["usage"] == {"tokens_used": 0, "tokens_reserved": 0},
                "zero_ai_tokens",
            )
            require(not status["key_configured"], "no_api_key_loaded")
            require(
                api(client, "GET", "/discovery/papers")["total"] == 0,
                "no_unanalyzed_recommendations",
            )

    return {
        "status": "PASS",
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "api_transport": "FastAPI ASGI TestClient; real routes and SQLite, no API mocks",
        "isolation": {
            "temporary_data": True,
            "metadata_online": False,
            "scheduler_online": False,
        },
        "discovery": {
            "source": "arXiv public API",
            "categories": ["cs.RO"],
            "count": len(candidates),
            "complete": batch["complete"],
            "next_start": batch["next_start"],
            "papers": [
                {
                    key: row[key]
                    for key in (
                        "arxiv_id",
                        "arxiv_version",
                        "title",
                        "categories",
                        "published_at",
                        "updated_at",
                        "source_url",
                    )
                }
                for row in candidates
            ],
        },
        "body_sample": {
            "arxiv_id": BODY_SAMPLE_ID + "v1",
            "separate_from_discovery_batch": True,
            "basis": body["basis"],
            "source_url": body["source_url"],
            "characters": len(body["text"]),
            "content_sha256": body["content_hash"],
        },
        "checks": {
            name: "PASS"
            for name in (
                "discovery_library_separation",
                "candidate_storage_deduplication",
                "history_api",
                "feedback_api",
                "library_import_deduplication",
                "feedback_and_link_after_restart",
                "existing_library_pdf_tags_collections_and_reading_state",
                "no_candidate_pdf_download",
            )
        },
        "ai_analysis": "NOT RUN",
        "ai_tokens": 0,
        "browser_interaction": "NOT RUN",
        "scheduled_network_fetch": "NOT RUN",
    }


def main():
    try:
        report = validate()
    except ValidationFailure as exc:
        print(
            json.dumps(
                {"status": "FAIL", "check": exc.check, "ai_analysis": "NOT RUN"},
                ensure_ascii=False,
            )
        )
        return 1
    except Exception as exc:
        # Do not print exception messages or HTTP response/request bodies.
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_type": type(exc).__name__,
                    "ai_analysis": "NOT RUN",
                }
            )
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
