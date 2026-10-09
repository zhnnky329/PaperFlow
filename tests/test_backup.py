import importlib.util
from pathlib import Path
import zipfile
import pytest
from test_library import upload
from test_folders import eventually

spec = importlib.util.spec_from_file_location(
    "backup", Path(__file__).resolve().parents[1] / "scripts/backup.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_backup_requires_stop_and_recovers_assets(app, config, pdf_bytes, tmp_path):
    from fastapi.testclient import TestClient

    with TestClient(
        app, base_url="http://127.0.0.1:8000", headers={"Origin": "http://127.0.0.1:8000", "X-PaperFlow": "1"}
    ) as client:
        paper = upload(client, pdf_bytes)
        client.patch("/api/v1/papers/" + paper["id"], json={"collections": ["BackupFolder"]})
        folder = config.data_dir / "folders/BackupFolder"
        eventually(lambda: bool(list(folder.glob("*.pdf"))))
        (folder / "note.txt").write_text("User note")
        with pytest.raises(ValueError, match="Stop"):
            module.backup(config.data_dir, tmp_path / "running.zip")
    archive = module.backup(config.data_dir, tmp_path / "backup.zip")
    target = module.restore(archive, tmp_path / "restored")
    assert (target / "papers" / paper["id"] / "original.pdf").read_bytes() == pdf_bytes
    assert next((target / "folders/BackupFolder").glob("*.pdf")).read_bytes() == pdf_bytes
    assert (target / "folders/BackupFolder/note.txt").read_text() == "User note"
    import sqlite3

    with sqlite3.connect(target / "paperflow.sqlite3") as db:
        assert db.execute("SELECT title FROM papers").fetchone()[0] == "Test Research"
    with pytest.raises(ValueError, match="existing"):
        module.restore(archive, target)


def test_restore_rejects_zip_slip(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../../escape", "bad")
    with pytest.raises(ValueError, match="Unsafe"):
        module.restore(archive, tmp_path / "restored")
