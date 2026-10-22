"""Offline script contract tests; only the separate manual script run is live evidence."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from app import arxiv


@pytest.fixture
def validator():
    path = Path(__file__).resolve().parents[1] / "scripts" / "validate_discovery.py"
    spec = importlib.util.spec_from_file_location("validate_discovery", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidates():
    return [
        {
            "arxiv_id": identifier,
            "arxiv_version": 1,
            "doi": None,
            "title": "Isolated upstream fixture " + identifier,
            "abstract": "Offline script contract fixture.",
            "authors": ["Generated fixture"],
            "categories": ["cs.RO"],
            "published_at": "2026-10-19T00:00:00+00:00",
            "updated_at": "2026-10-19T00:00:00+00:00",
            "source_url": "https://arxiv.org/abs/" + identifier + "v1",
            "venue": None,
            "content_hash": hashlib.sha256(identifier.encode()).hexdigest(),
        }
        for identifier in ("2610.12345", "2610.12346")
    ]


def fake_upstream(validator, monkeypatch, basis="partial_text"):
    def fetch(**kwargs):
        assert kwargs == {"categories": ["cs.RO"], "max_results": 2, "page_size": 2}
        return {"candidates": candidates(), "complete": False, "next_start": 2}

    text = "This fixture body must never appear in the script report. " * 100

    def body(paper, **kwargs):
        assert paper["arxiv_id"] == "2406.11944" and paper["arxiv_version"] == 1
        assert kwargs["try_full_text"] is True
        return {
            "text": text,
            "basis": basis,
            "source_url": "https://arxiv.org/html/2406.11944v1",
            "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        }

    monkeypatch.setattr(validator.discovery_feed, "fetch_candidates", fetch)
    monkeypatch.setattr(validator.discovery_ai, "fetch_content", body)
    return text


def test_script_exercises_real_storage_and_api_with_only_upstream_fixtures(
    validator, monkeypatch
):
    text = fake_upstream(validator, monkeypatch)
    data_directories = []
    original_config = validator.Config

    def config(**kwargs):
        assert kwargs["_env_file"] is None
        assert not kwargs["metadata_online"] and not kwargs["discovery_online"]
        assert kwargs["deepseek_api_key"] == ""
        data_directories.append(kwargs["data_dir"])
        return original_config(**kwargs)

    def no_paid_call(*args, **kwargs):
        pytest.fail("The validation script attempted an AI call")

    def no_extra_network(*args, **kwargs):
        pytest.fail("A production API route attempted extra network traffic")

    monkeypatch.setattr(validator, "Config", config)
    monkeypatch.setattr(validator.discovery_ai, "analyze", no_paid_call)
    monkeypatch.setattr(arxiv, "request", no_extra_network)
    report = validator.validate()
    assert report["status"] == "PASS"
    assert report["discovery"]["count"] == 2
    assert report["body_sample"]["basis"] == "partial_text"
    assert report["body_sample"]["separate_from_discovery_batch"]
    assert report["ai_analysis"] == "NOT RUN" and report["ai_tokens"] == 0
    assert all(value == "PASS" for value in report["checks"].values())
    assert text not in json.dumps(report)
    assert data_directories and all(
        not directory.exists() for directory in data_directories
    )


def test_script_does_not_claim_body_success_after_abstract_fallback(
    validator, monkeypatch
):
    fake_upstream(validator, monkeypatch, basis="abstract")
    with pytest.raises(
        validator.ValidationFailure, match="official_html_body_available"
    ):
        validator.validate()


def test_failure_report_does_not_print_secret_or_remote_response(
    validator, monkeypatch, capsys
):
    def fail():
        raise RuntimeError("sk-private-secret and untrusted remote response")

    monkeypatch.setattr(validator, "validate", fail)
    assert validator.main() == 1
    captured = capsys.readouterr().out
    assert json.loads(captured) == {
        "status": "FAIL",
        "error_type": "RuntimeError",
        "ai_analysis": "NOT RUN",
    }
    assert "sk-private" not in captured and "remote response" not in captured
