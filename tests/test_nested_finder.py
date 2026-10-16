"""Nested Finder operations preserve IDs, originals, and filesystem boundaries."""

import json
import shutil
import subprocess

import pytest
from sqlalchemy import delete

from app.db import Setting
from app.folders import Directory, FolderConflict, FolderPending
from test_finder_sync import stable_sync
from test_library import upload


def folders(client):
    return {item["path"]: item for item in client.get("/api/v1/collections").json()}


def create(client, name, parent=None):
    result = client.post("/api/v1/collections", json={"name": name, "parent_id": parent})
    result.raise_for_status()
    return result.json()


def nested_setup(client, app, config, pdf_bytes):
    config.metadata_online = False
    sync = app.state.folder_sync
    sync.stop()
    parent = create(client, "Research")
    child = create(client, "SLAM", parent["id"])
    grandchild = create(client, "Methods", child["id"])
    paper = upload(client, pdf_bytes)
    client.patch(
        "/api/v1/papers/" + paper["id"], json={"collection_ids": [grandchild["id"]]}
    ).raise_for_status()
    sync.sync()
    directory = config.data_dir / "folders/Research/SLAM/Methods"
    return sync, parent, child, grandchild, paper, directory


def test_nested_finder_creation_import_and_same_names(client, app, config, pdf_bytes):
    config.metadata_online = False
    sync = app.state.folder_sync
    sync.stop()
    left = config.data_dir / "folders/Research/SLAM/Methods"
    right = config.data_dir / "folders/Reading/SLAM"
    left.mkdir(parents=True)
    right.mkdir(parents=True)
    (left / "paper.pdf").write_bytes(pdf_bytes)
    (right / "same.pdf").write_bytes(pdf_bytes)
    (left / "notes.txt").write_text("keep this")
    stable_sync(sync)
    groups = folders(client)
    assert set(groups) == {"Research", "Research/SLAM", "Research/SLAM/Methods", "Reading", "Reading/SLAM"}
    assert groups["Research/SLAM"]["parent_id"] == groups["Research"]["id"]
    assert groups["Research"]["paper_count"] == 0
    assert groups["Research/SLAM"]["paper_count"] == 0
    paper = client.get("/api/v1/papers").json()["items"][0]
    assert {row["path"] for row in paper["collections"]} == {"Research/SLAM/Methods", "Reading/SLAM"}
    assert client.get("/api/v1/papers").json()["total"] == 1
    assert (left / "notes.txt").read_text() == "keep this"
    assert sync.manifest(left)["id"] == groups["Research/SLAM/Methods"]["id"]


def test_app_parent_rename_and_cross_parent_move_update_entire_tree(client, app, config, pdf_bytes):
    sync, parent, child, grandchild, paper, directory = nested_setup(client, app, config, pdf_bytes)
    (directory / "notes.txt").write_text("keep")
    copy = next(directory.glob("*.pdf"))
    client.patch("/api/v1/collections/" + parent["id"], json={"name": "Archive"}).raise_for_status()
    sync.sync()
    renamed = config.data_dir / "folders/Archive/SLAM/Methods"
    assert not directory.exists() and (renamed / copy.name).read_bytes() == pdf_bytes
    assert (renamed / "notes.txt").read_text() == "keep"
    other = create(client, "Robotics")
    sync.sync()
    client.patch("/api/v1/collections/" + child["id"], json={"parent_id": other["id"]}).raise_for_status()
    sync.sync()
    moved = config.data_dir / "folders/Robotics/SLAM/Methods"
    assert not renamed.exists() and (moved / copy.name).read_bytes() == pdf_bytes
    assert (moved / "notes.txt").read_text() == "keep"
    assert folders(client)["Robotics/SLAM/Methods"]["id"] == grandchild["id"]
    assert sync.manifest(moved)["name"] == "Robotics/SLAM/Methods"
    assert client.get("/api/v1/papers/" + paper["id"] + "/pdf").content == pdf_bytes
    sync.sync()
    assert len(folders(client)) == 4


def test_finder_parent_rename_and_child_move_preserve_ids(client, app, config, pdf_bytes):
    sync, parent, child, grandchild, paper, directory = nested_setup(client, app, config, pdf_bytes)
    root = config.data_dir / "folders"
    (root / "Research").rename(root / "Renamed")
    sync.sync()
    assert folders(client)["Renamed/SLAM/Methods"]["id"] == grandchild["id"]
    (root / "Renamed/Destination").mkdir()
    (root / "Renamed/SLAM").rename(root / "Renamed/Destination/SLAM")
    sync.sync()
    groups = folders(client)
    assert groups["Renamed/Destination/SLAM"]["id"] == child["id"]
    assert groups["Renamed/Destination/SLAM"]["parent_id"] == groups["Renamed/Destination"]["id"]
    assert groups["Renamed/Destination/SLAM/Methods"]["id"] == grandchild["id"]
    assert client.get("/api/v1/papers").json()["total"] == 1
    sync.sync()


def test_copied_nested_tree_gets_distinct_collection_ids(client, app, config, pdf_bytes):
    sync, parent, child, grandchild, paper, directory = nested_setup(client, app, config, pdf_bytes)
    root = config.data_dir / "folders"
    shutil.copytree(root / "Research", root / "Copy")
    sync.sync()
    groups = folders(client)
    assert groups["Research"]["id"] != groups["Copy"]["id"]
    assert groups["Research/SLAM"]["id"] != groups["Copy/SLAM"]["id"]
    assert groups["Copy/SLAM/Methods"]["parent_id"] == groups["Copy/SLAM"]["id"]
    assert client.get("/api/v1/papers").json()["total"] == 1
    assert {row["path"] for row in client.get("/api/v1/papers/" + paper["id"]).json()["collections"]} == {
        "Research/SLAM/Methods",
        "Copy/SLAM/Methods",
    }


def test_app_parent_delete_preserves_personal_subtree_without_resurrection(client, app, config, pdf_bytes):
    sync, parent, child, grandchild, paper, directory = nested_setup(client, app, config, pdf_bytes)
    copy = next(directory.glob("*.pdf"))
    (directory / "notes.txt").write_text("personal")
    extra = directory / "Unmanaged/Deep"
    extra.mkdir(parents=True)
    (extra / "extra.pdf").write_bytes(pdf_bytes + b"\n% unowned PDF")
    copy.write_bytes(pdf_bytes + b"\n% annotated copy")
    client.delete("/api/v1/collections/" + parent["id"]).raise_for_status()
    for _ in range(3):
        stable_sync(sync)
    assert folders(client) == {}
    assert (directory / "notes.txt").read_text() == "personal"
    assert (extra / "extra.pdf").read_bytes().endswith(b"% unowned PDF")
    assert copy.read_bytes().endswith(b"% annotated copy")
    assert not list((config.data_dir / "folders").rglob(".paperflow.json"))
    assert client.get("/api/v1/papers").json()["total"] == 1
    assert client.get("/api/v1/papers/" + paper["id"]).json()["collections"] == []
    assert client.get("/api/v1/papers/" + paper["id"] + "/pdf").content == pdf_bytes


def test_finder_deletes_parent_but_preserves_moved_descendant(client, app, config, pdf_bytes):
    sync, parent, child, grandchild, paper, directory = nested_setup(client, app, config, pdf_bytes)
    root = config.data_dir / "folders"
    (root / "Research/SLAM").rename(root / "SLAM")
    shutil.rmtree(root / "Research")
    sync.sync()
    groups = folders(client)
    assert set(groups) == {"SLAM", "SLAM/Methods"}
    assert groups["SLAM"]["id"] == child["id"] and groups["SLAM"]["parent_id"] is None
    assert groups["SLAM/Methods"]["id"] == grandchild["id"]
    assert client.get("/api/v1/papers/" + paper["id"] + "/pdf").content == pdf_bytes


def test_nested_symlinks_and_reveal_parent_symlink_are_rejected(
    client, app, config, pdf_bytes, tmp_path, monkeypatch
):
    sync, parent, child, grandchild, paper, directory = nested_setup(client, app, config, pdf_bytes)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.pdf").write_bytes(pdf_bytes)
    link = directory / "linked"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(FolderConflict, match="符号链接"):
        sync.sync()
    link.unlink()
    original_parent = directory.parent
    moved_parent = original_parent.with_name("Saved")
    original_parent.rename(moved_parent)
    original_parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(FolderConflict, match="符号链接"):
        sync.manifest(directory)
    opened = []
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: opened.append(args))
    assert client.post("/api/v1/collections/" + grandchild["id"] + "/reveal").status_code in (409, 422)
    assert opened == []
    assert (outside / "secret.pdf").read_bytes() == pdf_bytes
    assert list(outside.iterdir()) == [outside / "secret.pdf"]


def test_nested_handle_chain_detects_ancestor_replacement(tmp_path):
    root = tmp_path / "root"
    (root / "A/B/C").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    with Directory(str(root)) as opened_root, Directory("A", opened_root) as a:
        with Directory("B", a) as b, Directory("C", b) as c:
            (root / "A").rename(root / "Saved")
            (root / "A").symlink_to(outside, target_is_directory=True)
            with pytest.raises(FolderPending):
                c.write_manifest({"id": "anything", "files": {}})
    assert not list(outside.iterdir())


def test_legacy_root_baseline_upgrades_without_membership_loss(client, app, config, pdf_bytes):
    config.metadata_online = False
    sync = app.state.folder_sync
    sync.stop()
    root = create(client, "Legacy")
    paper = upload(client, pdf_bytes)
    client.patch("/api/v1/papers/" + paper["id"], json={"collection_ids": [root["id"]]}).raise_for_status()
    sync.sync()
    with app.state.sessions() as session:
        baseline = session.get(Setting, "folder_sync_baseline")
        old = json.loads(json.dumps(baseline.value))
        for record in old["folders"].values():
            record.pop("parent_id", None)
        baseline.value = old
        session.commit()
    folder = config.data_dir / "folders/Legacy"
    data = json.loads((folder / ".paperflow.json").read_text())
    data.pop("parent_id")
    (folder / ".paperflow.json").write_text(json.dumps(data))
    sync.sync()
    assert folders(client)["Legacy"]["id"] == root["id"]
    create(client, "New Child", root["id"])
    sync.sync()
    assert (folder / "New Child/.paperflow.json").exists()
    assert client.get("/api/v1/papers/" + paper["id"]).json()["collections"][0]["id"] == root["id"]


def test_nested_missing_copy_upgrade_is_conservative(client, app, config, pdf_bytes):
    sync, parent, child, grandchild, paper, directory = nested_setup(client, app, config, pdf_bytes)
    with app.state.sessions() as session:
        session.execute(delete(Setting).where(Setting.key == "folder_sync_baseline"))
        session.commit()
    copy = next(directory.glob("*.pdf"))
    copy.unlink()
    sync.sync()
    assert copy.read_bytes() == pdf_bytes
    assert client.get("/api/v1/papers/" + paper["id"]).json()["collections"][0]["id"] == grandchild["id"]


def test_app_moves_child_then_deletes_parent_before_worker_runs(client, app, config, pdf_bytes):
    sync, parent, child, grandchild, paper, directory = nested_setup(client, app, config, pdf_bytes)
    (directory / "notes.txt").write_text("keep moved notes")
    extra = directory / "New Subfolder"
    extra.mkdir()
    client.patch("/api/v1/collections/" + child["id"], json={"parent_id": None}).raise_for_status()
    client.delete("/api/v1/collections/" + parent["id"]).raise_for_status()
    sync.sync()
    sync.sync()
    moved = config.data_dir / "folders/SLAM/Methods"
    assert next(moved.glob("*.pdf")).read_bytes() == pdf_bytes
    assert (moved / "notes.txt").read_text() == "keep moved notes"
    assert folders(client)["SLAM/Methods"]["id"] == grandchild["id"]
    assert folders(client)["SLAM/Methods/New Subfolder"]["parent_id"] == grandchild["id"]
    assert client.get("/api/v1/papers/" + paper["id"]).json()["collections"][0]["id"] == grandchild["id"]


def test_app_deletes_only_child_and_removes_owned_subtree(client, app, config, pdf_bytes):
    sync, parent, child, grandchild, paper, directory = nested_setup(client, app, config, pdf_bytes)
    client.delete("/api/v1/collections/" + child["id"]).raise_for_status()
    sync.sync()
    sync.sync()
    assert set(folders(client)) == {"Research"}
    assert not directory.parent.exists()
    assert (config.data_dir / "folders/Research/.paperflow.json").exists()
    assert client.get("/api/v1/papers/" + paper["id"] + "/pdf").content == pdf_bytes


def test_finder_parent_rename_keeps_preserved_copy_and_deleted_child_suppressed(
    client, app, config, pdf_bytes
):
    sync, parent, child, grandchild, paper, directory = nested_setup(client, app, config, pdf_bytes)
    copy = next(directory.glob("*.pdf"))
    renamed = directory / "custom.pdf"
    copy.rename(renamed)
    client.patch("/api/v1/papers/" + paper["id"], json={"collection_ids": []}).raise_for_status()
    sync.sync()
    assert renamed.exists()
    (directory / "notes.txt").write_text("private notes")
    client.delete("/api/v1/collections/" + grandchild["id"]).raise_for_status()
    sync.sync()
    assert directory.is_dir() and not (directory / ".paperflow.json").exists()
    root = config.data_dir / "folders"
    (root / "Research").rename(root / "Renamed")
    for _ in range(2):
        sync.sync()
    assert set(folders(client)) == {"Renamed", "Renamed/SLAM"}
    assert client.get("/api/v1/papers/" + paper["id"]).json()["collections"] == []
    assert (root / "Renamed/SLAM/Methods/custom.pdf").read_bytes() == pdf_bytes
    assert (root / "Renamed/SLAM/Methods/notes.txt").read_text() == "private notes"


def test_finder_rename_preserves_unfiled_custom_copy_without_reclassifying(client, app, config, pdf_bytes):
    sync, parent, child, grandchild, paper, directory = nested_setup(client, app, config, pdf_bytes)
    next(directory.glob("*.pdf")).rename(directory / "custom.pdf")
    client.patch("/api/v1/papers/" + paper["id"], json={"collection_ids": []}).raise_for_status()
    sync.sync()
    root = config.data_dir / "folders"
    (root / "Research").rename(root / "Renamed")
    sync.sync()
    sync.sync()
    assert client.get("/api/v1/papers/" + paper["id"]).json()["collections"] == []
    assert (root / "Renamed/SLAM/Methods/custom.pdf").exists()


def test_deleted_child_residue_stays_suppressed_when_app_renames_parent(client, app, config, pdf_bytes):
    sync, parent, child, grandchild, paper, directory = nested_setup(client, app, config, pdf_bytes)
    (directory / "notes.txt").write_text("keep")
    client.delete("/api/v1/collections/" + child["id"]).raise_for_status()
    client.patch("/api/v1/collections/" + parent["id"], json={"name": "Archive"}).raise_for_status()
    for _ in range(3):
        sync.sync()
    assert set(folders(client)) == {"Archive"}
    assert (config.data_dir / "folders/Archive/SLAM/Methods/notes.txt").read_text() == "keep"
    assert client.get("/api/v1/papers/" + paper["id"]).json()["collections"] == []


def test_nested_folder_with_pdf_suffix_is_a_directory_not_a_pdf(client, app, config, pdf_bytes):
    config.metadata_online = False
    sync = app.state.folder_sync
    sync.stop()
    parent = create(client, "Research")
    child = create(client, "Papers.pdf", parent["id"])
    sync.sync()
    sync.sync()
    directory = config.data_dir / "folders/Research/Papers.pdf"
    (directory / "paper.pdf").write_bytes(pdf_bytes)
    stable_sync(sync)
    assert folders(client)["Research/Papers.pdf"]["id"] == child["id"]
    paper = client.get("/api/v1/papers").json()["items"][0]
    assert paper["collections"][0]["id"] == child["id"]
