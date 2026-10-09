"""Opt-in, actual PDF → API → Marker → sanitized HTML → restart integration gate.

No paid translation calls. Data and original PDFs must remain outside Git.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import Config  # noqa: E402
from app.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--pdf", type=Path, required=True)
parser.add_argument("--data-dir", type=Path, required=True)
parser.add_argument("--executable", required=True)
parser.add_argument("--report", type=Path, required=True)
args = parser.parse_args()
config = Config(data_dir=args.data_dir, marker_executable=args.executable, marker_timeout=600)
headers = {"Origin": "http://127.0.0.1:8000", "X-PaperFlow": "1"}
app = create_app(config)
report = {"translation": "NOT RUN"}
with TestClient(app, base_url="http://127.0.0.1:8000", headers=headers) as client:
    with args.pdf.open("rb") as stream:
        response = client.post(
            "/api/v1/papers/upload", files={"file": (args.pdf.name, stream, "application/pdf")}
        )
    assert response.status_code == 200, response.text
    paper = response.json()["paper"]
    base = "/api/v1/papers/" + paper["id"]
    report["paper_id"] = paper["id"]
    client.patch(base, json={"tags": ["validation"], "collections": ["M0 actual papers"]})
    client.put(base + "/reading-position?mode=pdf", json={"pdf_page": 6, "pdf_scale": 1.1})
    started = time.monotonic()
    response = client.post(base + "/conversions", json={})
    assert response.status_code == 202, response.text
    job = response.json()["job"]
    report["job_id"] = job["id"]
    assert client.get(base + "/pdf", headers={"Range": "bytes=0-99"}).status_code == 206
    assert client.get("/api/v1/health").status_code == 200
    print("PDF/health remained usable during actual conversion", flush=True)
    previous = ""
    while time.monotonic() - started < 650:
        job = client.get("/api/v1/conversions/" + job["id"]).json()
        if job["status"] != previous:
            print("actual worker:", job["status"], job["progress_stage"], flush=True)
            previous = job["status"]
        if job["status"] not in ("queued", "running"):
            break
        time.sleep(1)
    report["status"] = job["status"]
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    assert job["status"] == "succeeded", job
    document = client.get("/read/" + paper["id"] + "/html")
    assert document.status_code == 200
    soup = BeautifulSoup(document.text, "html.parser")
    for image in soup.select("article img"):
        assert client.get(image["src"]).status_code == 200
    report["images"] = len(soup.select("article img"))
    report["math"] = len(soup.select("article math"))
    report["tables"] = len(soup.select("article table"))
    cached = client.post(base + "/conversions", json={}).json()
    assert cached["cached"]
    report["cache"] = "PASS"
    client.put(
        base + "/reading-position?mode=local_html", json={"html_anchor": "section-2", "scroll_ratio": 0.4}
    )
second = create_app(config)
with TestClient(second, base_url="http://127.0.0.1:8000", headers=headers) as client:
    assert client.get(base).json()["has_html"]
    assert client.get(base).json()["collections"][0]["name"] == "m0 actual papers"
    assert client.get(base + "/reading-position?mode=pdf").json()["pdf_page"] == 6
    assert client.get(base + "/reading-position?mode=local_html").json()["scroll_ratio"] == 0.4
report["restart"] = "PASS"
args.report.parent.mkdir(parents=True, exist_ok=True)
args.report.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2), flush=True)
