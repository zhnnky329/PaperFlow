"""Bounded arXiv metadata discovery, independent from the user's Library.

The API documents submittedDate filtering, but only sorting for lastUpdatedDate.
Consequently an old paper's new version must be found by scanning the categories
in update order and applying the time window locally. ``until`` is an output
boundary, not a server snapshot; continuation overlaps some rows to tolerate
shifting offsets. Callers must deduplicate persisted IDs and overlap successive
time windows, since the remote API cannot provide snapshot-consistent pagination.
"""

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

from defusedxml.ElementTree import fromstring, ParseError
from defusedxml.common import DefusedXmlException
from fastapi import HTTPException

from . import arxiv
from .metadata import normalize_doi

DEFAULT_CATEGORIES = ("cs.CV", "cs.RO", "cs.AI")
ATOM = "{http://www.w3.org/2005/Atom}"
EXTRA = "{http://arxiv.org/schemas/atom}"
OPEN_SEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
CATEGORY = re.compile(r"[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)?")


def _date(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Invalid discovery timestamp") from exc
    if not isinstance(value, datetime):
        raise ValueError("Invalid discovery timestamp")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _text(entry, name, limit):
    return " ".join((entry.findtext(name) or "").split())[:limit]


def _identifier(value):
    # Official Atom IDs still use http://; no network request is made to them.
    if value.startswith("http://"):
        try:
            parsed = urlsplit(value)
            if (
                parsed.hostname not in arxiv.HOSTS
                or parsed.port not in (None, 80)
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Invalid arXiv feed identifier")
        except ValueError as exc:
            raise ValueError("Invalid arXiv feed identifier") from exc
        value = "https://" + parsed.hostname + parsed.path
    try:
        return arxiv.parse(value)
    except HTTPException as exc:
        raise ValueError("Invalid arXiv feed identifier") from exc


def parse_feed(raw):
    """Parse trusted-origin, untrusted XML; never follow links in the response."""
    if len(raw) > 2_000_000:
        raise ValueError("arXiv feed exceeds limit")
    try:
        root = fromstring(raw)
    except (ParseError, DefusedXmlException) as exc:
        raise ValueError("Invalid arXiv feed XML") from exc
    if root.tag != ATOM + "feed":
        raise ValueError("Invalid arXiv feed")
    total = root.findtext(OPEN_SEARCH + "totalResults")
    try:
        total = int(total) if total is not None else None
        if total is not None and total < 0:
            raise ValueError
    except ValueError as exc:
        raise ValueError("Invalid arXiv result count") from exc
    entries = root.findall(ATOM + "entry")
    candidates = {}
    for entry in entries:
        title = _text(entry, ATOM + "title", 1000)
        if title == "Error":
            raise ValueError("arXiv returned a query error")
        if not title:
            raise ValueError("arXiv feed entry has no title")
        arxiv_id, version = _identifier(_text(entry, ATOM + "id", 1000))
        published = _date(entry.findtext(ATOM + "published"))
        updated = _date(entry.findtext(ATOM + "updated"))
        categories = list(
            dict.fromkeys(
                category.attrib.get("term", "")
                for category in entry.findall(ATOM + "category")
                if CATEGORY.fullmatch(category.attrib.get("term", ""))
            )
        )[:40]
        primary = entry.find(EXTRA + "primary_category")
        if primary is not None and CATEGORY.fullmatch(primary.attrib.get("term", "")):
            category = primary.attrib["term"]
            categories = [category] + [item for item in categories if item != category]
        canonical = arxiv_id + (f"v{version}" if version else "")
        candidate = {
            "arxiv_id": arxiv_id,
            "arxiv_version": version,
            "doi": normalize_doi(_text(entry, EXTRA + "doi", 1000)),
            "title": title,
            "authors": [
                name
                for author in entry.findall(ATOM + "author")[:100]
                if (name := _text(author, ATOM + "name", 500))
            ],
            "abstract": _text(entry, ATOM + "summary", 30000),
            "categories": categories,
            "published_at": published.isoformat(),
            "updated_at": updated.isoformat(),
            "source_url": "https://arxiv.org/abs/" + canonical,
            "pdf_url": "https://arxiv.org/pdf/" + canonical,
            "venue": _text(entry, EXTRA + "journal_ref", 1000) or None,
        }
        # Bibliographic enrichment does not invalidate paid analysis. New
        # versions do: the body can change without a title/abstract change.
        substantive = {key: candidate[key] for key in ("arxiv_id", "arxiv_version", "title", "abstract")}
        candidate["content_hash"] = hashlib.sha256(
            json.dumps(substantive, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        previous = candidates.get(arxiv_id)
        if previous is None or (version, candidate["updated_at"]) > (
            previous["arxiv_version"],
            previous["updated_at"],
        ):
            candidates[arxiv_id] = candidate
    return {"candidates": list(candidates.values()), "total_results": total, "entry_count": len(entries)}


def fetch_candidates(
    *, categories=DEFAULT_CATEGORIES, since=None, until=None, max_results=100, page_size=50, start=0
):
    """Scan at most max_results metadata rows, returning a resumable offset.

    ``complete=False`` means the caller must retain this window's since/until
    and resume next_start before advancing its successful-check watermark.
    Network errors propagate so partial windows cannot be mistaken for success.
    """
    if (
        not categories
        or isinstance(categories, str)
        or len(categories) > 16
        or any(
            not isinstance(value, str) or len(value) > 64 or not CATEGORY.fullmatch(value)
            for value in categories
        )
    ):
        raise ValueError("Invalid arXiv discovery categories")
    for name, value, lower, upper in (
        ("max_results", max_results, 1, 1000),
        ("page_size", page_size, 1, 100),
        ("start", start, 0, 30000),
    ):
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError("Invalid discovery " + name)
    until = _date(until) if until is not None else datetime.now(timezone.utc)
    since = _date(since) if since is not None else until - timedelta(days=7)
    if since > until:
        raise ValueError("Discovery since must not exceed until")
    overlap = min(page_size, max_results // 4) if start else 0
    offset = max(0, start - overlap)
    scanned = 0
    candidates = {}
    oldest = None
    complete = False
    query = "(" + " OR ".join("cat:" + value for value in dict.fromkeys(categories)) + ")"
    while scanned < max_results:
        count = min(page_size, max_results - scanned)
        # arXiv recommends refining queries beyond 1,000 results. A category
        # update window is normally small; never silently treat the API's
        # 30,000-result ceiling as an exhausted feed.
        if offset >= 30000:
            raise ValueError("arXiv discovery window exceeds paging limit; narrow the window")
        count = min(count, 30000 - offset)
        url = "https://export.arxiv.org/api/query?" + urlencode(
            {
                "search_query": query,
                "start": offset,
                "max_results": count,
                "sortBy": "lastUpdatedDate",
                "sortOrder": "descending",
            }
        )
        raw, kind, _ = arxiv.request(url, limit=2_000_000)
        if not any(content_type in kind.lower() for content_type in ("xml", "atom")):
            raise ValueError("Unexpected arXiv feed content type")
        page = parse_feed(raw)
        if page["entry_count"] > count:
            raise ValueError("arXiv feed exceeded requested page size")
        scanned += page["entry_count"]
        offset += page["entry_count"]
        reached_since = False
        for candidate in page["candidates"]:
            updated = _date(candidate["updated_at"])
            oldest = updated if oldest is None else min(oldest, updated)
            if updated < since:
                reached_since = True
            elif updated <= until:
                previous = candidates.get(candidate["arxiv_id"])
                if previous is None or candidate["arxiv_version"] > previous["arxiv_version"]:
                    candidates[candidate["arxiv_id"]] = candidate
        if (
            reached_since
            or page["entry_count"] < count
            or (page["total_results"] is not None and offset >= page["total_results"])
        ):
            complete = True
            break
    return {
        "candidates": list(candidates.values()),
        "next_start": None if complete else offset,
        "complete": complete,
        "oldest_updated_at": oldest.isoformat() if oldest else None,
    }


def _normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _matches(term, text):
    term = _normalized(term)
    if not term:
        return False
    # Bound ASCII words, so an exclusion such as "gene" cannot reject a paper
    # about "general" visual methods. Chinese phrases use substring matching.
    if term.isascii():
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text))
    return term in text


def prefilter(candidate, interests, exclude_keywords=(), *, interest_description=""):
    """Reject explicit exclusions; rank broad-category candidates for the AI.

    Keyword/description overlap is a scheduling hint, never an AI relevance
    score. An in-scope category remains eligible without any lexical match.
    Per-interest exclusions apply only to that interest, so they cannot veto a
    paper that remains useful to a different research direction.
    """
    text = _normalized(candidate.get("title", "") + " " + candidate.get("abstract", ""))
    if any(_matches(term, text) for term in exclude_keywords if isinstance(term, str)):
        return {"eligible": False, "matched_interests": [], "priority_score": 0, "reason": "命中全局排除词"}
    matches = []
    priority_score = 0
    active = []
    for interest in interests:
        if any(
            _matches(term, text) for term in interest.get("exclude_keywords", []) if isinstance(term, str)
        ):
            continue
        active.append(interest)
        keywords = [term for term in interest.get("keywords", []) if isinstance(term, str)]
        lexical = sum(_matches(term, text) for term in keywords)
        description = _normalized(interest.get("name", "") + " " + interest.get("description", ""))
        tokens = set(re.findall(r"[a-z][a-z-]{3,}", description)) - {
            "with",
            "that",
            "this",
            "from",
            "into",
            "using",
            "research",
            "methods",
            "method",
        }
        description_hits = sum(_matches(token, text) for token in tokens)
        matched = (
            lexical > 0
            or description_hits >= 2
            or (bool(interest.get("name")) and _matches(interest["name"], text))
        )
        if matched:
            matches.append(str(interest.get("id") or interest.get("name") or ""))
            priority = interest.get("priority", 1)
            priority = max(1, min(3, priority)) if type(priority) is int else 1
            priority_score += priority * (min(lexical, 5) * 3 + min(description_hits, 4) + 1)
    in_scope = bool(set(candidate.get("categories", [])) & set(DEFAULT_CATEGORIES))
    has_general_interest = not interests and bool(interest_description.strip())
    eligible = (bool(active) or has_general_interest) and (in_scope or bool(matches))
    reason = "研究方向词汇相关，交由 AI 判断" if matches else "保留相关分类中的潜在工作，交由 AI 判断"
    if not eligible:
        reason = (
            "没有启用的研究方向"
            if not interests and not has_general_interest
            else "不在关注分类或命中各研究方向排除词"
        )
    return {
        "eligible": eligible,
        "matched_interests": matches,
        "priority_score": priority_score,
        "reason": reason,
    }
