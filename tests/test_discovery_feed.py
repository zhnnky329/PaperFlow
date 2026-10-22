from datetime import datetime, timezone
from html import escape
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app import arxiv, discovery_feed as feed


def atom(entries, total=None):
    metadata = (
        f"<opensearch:totalResults>{total}</opensearch:totalResults>"
        if total is not None
        else ""
    )
    return (
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:arxiv="http://arxiv.org/schemas/atom" '
        'xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">'
        + metadata
        + "".join(entries)
        + "</feed>"
    ).encode()


def entry(identifier="2402.08954v2", updated="2026-10-19T12:00:00Z", **kwargs):
    values = {
        "title": "Active visual mapping",
        "abstract": "A visual navigation approach.",
        "doi": "https://doi.org/10.1234/MAPPING.1",
        "category": "cs.RO",
        "author": "Ada Scientist",
        "venue": "Robotics Journal 2026",
        **kwargs,
    }
    return (
        f"<entry><id>http://arxiv.org/abs/{escape(identifier)}</id>"
        f"<title>{escape(values['title'])}</title><summary>{escape(values['abstract'])}</summary>"
        "<published>2024-02-01T00:00:00Z</published>"
        f"<updated>{updated}</updated><author><name>{escape(values['author'])}</name></author>"
        f'<category term="{escape(values["category"])}"/>'
        '<arxiv:primary_category term="cs.RO"/>'
        f"<arxiv:doi>{escape(values['doi'])}</arxiv:doi>"
        f"<arxiv:journal_ref>{escape(values['venue'])}</arxiv:journal_ref>"
        '<link href="http://127.0.0.1/private" rel="related"/>'
        "</entry>"
    )


def test_metadata_reuses_identifiers_and_doi_and_ignores_feed_links():
    result = feed.parse_feed(atom([entry()]))
    candidate = result["candidates"][0]
    assert candidate["arxiv_id"] == "2402.08954"
    assert candidate["arxiv_version"] == 2
    assert candidate["doi"] == "10.1234/mapping.1"
    assert candidate["authors"] == ["Ada Scientist"]
    assert candidate["categories"] == ["cs.RO"]
    assert candidate["venue"] == "Robotics Journal 2026"
    assert candidate["source_url"] == "https://arxiv.org/abs/2402.08954v2"
    assert candidate["pdf_url"] == "https://arxiv.org/pdf/2402.08954v2"
    assert candidate["published_at"] == "2024-02-01T00:00:00+00:00"
    assert len(candidate["content_hash"]) == 64


def test_versions_deduplicate_and_invalid_doi_does_not_become_identifier():
    result = feed.parse_feed(
        atom(
            [
                entry("2402.08954v1"),
                entry(),
                entry("cs/0101001v3", doi="not-a-doi"),
            ]
        )
    )
    assert result["entry_count"] == 3
    assert len(result["candidates"]) == 2
    assert result["candidates"][0]["arxiv_version"] == 2
    assert result["candidates"][1]["arxiv_id"] == "cs/0101001"
    assert result["candidates"][1]["doi"] is None


def test_content_fingerprint_tracks_versions_and_substantive_text():
    def fingerprint(**kwargs):
        return feed.parse_feed(atom([entry(**kwargs)]))["candidates"][0]["content_hash"]

    assert fingerprint() == fingerprint(updated="2026-10-20T10:00:00Z")
    assert fingerprint() != fingerprint(identifier="2402.08954v3")
    assert fingerprint() != fingerprint(title="A new visual mapping method")
    assert fingerprint() != fingerprint(
        abstract="An updated method with new experiments."
    )
    assert fingerprint() == fingerprint(title="Active   visual\n mapping")


@pytest.mark.parametrize(
    "enrichment",
    [
        {"doi": "https://doi.org/10.1234/NEW-PUBLICATION"},
        {"venue": "A newly assigned conference"},
        {"author": "Ada Scientist, Another Author"},
        {"category": "cs.CV"},
        {"updated": "2026-10-20T10:00:00Z"},
        {
            "doi": "",
            "venue": "",
            "author": "Corrected Author",
            "category": "cs.AI",
            "updated": "2026-10-20T10:00:00Z",
        },
    ],
)
def test_bibliographic_enrichment_does_not_invalidate_paid_analysis(enrichment):
    original = feed.parse_feed(atom([entry()]))["candidates"][0]
    updated = feed.parse_feed(atom([entry(**enrichment)]))["candidates"][0]
    assert original["content_hash"] == updated["content_hash"]
    assert original != updated


@pytest.mark.parametrize(
    "raw, message",
    [
        (b"<html>Service unavailable</html>", "Invalid arXiv feed"),
        (b"<feed>", "XML"),
        (atom(["<entry><title>Error</title></entry>"]), "query error"),
        (
            atom(
                [
                    entry().replace(
                        "http://arxiv.org/abs/2402.08954v2", "http://127.0.0.1/private"
                    )
                ]
            ),
            "identifier",
        ),
        (
            atom(
                [
                    entry().replace(
                        "http://arxiv.org/abs/2402.08954v2",
                        "http://arxiv.org:80@evil.org/abs/2402.08954v2",
                    )
                ]
            ),
            "identifier",
        ),
        (atom([entry(updated="not-a-time")]), "timestamp"),
        (
            atom([entry()]).replace(
                b"<title>Active visual mapping</title>", b"<title/>"
            ),
            "title",
        ),
        (atom([], total=-1), "count"),
        (b"x" * 2_000_001, "limit"),
    ],
)
def test_bad_feeds_fail_without_silently_advancing_checkpoint(raw, message):
    with pytest.raises(ValueError, match=message):
        feed.parse_feed(raw)


def test_xml_entities_are_not_expanded():
    raw = b'<!DOCTYPE feed [<!ENTITY x SYSTEM "file:///etc/passwd">]><feed xmlns="http://www.w3.org/2005/Atom">&x;</feed>'
    with pytest.raises(ValueError, match="XML"):
        feed.parse_feed(raw)


def test_recent_update_of_old_submission_is_included_and_cutoff_ends_scan(monkeypatch):
    calls = []

    def request(url, **kwargs):
        calls.append((parse_qs(urlsplit(url).query), kwargs))
        return (
            atom(
                [
                    entry(),
                    entry("2402.08955v1", "2026-10-17T00:00:00Z"),
                    entry("2402.08956v1", "2026-10-16T23:59:59Z"),
                ],
                total=1000,
            ),
            "application/atom+xml",
            url,
        )

    monkeypatch.setattr(arxiv, "request", request)
    result = feed.fetch_candidates(
        since="2026-10-17T00:00:00Z", until="2026-10-20T00:00:00Z", page_size=3
    )
    assert result["complete"] and result["next_start"] is None
    assert [row["arxiv_id"] for row in result["candidates"]] == [
        "2402.08954",
        "2402.08955",
    ]
    assert calls[0][0]["sortBy"] == ["lastUpdatedDate"]
    assert calls[0][0]["sortOrder"] == ["descending"]
    assert "submittedDate" not in calls[0][0]["search_query"][0]
    assert calls[0][0]["search_query"] == ["(cat:cs.CV OR cat:cs.RO OR cat:cs.AI)"]
    assert calls[0][1] == {"limit": 2_000_000}


def test_paginated_scan_retains_checkpoint_and_applies_snapshot_locally(monkeypatch):
    calls = []

    def request(url, **kwargs):
        values = parse_qs(urlsplit(url).query)
        start, count = int(values["start"][0]), int(values["max_results"][0])
        calls.append((start, count))
        items = [
            entry(
                f"2402.{9000 + n}",
                "2026-10-20T12:00:00Z" if n == 0 else "2026-10-19T12:00:00Z",
            )
            for n in range(start, start + count)
        ]
        return atom(items, total=20), "text/xml", url

    monkeypatch.setattr(arxiv, "request", request)
    first = feed.fetch_candidates(
        since="2026-10-17", until="2026-10-20T00:00:00Z", max_results=4, page_size=2
    )
    assert calls == [(0, 2), (2, 2)]
    assert not first["complete"] and first["next_start"] == 4
    assert len(first["candidates"]) == 3  # newer-than-snapshot metadata is not emitted
    second = feed.fetch_candidates(
        since="2026-10-17",
        until="2026-10-20T00:00:00Z",
        max_results=4,
        page_size=2,
        start=4,
    )
    assert calls[2:] == [(3, 2), (5, 2)]  # one-row overlap tolerates offset movement
    assert second["next_start"] == 7 and not second["complete"]
    assert first["candidates"][-1]["arxiv_id"] == second["candidates"][0]["arxiv_id"]


def test_empty_and_short_pages_finish_without_more_requests(monkeypatch):
    calls = []

    def request(url, **kwargs):
        calls.append(url)
        return atom([], total=0), "application/atom+xml;charset=utf-8", url

    monkeypatch.setattr(arxiv, "request", request)
    result = feed.fetch_candidates()
    assert result == {
        "candidates": [],
        "next_start": None,
        "complete": True,
        "oldest_updated_at": None,
    }
    assert len(calls) == 1


def test_request_failure_does_not_return_partial_success(monkeypatch):
    calls = []

    def request(url, **kwargs):
        calls.append(url)
        if len(calls) == 2:
            raise httpx.ConnectError("offline")
        return atom([entry()], total=10), "application/atom+xml", url

    monkeypatch.setattr(arxiv, "request", request)
    with pytest.raises(httpx.ConnectError):
        feed.fetch_candidates(max_results=2, page_size=1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"categories": ["cs.RO) OR all:*"]},
        {"categories": "cs.RO"},
        {"categories": []},
        {"max_results": 0},
        {"max_results": True},
        {"page_size": 101},
        {"start": -1},
        {"since": "2026-10-20", "until": "2026-10-19"},
        {"since": "yesterday"},
    ],
)
def test_invalid_query_is_rejected_before_network(kwargs, monkeypatch):
    def request(*args, **kw):
        pytest.fail("invalid query attempted a network request")

    monkeypatch.setattr(arxiv, "request", request)
    with pytest.raises(ValueError):
        feed.fetch_candidates(**kwargs)


def test_paging_ceiling_is_an_error_instead_of_fake_completion(monkeypatch):
    with pytest.raises(ValueError, match="paging limit"):
        feed.fetch_candidates(start=30000, max_results=1)


def test_initial_window_is_seven_days_and_handles_timezone(monkeypatch):
    def request(url, **kwargs):
        return (
            atom(
                [
                    entry(updated="2026-10-13T08:00:00+08:00"),
                    entry("2402.08955", "2026-10-12T23:59:59Z"),
                ]
            ),
            "application/atom+xml",
            url,
        )

    monkeypatch.setattr(arxiv, "request", request)
    result = feed.fetch_candidates(
        until=datetime(2026, 10, 20, tzinfo=timezone.utc), page_size=2
    )
    assert len(result["candidates"]) == 1 and result["complete"]


INTERESTS = [
    {
        "id": "tracking",
        "name": "Tracking",
        "description": "Visual navigation for autonomous robots",
        "keywords": ["object tracking"],
        "exclude_keywords": ["medical imaging"],
        "priority": 3,
    }
]


def test_initial_filter_preserves_category_candidates_without_keywords():
    candidate = {
        "title": "A new geometric representation",
        "abstract": "Learning a useful latent structure.",
        "categories": ["cs.CV"],
    }
    result = feed.prefilter(candidate, INTERESTS)
    assert result["eligible"] and result["matched_interests"] == []
    assert result["priority_score"] == 0
    assert "潜在工作" in result["reason"]


def test_natural_language_interest_alone_preserves_broad_category_candidates():
    candidate = {
        "title": "A new geometric representation",
        "abstract": "A useful latent structure.",
        "categories": ["cs.CV"],
    }
    result = feed.prefilter(
        candidate, [], interest_description="关注无人机在动态场景中的主动视觉感知。"
    )
    assert result["eligible"] and result["matched_interests"] == []
    assert result["priority_score"] == 0
    assert not feed.prefilter(candidate, [], interest_description="  ")["eligible"]
    assert not feed.prefilter(
        candidate, [], ["geometric"], interest_description="三维视觉"
    )["eligible"]


def test_filter_ranks_natural_language_and_priority_as_hints():
    candidate = {
        "title": "Visual navigation for robots",
        "abstract": "An autonomous approach.",
        "categories": ["cs.AI"],
    }
    high = feed.prefilter(candidate, INTERESTS)
    low = feed.prefilter(candidate, [{**INTERESTS[0], "priority": 1}])
    assert high["eligible"] and high["matched_interests"] == ["tracking"]
    assert high["priority_score"] == low["priority_score"] * 3


def test_explicit_exclusions_are_scoped_and_match_whole_words():
    candidate = {
        "title": "General object tracking for medical imaging",
        "abstract": "A useful method.",
        "categories": ["cs.CV"],
    }
    assert not feed.prefilter(candidate, INTERESTS)["eligible"]
    assert not feed.prefilter(
        candidate, INTERESTS, interest_description="关注视觉方法"
    )["eligible"]
    assert feed.prefilter(
        candidate, INTERESTS + [{"id": "medical", "name": "Imaging"}]
    )["eligible"]
    assert not feed.prefilter(candidate, INTERESTS, ["object tracking"])["eligible"]
    assert feed.prefilter(candidate, [{"id": "general"}], ["gene"])["eligible"]
    assert not feed.prefilter(candidate, [], [""])["eligible"]


def test_clear_out_of_scope_is_rejected_but_cross_category_relevance_is_retained():
    candidate = {
        "title": "Electron interaction theory",
        "abstract": "High energy measurements.",
        "categories": ["hep-ph"],
    }
    assert not feed.prefilter(candidate, INTERESTS)["eligible"]
    candidate["abstract"] = "This provides a new approach to object tracking."
    assert feed.prefilter(candidate, INTERESTS)["eligible"]
