"""A stopped backup preserves nested memberships and offline Finder moves."""

from fastapi.testclient import TestClient

from app.main import create_app
from test_backup import module
from test_folders import eventually
from test_library import upload


def test_nested_backup_restore_then_offline_finder_move(config, pdf_bytes, tmp_path):
    config.metadata_online = False
    headers = {"Origin": "http://127.0.0.1:8000", "X-PaperFlow": "1"}
    with TestClient(create_app(config), base_url="http://127.0.0.1:8000", headers=headers) as client:
        parent = client.post("/api/v1/collections", json={"name": "Research"}).json()
        child = client.post(
            "/api/v1/collections", json={"name": "SLAM", "parent_id": parent["id"]}
        ).json()
        paper = upload(client, pdf_bytes)
        endpoint = "/api/v1/papers/" + paper["id"]
        assert client.patch(endpoint, json={"collection_ids": [child["id"]]}).status_code == 200
        client.put(endpoint + "/reading-position?mode=pdf", json={"pdf_page": 7, "pdf_scale": 1.2})
        directory = config.data_dir / "folders/Research/SLAM"
        eventually(lambda: bool(list(directory.glob("*.pdf"))))
        (directory / "notes.txt").write_text("Keep this research note")

    archive = module.backup(config.data_dir, tmp_path / "nested.zip")
    restored = module.restore(archive, tmp_path / "restored-nested")
    methods = restored / "folders/Research/Methods"
    methods.mkdir()
    (restored / "folders/Research/SLAM").rename(methods / "SLAM")
    assert (methods / "SLAM/notes.txt").read_text() == "Keep this research note"
    restored_config = config.model_copy(update={"data_dir": restored})
    with TestClient(create_app(restored_config), base_url="http://127.0.0.1:8000", headers=headers) as client:
        def moved():
            groups = client.get(endpoint).json()["collections"]
            return len(groups) == 1 and groups[0].get("path") == "Research/Methods/SLAM"

        eventually(moved)
        groups = client.get("/api/v1/collections").json()
        paths = {group["path"]: group for group in groups}
        assert paths["Research/Methods/SLAM"]["id"] == child["id"]
        assert paths["Research/Methods/SLAM"]["parent_id"] == paths["Research/Methods"]["id"]
        assert client.get(endpoint + "/pdf").content == pdf_bytes
        assert client.get(endpoint + "/reading-position?mode=pdf").json()["pdf_page"] == 7
        assert client.get("/api/v1/papers").json()["total"] == 1
        assert client.patch(
            "/api/v1/collections/" + parent["id"], json={"name": "Research Archive"}
        ).status_code == 200
        renamed = restored / "folders/Research Archive/Methods/SLAM"
        eventually(lambda: bool(list(renamed.glob("*.pdf"))))
        assert (renamed / "notes.txt").read_text() == "Keep this research note"
