import json
import time
import pytest
from fastapi.testclient import TestClient
from app.db import Job
from app.html import publish_html
from app.main import create_app
from test_library import upload


def fake_cli(path, fail=False, slow=False):
    path.write_text(f"""#!/usr/bin/env python3
import sys,time,os
from pathlib import Path
if '--help' in sys.argv:
 print('--mode fast --output_format html');sys.exit(0)
assert 'SURYA_INFERENCE_URL' not in os.environ
assert 'DEEPSEEK_API_KEY' not in os.environ
assert os.environ['SURYA_INFERENCE_HOST']=='127.0.0.1'
{"time.sleep(10)" if slow else ""}
{"sys.exit(3)" if fail else ""}
out=Path(sys.argv[sys.argv.index('--output_dir')+1]);out.mkdir(parents=True,exist_ok=True)
(out/'result.html').write_text('<h1>Safe Article</h1><h2>Method</h2><p>Actual fixture paragraph with sufficient text.</p><math display="block">x^2</math><table><tr><td>Safe table</td></tr></table><script>alert(1)</script>')
""")
    path.chmod(0o755)


def wait_job(client, job_id):
    for _ in range(100):
        job = client.get("/api/v1/conversions/" + job_id).json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError("Worker did not finish")


def test_real_subprocess_queue_cache_failure_retry(config, pdf_bytes, tmp_path, monkeypatch):
    monkeypatch.setenv("SURYA_INFERENCE_URL", "https://untrusted-inference.invalid")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "FAKE_KEY_FOR_ENV_BOUNDARY_TEST")
    executable = tmp_path / "fake-marker"
    fake_cli(executable)
    config.marker_executable = str(executable)
    app = create_app(config)
    with TestClient(
        app, base_url="http://127.0.0.1:8000", headers={"Origin": "http://127.0.0.1:8000", "X-PaperFlow": "1"}
    ) as client:
        paper = upload(client, pdf_bytes)
        base = "/api/v1/papers/" + paper["id"]
        first = client.post(base + "/conversions", json={}).json()["job"]
        assert wait_job(client, first["id"])["status"] == "succeeded"
        cached = client.post(base + "/conversions", json={}).json()
        assert cached["cached"] and cached["job"]["id"] == first["id"]
        reader = client.get("/read/" + paper["id"] + "/html")
        assert reader.status_code == 200 and "Safe Article" in reader.text
        assert "<script>alert" not in reader.text
        assert 'translate="no"' in reader.text and "frame-src" in reader.headers["content-security-policy"]
        fake_cli(executable, fail=True)
        failed = client.post(base + "/conversions", json={"force_rebuild": True}).json()["job"]
        assert wait_job(client, failed["id"])["status"] == "failed"
        assert client.get("/read/" + paper["id"] + "/html").status_code == 200
        assert client.get(base + "/pdf").status_code == 200
        fake_cli(executable)
        retry = client.post("/api/v1/conversions/" + failed["id"] + "/retry").json()["job"]
        assert retry["attempt"] == 2
        assert wait_job(client, retry["id"])["status"] == "succeeded"


def test_cancel_and_orphan_recovery(config, pdf_bytes, tmp_path):
    executable = tmp_path / "fake-marker"
    fake_cli(executable, slow=True)
    config.marker_executable = str(executable)
    app = create_app(config)
    headers = {"Origin": "http://127.0.0.1:8000", "X-PaperFlow": "1"}
    with TestClient(app, base_url="http://127.0.0.1:8000", headers=headers) as client:
        paper = upload(client, pdf_bytes)
        job = client.post("/api/v1/papers/" + paper["id"] + "/conversions", json={}).json()["job"]
        time.sleep(0.4)
        assert client.delete("/api/v1/papers/" + paper["id"] + "?confirm=true").status_code == 409
        assert client.post("/api/v1/conversions/" + job["id"] + "/cancel").status_code == 200
        assert wait_job(client, job["id"])["status"] == "canceled"
    with app.state.sessions() as session:
        row = session.get(Job, job["id"])
        row.status = "running"
        session.commit()
    second = create_app(config)
    with TestClient(second, base_url="http://127.0.0.1:8000", headers=headers) as restarted:
        recovered = restarted.get("/api/v1/conversions/" + job["id"]).json()
        assert recovered["status"] == "failed" and recovered["error_code"] == "INTERRUPTED"


def test_sanitize_xss_assets_math(tmp_path):
    from PIL import Image

    raw = tmp_path / "raw"
    raw.mkdir()
    out = tmp_path / "clean"
    Image.new("RGB", (8, 8)).save(raw / "image.png")
    fixture = raw / "article.html"
    fixture.write_text("""<style>body{background:url(file:///etc/passwd)}</style><script>alert(1)</script>
    <h1 onclick="alert(2)">Research</h1><p>Enough readable article text here.</p>
    <img src="image.png" onerror="alert(3)"><a href="javascript:alert(4)">link</a>
    <svg onload="alert(5)"></svg><iframe src="file:///etc/passwd"></iframe>
    <math display="block">x^2+y^2</math><table><tr><td>Value</td></tr></table>""")
    assert publish_html(fixture, out, "id") == 1
    clean = (out / "article.html").read_text()
    for forbidden in ("script", "onclick", "onerror", "javascript:", "file:", "<svg", "<iframe", "<style"):
        assert forbidden not in clean
    assert "<math" in clean and 'translate="no"' in clean and "<table" in clean
    assert "/paper-assets/id/asset-0.png" in clean
    assert json.loads((out / "manifest.json").read_text())["assets"] == {"asset-0.png": "asset-0.png"}
    fixture.write_text('<p>Enough readable article text here.</p><img src="../../outside.png">')
    with pytest.raises(ValueError):
        publish_html(fixture, tmp_path / "bad", "id")
    (raw / "escape.png").symlink_to(tmp_path / "outside.png")
    (tmp_path / "outside.png").write_bytes(b"x")
    fixture.write_text('<p>Enough readable article text here.</p><img src="escape.png">')
    with pytest.raises(ValueError):
        publish_html(fixture, tmp_path / "symlink", "id")
