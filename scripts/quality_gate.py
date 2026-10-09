"""Opt-in ten public paper gate: eight real Marker jobs and two official HTML imports.

Artifacts stay in the chosen external data directory. This does not test Read Frog
or assert visual quality; follow with Chrome inspection and PDF comparison.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

root = Path(__file__).resolve().parents[1]
load_dotenv(root / ".env")
sys.path.insert(0, str(root / "backend"))
from app import arxiv  # noqa: E402
from app.config import Config  # noqa: E402
from app.main import create_app  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pypdf import PdfReader  # noqa: E402

SAMPLES = [
    ("2107.06829", "FAST-LIO2", "robotics", "marker"),
    ("2007.00258", "LIO-SAM", "robotics", "marker"),
    ("2007.11898", "ORB-SLAM3", "robotics", "marker"),
    ("1404.2334", "Informed RRT*", "robotics", "marker"),
    ("1706.03762", "Attention Is All You Need", "math", "marker"),
    ("1806.07366", "Neural Ordinary Differential Equations", "math", "marker"),
    ("1512.03385", "Deep Residual Learning", "figures-tables", "marker"),
    ("1506.02640", "You Only Look Once", "figures-tables", "marker"),
    ("2402.08954", "HTML papers on arXiv", "official-html", "official"),
    ("2312.00752", "Mamba", "official-html", "official"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--executable", default=Config().marker_executable)
    args = parser.parse_args()
    config = Config(data_dir=args.data_dir, marker_executable=args.executable)
    samples_dir = config.path("samples")
    samples_dir.mkdir(parents=True, exist_ok=True)
    result = {"mode": "fast", "read_frog": "NOT RUN", "visual_quality": "NOT RUN", "samples": []}

    def record(row):
        result["samples"].append(row)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(row, ensure_ascii=False), flush=True)

    headers = {"Origin": "http://127.0.0.1:8000", "X-PaperFlow": "1"}
    app = create_app(config)
    with TestClient(app, base_url="http://127.0.0.1:8000", headers=headers) as client:
        client.patch("/api/v1/settings", json={"marker_mode": "fast"}).raise_for_status()
        for arxiv_id, title, category, mode in SAMPLES:
            row = {"arxiv_id": arxiv_id, "title": title, "category": category, "reader": mode}
            try:
                if mode == "official":
                    response = client.post("/api/v1/papers/arxiv", json={"input": arxiv_id})
                    response.raise_for_status()
                    paper = response.json()["paper"]
                    for _ in range(100):
                        paper = client.get("/api/v1/papers/" + paper["id"]).json()
                        if paper["metadata_status"] != "pending":
                            break
                        time.sleep(1)
                    row.update(paper_id=paper["id"], metadata_status=paper["metadata_status"])
                    opened = client.post("/api/v1/papers/" + paper["id"] + "/open-official")
                    opened.raise_for_status()
                    row.update(status="succeeded", official_html_url=opened.json()["official_html_url"])
                    record(row)
                    continue
                pdf = samples_dir / (arxiv_id + ".pdf")
                if not pdf.exists():
                    staging = pdf.with_suffix(".staging")
                    try:
                        with staging.open("wb") as output:
                            arxiv.request("https://arxiv.org/pdf/" + arxiv_id, 100_000_000, output)
                        PdfReader(staging, strict=True)
                        staging.replace(pdf)
                    finally:
                        staging.unlink(missing_ok=True)
                row["pages"] = len(PdfReader(pdf).pages)
                row["pdf_sha256"] = hashlib.sha256(pdf.read_bytes()).hexdigest()
                with pdf.open("rb") as stream:
                    response = client.post(
                        "/api/v1/papers/upload", files={"file": (pdf.name, stream, "application/pdf")}
                    )
                response.raise_for_status()
                paper = response.json()["paper"]
                row["paper_id"] = paper["id"]
                base = "/api/v1/papers/" + paper["id"]
                client.patch(base, json={"title": title, "collections": ["quality gate"], "tags": [category]})
                started = time.monotonic()
                response = client.post(base + "/conversions", json={})
                response.raise_for_status()
                job = response.json()["job"]
                print(f"{arxiv_id}: real Marker queued ({row['pages']} pages)", flush=True)
                while time.monotonic() - started < config.marker_timeout + 20:
                    assert client.get("/api/v1/health").status_code == 200
                    assert client.get(base + "/pdf", headers={"Range": "bytes=0-99"}).status_code == 206
                    job = client.get("/api/v1/conversions/" + job["id"]).json()
                    if job["status"] not in ("queued", "running"):
                        break
                    time.sleep(1)
                row.update(status=job["status"], elapsed_seconds=round(time.monotonic() - started, 2))
                if job["status"] != "succeeded":
                    row["error_code"] = job.get("error_code")
                else:
                    document = client.get("/read/" + paper["id"] + "/html")
                    document.raise_for_status()
                    soup = BeautifulSoup(document.text, "html.parser")
                    for image in soup.select("article img"):
                        assert client.get(image["src"]).status_code == 200
                    row.update(
                        images=len(soup.select("article img")),
                        math=len(soup.select("article math")),
                        tables=len(soup.select("article table")),
                        headings=len(soup.select("article h1,article h2,article h3,article h4")),
                        cache="PASS"
                        if client.post(base + "/conversions", json={}).json()["cached"]
                        else "FAIL",
                    )
                record(row)
            except Exception as exc:
                row.update(status="failed", exception=type(exc).__name__)
                record(row)
    failed = sum(row["status"] != "succeeded" for row in result["samples"])
    print(
        f"Actual jobs/official HTML: {len(SAMPLES) - failed}/10 succeeded; visual quality NOT RUN", flush=True
    )
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
