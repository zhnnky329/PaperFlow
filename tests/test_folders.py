import time
from fastapi.testclient import TestClient
from app.main import create_app
from test_library import upload


def eventually(check):
    for _ in range(350):
        if check():
            return
        time.sleep(0.03)
    assert check(), "Folder synchronization did not reach expected state"


def test_folder_copy_rename_unfiled_and_restart(client, config, pdf_bytes):
    paper = upload(client, pdf_bytes)
    folder = client.post("/api/v1/collections", json={"name": "SLAM"}).json()
    other = client.post("/api/v1/collections", json={"name": "路径规划, Planning"}).json()
    assert client.post("/api/v1/collections", json={"name": "slam"}).json()["id"] == folder["id"]
    endpoint = "/api/v1/papers/" + paper["id"]
    assert client.patch(endpoint, json={"collections": ["SLAM", other["name"]]}).status_code == 200
    first = config.data_dir / "folders/SLAM"
    second = config.data_dir / "folders" / other["name"]
    eventually(lambda: len(list(first.glob("*.pdf"))) == len(list(second.glob("*.pdf"))) == 1)
    copy = next(first.glob("*.pdf"))
    assert copy.read_bytes() == pdf_bytes
    canonical = config.path("papers/" + paper["id"] + "/original.pdf")
    assert copy.stat().st_ino != canonical.stat().st_ino  # independent, never hard linked
    counts = {r["id"]: r["paper_count"] for r in client.get("/api/v1/collections").json()}
    assert counts[folder["id"]] == counts[other["id"]] == 1
    assert client.get("/api/v1/papers?unfiled=true").json()["total"] == 0
    assert (
        client.patch("/api/v1/collections/" + folder["id"], json={"name": "机器人 SLAM"}).json()["name"]
        == "机器人 SLAM"
    )
    renamed = config.data_dir / "folders/机器人 SLAM"
    eventually(lambda: renamed.is_dir() and not first.exists())
    assert next(renamed.glob("*.pdf")).read_bytes() == pdf_bytes
    assert (
        client.patch("/api/v1/collections/" + folder["id"], json={"name": other["name"]}).status_code == 409
    )
    assert client.patch(endpoint, json={"collections": []}).status_code == 200
    eventually(lambda: not list(renamed.glob("*.pdf")) and not list(second.glob("*.pdf")))
    assert client.get("/api/v1/papers?unfiled=true").json()["total"] == 1
    assert canonical.read_bytes() == pdf_bytes


def test_folder_restart_detaches_removed_copy_and_keeps_original(config, pdf_bytes):
    headers = {"Origin": "http://127.0.0.1:8000", "X-PaperFlow": "1"}
    with TestClient(create_app(config), base_url="http://127.0.0.1:8000", headers=headers) as client:
        paper = upload(client, pdf_bytes)
        client.patch("/api/v1/papers/" + paper["id"], json={"collections": ["恢复测试"]})
        folder = config.data_dir / "folders/恢复测试"
        eventually(lambda: bool(list(folder.glob("*.pdf"))))
    next(folder.glob("*.pdf")).unlink()
    with TestClient(create_app(config), base_url="http://127.0.0.1:8000", headers=headers) as restarted:
        eventually(lambda: restarted.get("/api/v1/papers/" + paper["id"]).json()["collections"] == [])
        assert not list(folder.glob("*.pdf"))
        assert restarted.get("/api/v1/papers/" + paper["id"] + "/pdf").content == pdf_bytes


def test_folder_rejects_paths_and_preserves_external_content(client, config, pdf_bytes):
    for name in ("../escape", "a/b", "a\\b", ".hidden", "a:b"):
        assert client.post("/api/v1/collections", json={"name": name}).status_code == 422
    paper = upload(client, pdf_bytes)
    client.patch("/api/v1/papers/" + paper["id"], json={"collections": ["My Research"]})
    folder = config.data_dir / "folders/My Research"
    eventually(lambda: bool(list(folder.glob("*.pdf"))))
    copy = next(folder.glob("*.pdf"))
    copy.write_bytes(pdf_bytes + b"\n% user annotation")
    note = folder / "personal-note.txt"
    note.write_text("keep this")
    row = client.get("/api/v1/collections").json()[0]
    client.delete("/api/v1/collections/" + row["id"])
    eventually(lambda: not (folder / ".paperflow.json").exists())
    assert copy.read_bytes().endswith(b"% user annotation") and note.read_text() == "keep this"
    assert config.path("papers/" + paper["id"] + "/original.pdf").read_bytes() == pdf_bytes


def test_folder_sync_failure_retry_and_symlink_boundary(client, config, tmp_path, pdf_bytes):
    root = config.data_dir / "folders"
    root.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("untouched")
    (root / "Collision").symlink_to(outside, target_is_directory=True)
    client.post("/api/v1/collections", json={"name": "Collision"})
    eventually(lambda: client.get("/api/v1/settings").json()["folder_sync"]["status"] == "failed")
    assert list(outside.iterdir()) == [outside / "keep"]
    assert client.get("/api/v1/health").status_code == 200
    (root / "Collision").unlink()
    assert client.post("/api/v1/collections/sync").status_code == 200
    eventually(lambda: (root / "Collision/.paperflow.json").is_file())
    assert (outside / "keep").read_text() == "untouched"
    paper = upload(client, pdf_bytes)
    client.patch("/api/v1/papers/" + paper["id"], json={"collections": ["Collision"]})
    directory = root / "Collision"
    eventually(lambda: bool(list(directory.glob("*.pdf"))))
    copy = next(directory.glob("*.pdf"))
    copy.unlink()
    copy.symlink_to(outside / "keep")
    client.post("/api/v1/collections/sync")
    eventually(lambda: client.get("/api/v1/settings").json()["folder_sync"]["status"] == "failed")
    assert (outside / "keep").read_text() == "untouched"
    assert client.get("/api/v1/papers/" + paper["id"] + "/pdf").content == pdf_bytes
    copy.unlink()
    client.post("/api/v1/collections/sync")
    eventually(lambda: client.get("/api/v1/papers/" + paper["id"]).json()["collections"] == [])
    assert client.get("/api/v1/papers/" + paper["id"] + "/pdf").content == pdf_bytes
    # A symlinked root must not break Library or reveal an outside directory.
    saved_root = root.with_name("folders-saved")
    root.rename(saved_root)
    root.symlink_to(outside, target_is_directory=True)
    client.post("/api/v1/collections/sync")
    eventually(lambda: client.get("/api/v1/settings").json()["folder_sync"]["status"] == "failed")
    assert client.get("/api/v1/collections").status_code == 200
    assert client.get("/api/v1/papers").status_code == 200
    row = client.get("/api/v1/collections").json()[0]
    assert client.post("/api/v1/collections/" + row["id"] + "/reveal").status_code == 422
    assert list(outside.iterdir()) == [outside / "keep"]
    root.unlink()
    saved_root.rename(root)
