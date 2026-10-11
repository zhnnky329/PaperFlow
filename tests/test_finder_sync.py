"""Real filesystem changes, isolated SQLite, and the production sync worker."""

import json
import shutil
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import Setting, uid
from app.folders import Directory, FolderConflict, FolderPending
from app.main import create_app
from test_folders import eventually
from test_library import upload


def membership(client, paper_id):
    return {c["name"] for c in client.get("/api/v1/papers/" + paper_id).json()["collections"]}


def paused_folder(client, app, config, pdf_bytes):
    paper = upload(client, pdf_bytes)
    client.patch("/api/v1/papers/" + paper["id"], json={"collections": ["Original"]}).raise_for_status()
    folder = config.data_dir / "folders/Original"
    eventually(lambda: bool(list(folder.glob("*.pdf"))))
    app.state.folder_sync.stop()
    app.state.folder_sync.sync()
    return paper, folder, next(folder.glob("*.pdf")), app.state.folder_sync


def stable_sync(sync):
    try:
        sync.sync()
    except FolderPending:
        time.sleep(0.6)
        sync.sync()


def test_finder_import_copy_and_rename_are_automatic(client, app, config, pdf_bytes):
    config.metadata_online = False
    first = config.data_dir / "folders/Finder Import"
    first.mkdir(parents=True)
    incoming = first / "my name.PDF"
    incoming.write_bytes(pdf_bytes)
    (first / "note.txt").write_text("keep")
    eventually(lambda: client.get("/api/v1/papers").json()["total"] == 1)
    paper = client.get("/api/v1/papers").json()["items"][0]
    eventually(lambda: membership(client, paper["id"]) == {"Finder Import"})
    eventually(lambda: client.get("/api/v1/papers/" + paper["id"]).json()["metadata_status"] == "local")
    canonical = config.path(f"papers/{paper['id']}/original.pdf")
    assert canonical.read_bytes() == pdf_bytes and canonical.stat().st_ino != incoming.stat().st_ino
    second = first.with_name("Finder Copy")
    second.mkdir()
    shutil.copy2(incoming, second / "copy.pdf")
    eventually(lambda: membership(client, paper["id"]) == {"Finder Import", "Finder Copy"})
    incoming.rename(first / "renamed.pdf")
    first.rename(first.with_name("重命名文件夹"))
    eventually(lambda: membership(client, paper["id"]) == {"重命名文件夹", "Finder Copy"})
    assert (first.with_name("重命名文件夹") / "renamed.pdf").read_bytes() == pdf_bytes
    assert client.get("/api/v1/papers").json()["total"] == 1
    assert client.get("/api/v1/papers/" + paper["id"]).json()["title"] == "Test Research"


def test_finder_move_delete_and_folder_delete_keep_original_and_progress(client, app, config, pdf_bytes):
    paper, first, copy, sync = paused_folder(client, app, config, pdf_bytes)
    endpoint = "/api/v1/papers/" + paper["id"]
    client.put(endpoint + "/reading-position?mode=pdf", json={"pdf_page": 7, "pdf_scale": 1.2})
    second = first.with_name("Moved")
    second.mkdir()
    moved = second / "a readable name.pdf"
    copy.rename(moved)
    sync.sync()
    assert membership(client, paper["id"]) == {"Moved"}
    assert not list(first.glob("*.pdf")) and moved.read_bytes() == pdf_bytes
    moved.unlink()
    sync.sync()
    assert membership(client, paper["id"]) == set()
    assert client.get(endpoint + "/pdf").content == pdf_bytes
    assert client.get(endpoint + "/reading-position?mode=pdf").json()["pdf_page"] == 7
    shutil.rmtree(second)
    sync.sync()
    assert "Moved" not in {c["name"] for c in client.get("/api/v1/collections").json()}
    assert client.get(endpoint).status_code == 200


def test_offline_finder_edits_are_reconciled_on_restart(config, pdf_bytes):
    config.metadata_online = False
    headers = {"Origin": "http://127.0.0.1:8000", "X-PaperFlow": "1"}
    with TestClient(create_app(config), base_url="http://127.0.0.1:8000", headers=headers) as client:
        paper = upload(client, pdf_bytes)
        client.patch("/api/v1/papers/" + paper["id"], json={"collections": ["Before"]})
        first = config.data_dir / "folders/Before"
        eventually(lambda: bool(list(first.glob("*.pdf"))))
        folder_id = client.get("/api/v1/collections").json()[0]["id"]
    first.rename(first.with_name("After"))
    first = first.with_name("After")
    next(first.glob("*.pdf")).rename(first / "offline name.pdf")
    (first / "additional.pdf").write_bytes(pdf_bytes + b"\n% another PDF")
    with TestClient(create_app(config), base_url="http://127.0.0.1:8000", headers=headers) as client:
        eventually(lambda: client.get("/api/v1/papers").json()["total"] == 2)
        eventually(lambda: membership(client, paper["id"]) == {"After"})
        assert client.get("/api/v1/collections").json()[0]["id"] == folder_id
        assert (first / "offline name.pdf").exists()


def test_modified_pdf_conflict_can_be_resolved_as_separate_paper(client, app, config, pdf_bytes):
    paper, folder, copy, sync = paused_folder(client, app, config, pdf_bytes)
    modified = pdf_bytes + b"\n% annotations"
    copy.write_bytes(modified)
    with pytest.raises(FolderConflict, match="内容已修改"):
        sync.sync()
    assert client.get("/api/v1/papers/" + paper["id"] + "/pdf").content == pdf_bytes
    assert copy.read_bytes() == modified and membership(client, paper["id"]) == {"Original"}
    copy.rename(folder / "annotated.pdf")
    stable_sync(sync)
    assert client.get("/api/v1/papers").json()["total"] == 2
    assert membership(client, paper["id"]) == set()
    assert (folder / "annotated.pdf").read_bytes() == modified


def test_conflicting_renames_preserve_both_sides_until_resolved(client, app, config, pdf_bytes):
    paper, folder, copy, sync = paused_folder(client, app, config, pdf_bytes)
    folder_id = client.get("/api/v1/collections").json()[0]["id"]
    client.patch("/api/v1/collections/" + folder_id, json={"name": "App Name"})
    folder.rename(folder.with_name("Finder Name"))
    with pytest.raises(FolderConflict, match="同时改名"):
        sync.sync()
    assert membership(client, paper["id"]) == {"App Name"}
    assert (folder.with_name("Finder Name") / copy.name).read_bytes() == pdf_bytes
    folder.with_name("Finder Name").rename(folder)
    sync.sync()
    assert folder.with_name("App Name").is_dir() and not folder.exists()


def test_app_removal_and_paper_deletion_do_not_resurrect_from_renamed_copy(client, app, config, pdf_bytes):
    paper, folder, copy, sync = paused_folder(client, app, config, pdf_bytes)
    renamed = folder / "custom.pdf"
    copy.rename(renamed)
    client.patch("/api/v1/papers/" + paper["id"], json={"collections": []})
    sync.sync()
    sync.sync()
    assert membership(client, paper["id"]) == set() and renamed.exists()
    client.delete("/api/v1/papers/" + paper["id"] + "?confirm=true").raise_for_status()
    sync.sync()
    sync.sync()
    assert client.get("/api/v1/papers").json()["total"] == 0 and renamed.exists()


def test_app_deleted_folder_residue_is_preserved_without_reimport(client, app, config, pdf_bytes):
    paper, folder, copy, sync = paused_folder(client, app, config, pdf_bytes)
    copy.write_bytes(pdf_bytes + b"\n% changed copy")
    (folder / "note.txt").write_text("keep")
    folder_id = client.get("/api/v1/collections").json()[0]["id"]
    client.delete("/api/v1/collections/" + folder_id).raise_for_status()
    sync.sync()
    sync.sync()
    assert copy.exists() and (folder / "note.txt").read_text() == "keep"
    assert client.get("/api/v1/collections").json() == []
    assert client.get("/api/v1/papers").json()["total"] == 1
    assert membership(client, paper["id"]) == set()


def test_duplicate_whole_finder_folder_creates_new_classification(client, app, config, pdf_bytes):
    paper, folder, copy, sync = paused_folder(client, app, config, pdf_bytes)
    duplicate = folder.with_name("Duplicated")
    shutil.copytree(folder, duplicate)
    sync.sync()
    assert membership(client, paper["id"]) == {"Original", "Duplicated"}
    assert client.get("/api/v1/papers").json()["total"] == 1
    assert (
        json.loads((folder / ".paperflow.json").read_text())["id"]
        != json.loads((duplicate / ".paperflow.json").read_text())["id"]
    )


def test_old_manifest_upgrade_recreates_missing_copy_conservatively(client, app, config, pdf_bytes):
    paper, folder, copy, sync = paused_folder(client, app, config, pdf_bytes)
    manifest = folder / ".paperflow.json"
    data = json.loads(manifest.read_text())
    manifest.write_text(json.dumps({"id": data["id"], "files": data["files"]}))
    with app.state.sessions() as session:
        session.execute(delete(Setting).where(Setting.key == "folder_sync_baseline"))
        session.commit()
    copy.unlink()
    sync.sync()
    assert copy.read_bytes() == pdf_bytes and membership(client, paper["id"]) == {"Original"}


def test_interrupted_publication_retries_without_detaching_app_membership(
    client, app, config, pdf_bytes, monkeypatch
):
    paper, folder, copy, sync = paused_folder(client, app, config, pdf_bytes)
    client.post("/api/v1/collections", json={"name": "Target"})
    sync.sync()
    client.patch("/api/v1/papers/" + paper["id"], json={"collections": ["Original", "Target"]})
    publish = sync.publish
    monkeypatch.setattr(sync, "publish", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        sync.sync()
    monkeypatch.setattr(sync, "publish", publish)
    sync.sync()
    assert membership(client, paper["id"]) == {"Original", "Target"}
    assert next((folder.with_name("Target")).glob("*.pdf")).read_bytes() == pdf_bytes


@pytest.mark.parametrize("kind", ["invalid", "oversized", "symlink", "fifo"])
def test_finder_rejects_unsafe_inputs_without_touching_original(
    client, app, config, pdf_bytes, tmp_path, kind
):
    paper, folder, copy, sync = paused_folder(client, app, config, pdf_bytes)
    incoming = folder / "unsafe.pdf"
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(pdf_bytes)
    if kind == "symlink":
        incoming.symlink_to(outside)
    elif kind == "fifo":
        import os

        os.mkfifo(incoming)
    else:
        incoming.write_bytes(b"x" * (1_048_577 if kind == "oversized" else 20))
    with pytest.raises(FolderConflict):
        stable_sync(sync)
    assert outside.read_bytes() == pdf_bytes and copy.read_bytes() == pdf_bytes
    assert client.get("/api/v1/papers").json()["total"] == 1


def test_missing_root_does_not_remove_classifications(client, app, config, pdf_bytes):
    paper, folder, copy, sync = paused_folder(client, app, config, pdf_bytes)
    root = folder.parent
    root.rename(root.with_name("temporarily moved"))
    with pytest.raises(FolderConflict, match="根目录已移走"):
        sync.sync()
    assert membership(client, paper["id"]) == {"Original"}
    root.with_name("temporarily moved").rename(root)
    sync.sync()
    assert copy.read_bytes() == pdf_bytes


def test_directory_replaced_by_symlink_is_not_followed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    folder = root / "folder"
    folder.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with Directory(str(root)) as base, Directory("folder", base) as opened:
        folder.rename(root / "moved")
        folder.symlink_to(outside, target_is_directory=True)
        with pytest.raises(FolderPending):
            opened.write_manifest({"id": "anything", "files": {}})
    assert list(outside.iterdir()) == []


def test_foreign_managed_folder_is_imported_without_deleting_files(client, app, config, pdf_bytes):
    import hashlib

    app.state.folder_sync.stop()
    folder = config.data_dir / "folders/From Another Library"
    folder.mkdir(parents=True)
    (folder / "public.pdf").write_bytes(pdf_bytes)
    (folder / ".paperflow.json").write_text(
        json.dumps(
            {
                "id": uid(),
                "files": {"public.pdf": hashlib.sha256(pdf_bytes).hexdigest()},
                "papers": {"public.pdf": uid()},
            }
        )
    )
    stable_sync(app.state.folder_sync)
    assert (folder / "public.pdf").read_bytes() == pdf_bytes
    assert client.get("/api/v1/papers").json()["total"] == 1
    assert client.get("/api/v1/collections").json()[0]["name"] == "From Another Library"


def test_copy_replaced_during_cleanup_is_preserved(client, app, config, pdf_bytes, monkeypatch):
    paper, folder, copy, sync = paused_folder(client, app, config, pdf_bytes)
    client.patch("/api/v1/papers/" + paper["id"], json={"collections": []})
    original_read = Directory.read
    modified = pdf_bytes + b"\n% user edited during cleanup"

    def replace_after_read(directory, name, limit):
        contents = original_read(directory, name, limit)
        if directory.name == "Original" and name == copy.name:
            copy.write_bytes(modified)
        return contents

    monkeypatch.setattr(Directory, "read", replace_after_read)
    with pytest.raises(FolderPending):
        sync.sync()
    assert copy.read_bytes() == modified
    monkeypatch.setattr(Directory, "read", original_read)
    sync.sync()
    sync.sync()
    assert copy.read_bytes() == modified and membership(client, paper["id"]) == set()


def test_idle_sync_does_not_reread_unchanged_or_preserved_pdf_copies(
    client, app, config, pdf_bytes, monkeypatch
):
    paper, folder, copy, sync = paused_folder(client, app, config, pdf_bytes)
    copy.rename(folder / "custom.pdf")
    client.patch("/api/v1/papers/" + paper["id"], json={"collections": []})
    sync.sync()
    sync.sync()
    original_read = Directory.read

    def reject_pdf_read(directory, name, limit):
        assert not name.lower().endswith(".pdf"), "Idle polling reread an unchanged PDF"
        return original_read(directory, name, limit)

    monkeypatch.setattr(Directory, "read", reject_pdf_read)
    sync.sync()
    assert (folder / "custom.pdf").exists() and membership(client, paper["id"]) == set()
