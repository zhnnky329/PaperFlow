import io
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import Config
from app.main import create_app


@pytest.fixture
def pdf_bytes():
    writer = PdfWriter()
    for _ in range(35):
        writer.add_blank_page(width=595, height=842)
    writer.add_metadata({"/Title": "Test Research", "/Author": "Ada Scientist"})
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def config(tmp_path):
    return Config(
        data_dir=tmp_path / "library", marker_executable="/missing/marker", max_upload_mb=1,
        discovery_online=False,
        deepseek_api_key="",
    )


@pytest.fixture
def app(config):
    return create_app(config)


@pytest.fixture
def client(app):
    with TestClient(
        app, base_url="http://127.0.0.1:8000", headers={"Origin": "http://127.0.0.1:8000", "X-PaperFlow": "1"}
    ) as client:
        yield client
