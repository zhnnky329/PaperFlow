"""Only canonical official URLs are fetched, with bounded streams and redirects."""

import re
import threading
import time
from urllib.parse import urlsplit, urljoin
from defusedxml.ElementTree import fromstring, ParseError
from defusedxml.common import DefusedXmlException
import httpx
from fastapi import HTTPException
from .db import Paper, now

ID = re.compile(r"^(\d{4}\.\d{4,5}|[a-z][a-z.\-]+/\d{7})(?:v([1-9]\d*))?$")
HOSTS = {"arxiv.org", "export.arxiv.org", "www.arxiv.org"}
_lock = threading.Lock()
_last_request = 0.0
_cooldown = {}


def parse(value):
    value = value.strip()
    if "://" in value:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or url.hostname not in HOSTS
            or url.port not in (None, 443)
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise HTTPException(422, "仅支持官方 HTTPS arXiv 地址或 ID")
        match = re.fullmatch(r"/(?:abs|pdf|html)/(.+)", url.path)
        if not match:
            raise HTTPException(422, "arXiv 地址格式不正确")
        value = match[1]
    value = value.removesuffix(".pdf")
    match = ID.fullmatch(value)
    if not match:
        raise HTTPException(422, "arXiv ID 格式不正确")
    return match[1], int(match[2] or 0)


def request(url, limit=2_000_000, destination=None):
    global _last_request
    with _lock:
        host = urlsplit(url).hostname
        if _cooldown.get(host, 0) > time.monotonic():
            raise ValueError("arXiv rate limit cooldown; retry later")
        time.sleep(max(0, 3 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        with httpx.Client(
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "PaperFlow/0.1 (local personal library)"},
        ) as client:
            for _ in range(4):
                parsed = urlsplit(url)
                if (
                    parsed.scheme != "https"
                    or parsed.hostname not in HOSTS
                    or parsed.port not in (None, 443)
                    or parsed.username
                    or parsed.password
                ):
                    raise ValueError("Unsafe redirect")
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers["location"])
                        continue
                    if response.status_code == 429:
                        try:
                            delay = int(response.headers.get("retry-after", "60"))
                        except ValueError:
                            delay = 60
                        _cooldown[parsed.hostname] = time.monotonic() + max(3, min(delay, 300))
                    response.raise_for_status()
                    size = 0
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise ValueError("Remote resource exceeds limit")
                        if destination:
                            destination.write(chunk)
                        else:
                            content.extend(chunk)
                    return bytes(content), response.headers.get("content-type", ""), url
        raise ValueError("Too many redirects")


def refresh(session_factory, paper_id):
    with session_factory() as session:
        paper = session.get(Paper, paper_id)
        if not paper:
            return
        canonical = paper.arxiv_id + (f"v{paper.arxiv_version}" if paper.arxiv_version else "")
    values = {"metadata_status": "failed", "updated_at": now()}
    try:
        raw, _, _ = request("https://export.arxiv.org/api/query?id_list=" + canonical)
        entry = fromstring(raw).find("{http://www.w3.org/2005/Atom}entry")
        if entry is not None:
            ns = "{http://www.w3.org/2005/Atom}"
            title = " ".join((entry.findtext(ns + "title") or "").split())
            if title and title != "Error":
                values.update(
                    title=title[:1000],
                    abstract=entry.findtext(ns + "summary", "")[:30000],
                    authors=[a.findtext(ns + "name", "") for a in entry.findall(ns + "author")],
                    year=int(entry.findtext(ns + "published")[:4]),
                    metadata_status="ready",
                )
    except (httpx.HTTPError, ValueError, TypeError, ParseError, DefusedXmlException):
        pass
    try:
        raw, kind, final = request("https://arxiv.org/html/" + canonical, limit=15_000_000)
        if "text/html" in kind and b"<html" in raw.lower() and ("/html/" + canonical) in urlsplit(final).path:
            values["official_html_url"] = final
        else:
            values["official_html_url"] = None
    except (httpx.HTTPError, ValueError):
        pass  # don't discard a previously verified URL for transient network failure
    with session_factory() as session:
        paper = session.get(Paper, paper_id)
        if paper:
            for key, value in values.items():
                setattr(paper, key, value)
            session.commit()
