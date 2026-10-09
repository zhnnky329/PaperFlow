"""Opt-in verification of a real library restored using scripts/backup.py.

Check positions against the stopped source, then open a new app factory against
the restored directory and verify original PDFs, HTML assets and cached jobs.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from dotenv import load_dotenv

root = Path(__file__).resolve().parents[1]
load_dotenv(root / ".env")
sys.path.insert(0, str(root / "backend"))
from app.config import Config  # noqa: E402
from app.main import create_app  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source-data-dir", type=Path, required=True)
parser.add_argument("--restored-data-dir", type=Path, required=True)
parser.add_argument("--sample-report", type=Path, required=True)
parser.add_argument("--archive", type=Path, required=True)
parser.add_argument("--report", type=Path, required=True)
args = parser.parse_args()


def positions(directory):
    path = (directory / "paperflow.sqlite3").resolve()
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as database:
        return database.execute("select * from reading_positions order by paper_id, mode").fetchall()


assert positions(args.source_data_dir) == positions(args.restored_data_dir)
samples = json.loads(args.sample_report.read_text())["samples"]
headers = {"Origin": "http://127.0.0.1:8000", "X-PaperFlow": "1"}
images = pdfs = html_readers = 0
with TestClient(
    create_app(Config(data_dir=args.restored_data_dir, port=8000)),
    base_url="http://127.0.0.1:8000",
    headers=headers,
) as client:
    assert client.get("/api/v1/papers").json()["total"] == len(samples)
    for sample in samples:
        base = "/api/v1/papers/" + sample["paper_id"]
        if sample["reader"] == "marker":
            assert client.get(base + "/pdf", headers={"Range": "bytes=0-99"}).status_code == 206
            pdfs += 1
            document = client.get("/read/" + sample["paper_id"] + "/html")
            assert document.status_code == 200
            html_readers += 1
            for image in BeautifulSoup(document.text, "html.parser").select("article img"):
                assert client.get(image["src"]).status_code == 200
                images += 1
            assert client.post(base + "/conversions", json={}).json()["cached"]
        else:
            assert client.get(base).json()["official_html_url"] == sample["official_html_url"]
result = {
    "backup": "PASS",
    "restore_new_directory": "PASS",
    "new_app_factory": "PASS",
    "papers": len(samples),
    "pdf_range_206": pdfs,
    "html_readers": html_readers,
    "images_200": images,
    "cache": "PASS",
    "positions_identical": len(positions(args.source_data_dir)),
    "translation": "NOT RUN",
    "archive_bytes": args.archive.stat().st_size,
}
args.report.parent.mkdir(parents=True, exist_ok=True)
args.report.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
