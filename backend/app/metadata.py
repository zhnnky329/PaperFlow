"""Bounded local extraction and conservative bibliographic enrichment."""

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
import tempfile
from contextlib import nullcontext
from difflib import SequenceMatcher
from urllib.parse import quote

import httpx
import psutil
from pypdf import PdfReader
from sqlalchemy import select

from . import arxiv
from .config import ROOT
from .db import Paper, Setting, now

FIELDS = {"title", "authors", "abstract", "year", "doi", "venue", "venue_kind", "affiliations", "source_url"}
PROTECTED = {"manual", "crossref-confirmed", "legacy"}
_network_lock = threading.Lock()
_last_request = 0.0


def normalize_doi(value):
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value.strip(), flags=re.I)
    return value.lower() if re.fullmatch(r"10\.\d{4,9}/[^\s<>\"?#]+", value) and len(value) <= 300 else None


def apply_values(paper, values, source):
    sources = dict(paper.metadata_sources or {})
    for field in FIELDS:
        value = values.get(field)
        if value in (None, "", []):
            continue
        if sources.get(field) in PROTECTED and not (sources[field] == source == "crossref-confirmed"):
            if sources[field] != "legacy" or getattr(paper, field) not in (None, "", []):
                continue
        # A less reliable local guess cannot replace official data.
        if source == "pdf" and sources.get(field) in ("arxiv", "crossref"):
            continue
        if source == "arxiv" and field in ("doi", "venue", "venue_kind") and sources.get(field) == "crossref":
            continue
        if field == "doi":
            value = normalize_doi(value)
            if not value:
                continue
        if field == "affiliations":
            grouped = {}
            for item in value[:100]:
                name = item["name"].strip()[:500]
                if not name:
                    continue
                authors = grouped.setdefault(name, [])
                for author in item.get("authors", [])[:100]:
                    author = author.strip()[:500]
                    if author and author not in authors:
                        authors.append(author)
            value = [{"name": name, "authors": authors} for name, authors in grouped.items()]
        setattr(paper, field, value)
        sources[field] = source
    paper.metadata_sources = sources
    paper.updated_at = now()


def extract_pdf(path):
    """Only the opening pages, never the reference list or a remote upload."""
    reader = PdfReader(path, strict=True)
    text = "\n".join(reader.pages[index].extract_text()[:40000] for index in range(min(2, len(reader.pages))))
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    text = re.split(r"(?im)^\s*(?:references|bibliography|参考文献)\s*$", text)[0]
    result = {}
    identifiers = re.findall(
        r"(?:\bdoi\s*:\s*|https?://(?:dx\.)?doi\.org/)(10\.\d{4,9}/[^\s<>\"]+)", text, re.I
    )
    dois = {doi for value in identifiers if (doi := normalize_doi(value.rstrip(".,;")))}
    if len(dois) == 1:
        result["doi"] = dois.pop()
    match = re.search(
        r"(?:arxiv\s*:\s*|https://arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5}(?:v\d+)?|[a-z][a-z.\-]+/\d{7}(?:v\d+)?)",
        text,
        re.I,
    )
    if match:
        result["arxiv"] = match[1].lower()
    header = re.split(r"(?im)^\s*(?:abstract|摘要|(?:1[.\s]+)?introduction)\b", text)[0]
    institutions = []
    for line in header.splitlines()[:75]:
        line = re.sub(r"^\s*[\d*†‡,\s]+", "", line).strip()
        if (
            4 <= len(line) <= 250
            and "@" not in line
            and re.search(
                r"\b(?:university|institute|laboratory|laboratories|college|academy|research center)\b|大学|研究院|研究所|实验室",
                line,
                re.I,
            )
        ):
            if line not in institutions:
                institutions.append(line)
    if institutions:
        result["affiliations"] = [{"name": name, "authors": []} for name in institutions[:20]]
    # Author footnotes may appear below the abstract and wrap across lines.
    footnote = re.search(
        r"(?is)(?<![A-Za-z])All authors (?:are|were) with\s+(.{4,500}?)(?=\.\s|\n\s*\{|$)", text
    )
    if footnote:
        institution = " ".join(footnote[1].split()).strip(" .")
        if re.search(r"\b(?:university|institute|laboratory|college|department)\b", institution, re.I):
            result.setdefault("affiliations", []).append(
                {"name": institution, "authors": [], "all_authors": True}
            )
    venue = re.search(r"(?im)^\s*(Journal|Conference)\s*:\s*(.{3,200})$", header)
    if venue:
        result.update(venue=venue[2].strip(), venue_kind=venue[1].lower())
    return result


def local_extract(config, relative):
    # A malformed compressed text stream cannot hold the HTTP server indefinitely.
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "app.metadata", "extract", str(config.path(relative))],
            cwd=ROOT,
            env=dict(os.environ, PYTHONPATH=str(ROOT / "backend")),
            stdout=output,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 12
        try:
            while process.poll() is None:
                if time.monotonic() > deadline:
                    raise ValueError("Metadata extraction timed out")
                try:
                    if psutil.Process(process.pid).memory_info().rss > 512 * 1024 * 1024:
                        raise ValueError("Metadata extraction memory limit")
                except psutil.NoSuchProcess:
                    pass
                time.sleep(0.05)
            if process.returncode or os.fstat(output.fileno()).st_size > 100000:
                raise ValueError("Metadata extraction failed or output too large")
            output.seek(0)
            return json.load(output)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def request_crossref(path, params=None):
    """Fixed HTTPS origin, no redirects/proxies, bounded response and rate."""
    global _last_request
    with _network_lock:
        time.sleep(max(0, 1 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        with httpx.Client(
            timeout=httpx.Timeout(15, connect=5), trust_env=False, follow_redirects=False
        ) as client:
            with client.stream(
                "GET",
                "https://api.crossref.org/works" + path,
                params=params,
                headers={"User-Agent": "PaperFlow/0.1 (local bibliographic lookup)"},
            ) as response:
                if response.is_redirect:
                    raise ValueError("Crossref redirect rejected")
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 1_000_000:
                        raise ValueError("Crossref response too large")
                return json.loads(content)["message"]


def cached_crossref(sessions, doi=None, title=None, author=None):
    query = {"doi": doi} if doi else {"title": title, "author": author}
    key = "metadata-cache:" + hashlib.sha256(json.dumps(query, sort_keys=True).encode()).hexdigest()
    with sessions() as session:
        row = session.get(Setting, key)
        if row and time.time() - row.value["time"] < 7 * 86400:
            return row.value["result"]
    if doi:
        message = request_crossref("/" + quote(doi, safe=""))
        result = [crossref_record(message)]
        if not result[0] or result[0]["doi"] != doi:
            raise ValueError("DOI response mismatch")
    else:
        params = {"query.bibliographic": title, "rows": 3}
        if author:
            params["query.author"] = author
        result = [
            record
            for item in request_crossref("", params).get("items", [])[:3]
            if (record := crossref_record(item))
        ]
    with sessions() as session:
        session.merge(Setting(key=key, value={"time": time.time(), "result": result}))
        session.commit()
    return result


def crossref_record(item):
    doi = normalize_doi(str(item.get("DOI", "")))
    titles = item.get("title") or []
    if not doi or not titles or not isinstance(titles[0], str):
        return None
    authors, affiliations = [], {}
    for person in item.get("author", [])[:100]:
        name = " ".join(str(person.get(part, "")) for part in ("given", "family")).strip()[:500]
        if name:
            authors.append(name)
        for affiliation in person.get("affiliation", [])[:30]:
            institution = str(affiliation.get("name", "")).strip()[:500]
            if institution:
                linked = affiliations.setdefault(institution, [])
                if name and name not in linked:
                    linked.append(name)
    kind = {"journal-article": "journal", "proceedings-article": "conference"}.get(item.get("type"))
    containers = item.get("container-title") or []
    venue = str(containers[0])[:1000] if containers and kind else None
    if kind == "conference" and item.get("event", {}).get("name"):
        venue = str(item["event"]["name"])[:1000]
    dates = item.get("published", item.get("issued", {})).get("date-parts", [[]])
    year = dates[0][0] if dates and dates[0] else None
    if not isinstance(year, int) or not 1500 <= year <= 2200:
        year = None
    return {
        "doi": doi,
        "title": titles[0][:1000],
        "authors": authors,
        "year": year,
        "venue": venue,
        "venue_kind": kind,
        "affiliations": [
            {"name": name, "authors": names} for name, names in list(affiliations.items())[:100]
        ],
    }


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def is_publication(record):
    return bool(record.get("venue")) and record.get("venue_kind") in ("journal", "conference")


def publication_sources(paper):
    """Publication and arXiv are independent sources for the same library item."""
    sources = []
    if paper.venue:
        doi = normalize_doi(paper.doi) if paper.doi else None
        sources.append(
            {
                "kind": paper.venue_kind or "publication",
                "label": paper.venue,
                "url": "https://doi.org/" + quote(doi, safe="/") if doi else None,
            }
        )
    if paper.arxiv_id:
        canonical = paper.arxiv_id + (f"v{paper.arxiv_version}" if paper.arxiv_version else "")
        sources.append(
            {"kind": "arxiv", "label": "arXiv:" + canonical, "url": "https://arxiv.org/abs/" + canonical}
        )
    return sources


def match_records(records, title, authors):
    """Crossref search ranking alone is not evidence of the same paper."""
    candidates = []
    for record in records:
        score = SequenceMatcher(None, normalized(title), normalized(record["title"])).ratio()
        # Author agreement helps present plausible candidates; it is never used
        # to silently accept a title search result.
        author_match = bool(set(map(normalized, authors)) & set(map(normalized, record["authors"])))
        if score >= 0.65:
            candidates.append(record | {"match_score": round(score, 3), "author_match": author_match})
    # Title searches always require confirmation: preprint/published versions can
    # share a title and author while referring to different publications.
    return sorted(
        candidates,
        key=lambda record: (is_publication(record), record["match_score"], record["author_match"]),
        reverse=True,
    )


def refresh(config, sessions, paper_id, lock=None, search=False):
    with sessions() as session:
        paper = session.get(Paper, paper_id)
        if not paper:
            return
        snapshot = {field: getattr(paper, field) for field in FIELDS}
        snapshot_sources = dict(paper.metadata_sources or {})
        pdf_path, arxiv_id, version = paper.pdf_path, paper.arxiv_id, paper.arxiv_version
    local, official, external, candidates = {}, {}, {}, []
    error, attempted, success = None, False, False
    if pdf_path:
        try:
            local = local_extract(config, pdf_path)
        except (OSError, ValueError, subprocess.SubprocessError):
            error = "PDF 文字信息未能提取，可以手动填写。"
    canonical = arxiv_id + (f"v{version}" if version else "") if arxiv_id else local.get("arxiv")
    if canonical and config.metadata_online:
        attempted = True
        official = arxiv.lookup(canonical)
        success = official["metadata_status"] == "ready"
        if (
            success
            and not arxiv_id
            and snapshot_sources.get("title") != "filename"
            and SequenceMatcher(
                None, normalized(snapshot["title"]), normalized(official.get("title", ""))
            ).ratio()
            < 0.9
        ):
            official, canonical, success = {}, None, False
            error = "PDF 中的 arXiv ID 与标题不一致，请核对标识或手动填写。"
        if not success:
            error = error or "arXiv 信息暂时无法获取，请稍后重试。"
    doi = snapshot["doi"] or official.get("doi") or local.get("doi")
    if snapshot_sources.get("doi") == "manual" and not snapshot["doi"]:
        doi = None
    doi = normalize_doi(doi) if doi else None
    lookup_title = official.get("title") or snapshot["title"]
    title_lookup = (
        search
        or bool(official.get("title"))
        or (
            bool(local.get("affiliations"))
            and snapshot_sources.get("title") == "pdf"
            and bool(snapshot["authors"])
        )
    )
    if config.metadata_online and (doi or (title_lookup and len(lookup_title) >= 8)):
        attempted = True
        try:
            records = cached_crossref(
                sessions,
                doi=doi,
                title=lookup_title,
                author=(official.get("authors") or snapshot["authors"] or [None])[0],
            )
            if doi:
                record = records[0]
                known_title = official.get("title") or snapshot["title"]
                title_agrees = (
                    SequenceMatcher(None, normalized(known_title), normalized(record["title"])).ratio() >= 0.9
                )
                # A DOI found in PDF text might belong to a cited paper.
                if (
                    (doi == local.get("doi") or snapshot_sources.get("doi") == "pdf")
                    and snapshot_sources.get("doi") != "manual"
                    and not official.get("doi")
                    and not title_agrees
                ):
                    candidates = [record | {"match_score": 0}]
                    local.pop("doi", None)
                    error = "PDF 中的 DOI 与标题不一致，请核对候选。"
                else:
                    external = record
                    success = True
                    # A preprint DOI does not rule out a later journal/conference
                    # version. Look for that version while retaining arXiv.
                    if canonical and not is_publication(record):
                        alternatives = cached_crossref(
                            sessions,
                            title=lookup_title,
                            author=(official.get("authors") or snapshot["authors"] or [None])[0],
                        )
                        candidates = match_records(
                            alternatives, lookup_title, official.get("authors") or snapshot["authors"]
                        )
            else:
                candidates = match_records(
                    records, lookup_title, official.get("authors") or snapshot["authors"]
                )
                success = True
                if not candidates and not canonical:
                    error = "未找到可靠的匹配，可补充 DOI 或手动填写。"
            if canonical:
                # Keep arXiv as the preprint source rather than suggesting a
                # second preprint service as a journal/conference publication.
                candidates = [candidate for candidate in candidates if is_publication(candidate)]
        except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError):
            error = "发表信息暂时无法获取，请检查网络或稍后重试。"
    with lock or nullcontext(), sessions() as session:
        paper = session.get(Paper, paper_id)
        if not paper:
            return
        if paper.doi != snapshot["doi"]:
            paper.metadata_status = "failed"
            paper.metadata_error = "识别期间 DOI 已修改，请重新查找元信息。"
            session.commit()
            return
        # Re-read after the network request so concurrent manual edits win.
        for institution in local.get("affiliations", []):
            if institution.pop("all_authors", False):
                institution["authors"] = official.get("authors") or snapshot["authors"] or []
        apply_values(paper, local, "pdf")
        apply_values(paper, official, "arxiv")
        apply_values(paper, external, "crossref")
        if "official_html_url" in official:
            paper.official_html_url = official["official_html_url"]
        if canonical and not paper.arxiv_id:
            detected_id, detected_version = arxiv.parse(canonical)
            existing = session.scalar(
                select(Paper).where(Paper.arxiv_id == detected_id, Paper.arxiv_version == detected_version)
            )
            if not existing:
                paper.arxiv_id, paper.arxiv_version = detected_id, detected_version
        paper.metadata_candidates = candidates
        paper.metadata_error = error
        paper.metadata_status = (
            "needs_review"
            if candidates
            else "ready"
            if success
            else "failed"
            if attempted or error
            else "local"
        )
        session.commit()


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "extract":
        sys.exit(2)
    print(json.dumps(extract_pdf(sys.argv[2]), ensure_ascii=False))
