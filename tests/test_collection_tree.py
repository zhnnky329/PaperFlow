from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import IntegrityError

from app.collection_tree import MAX_COLLECTION_DEPTH, collection_descendants, collection_path
from app.config import ROOT
from app.db import Collection, Paper, Position, paper_collections, uid
from app.main import create_app


@pytest.fixture
def tree_client(config):
    app = create_app(config)
    # These API tests deliberately leave the background Finder worker stopped.
    # Finder filesystem reconciliation has its own integration coverage.
    client = TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        headers={"Origin": "http://127.0.0.1:8000", "X-PaperFlow": "1"},
    )
    yield client
    client.close()
    app.state.sessions.kw["bind"].dispose()


def create_folder(client, name, parent=None):
    response = client.post("/api/v1/collections", json={"name": name, "parent_id": parent})
    assert response.status_code == 200, response.text
    return response.json()


def test_listing_uses_one_tree_snapshot_during_concurrent_delete(tree_client):
    parent = create_folder(tree_client, "Parent")
    create_folder(tree_client, "Child", parent["id"])
    engine = tree_client.app.state.sessions.kw["bind"]
    deleted = False

    def remove_after_tree_read(connection, cursor, statement, parameters, context, executemany):
        nonlocal deleted
        if not deleted and statement.startswith("SELECT collections."):
            deleted = True
            with engine.begin() as other:
                other.execute(text("DELETE FROM collections WHERE id=:id"), {"id": parent["id"]})

    event.listen(engine, "after_cursor_execute", remove_after_tree_read)
    try:
        response = tree_client.get("/api/v1/collections")
        assert deleted
        assert response.status_code == 200, response.text
        assert {row["path"] for row in response.json()} == {"Parent", "Parent/Child"}
        assert tree_client.get("/api/v1/collections").json() == []
    finally:
        event.remove(engine, "after_cursor_execute", remove_after_tree_read)


def insert_paper(client, config, pdf_bytes):
    paper_id = uid()
    relative = f"papers/{paper_id}/original.pdf"
    path = config.path(relative)
    path.parent.mkdir(parents=True)
    path.write_bytes(pdf_bytes)
    with client.app.state.sessions() as session:
        session.add(Paper(id=paper_id, title="Preserved paper", pdf_path=relative))
        session.add(Position(paper_id=paper_id, mode="pdf", pdf_page=8, pdf_scale=1.25))
        session.commit()
    return paper_id


def test_nested_folders_names_paths_and_counts(tree_client):
    client = tree_client
    root = create_folder(client, "Robotics")
    other = create_folder(client, "Vision")
    first = create_folder(client, "Straße", root["id"])
    duplicate = create_folder(client, "STRASSE", root["id"])
    second = create_folder(client, "Straße", other["id"])
    assert first["id"] == duplicate["id"] != second["id"]
    assert first == {
        "id": first["id"],
        "name": "Straße",
        "parent_id": root["id"],
        "path": "Robotics/Straße",
        "depth": 1,
    }
    rows = {row["id"]: row for row in client.get("/api/v1/collections").json()}
    assert rows[first["id"]]["paper_count"] == 0
    assert Path(rows[first["id"]]["folder_path"]).parts[-2:] == ("Robotics", "Straße")
    sibling = create_folder(client, "Mapping", root["id"])
    collision = client.patch("/api/v1/collections/" + sibling["id"], json={"name": "STRASSE"})
    assert collision.status_code == 409
    collision = client.patch("/api/v1/collections/" + second["id"], json={"parent_id": root["id"]})
    assert collision.status_code == 409
    with client.app.state.sessions() as session:
        session.add(Collection(id=uid(), name="STRASSE", parent_id=root["id"]))
        with pytest.raises(IntegrityError):
            session.commit()


def test_move_subtree_root_cycle_and_depth_limits(tree_client):
    client = tree_client
    root = create_folder(client, "Root")
    child = create_folder(client, "Child", root["id"])
    leaf = create_folder(client, "Leaf", child["id"])
    for invalid in (root["id"], child["id"], leaf["id"]):
        assert (
            client.patch("/api/v1/collections/" + root["id"], json={"parent_id": invalid}).status_code == 422
        )
    assert (
        client.post("/api/v1/collections", json={"name": "Missing", "parent_id": str(uuid4())}).status_code
        == 422
    )
    assert (
        client.patch("/api/v1/collections/" + root["id"], json={"parent_id": str(uuid4())}).status_code == 422
    )
    assert client.patch("/api/v1/collections/" + root["id"], json={"name": None}).status_code == 422
    moved = client.patch("/api/v1/collections/" + child["id"], json={"name": "Moved", "parent_id": None})
    assert moved.status_code == 200 and moved.json()["path"] == "Moved"
    rows = {row["id"]: row for row in client.get("/api/v1/collections").json()}
    assert rows[leaf["id"]]["path"] == "Moved/Leaf"
    chain = [create_folder(client, "Depth")]
    for level in range(1, MAX_COLLECTION_DEPTH):
        chain.append(create_folder(client, str(level), chain[-1]["id"]))
    assert chain[-1]["depth"] == MAX_COLLECTION_DEPTH - 1
    assert (
        client.post(
            "/api/v1/collections", json={"name": "Too deep", "parent_id": chain[-1]["id"]}
        ).status_code
        == 422
    )
    assert (
        client.patch("/api/v1/collections/" + child["id"], json={"parent_id": chain[-2]["id"]}).status_code
        == 422
    )
    rows = {row["id"]: row for row in client.get("/api/v1/collections").json()}
    assert rows[child["id"]]["parent_id"] is None and rows[leaf["id"]]["depth"] == 1
    with client.app.state.sessions() as session:
        models = {row.id: row for row in session.scalars(select(Collection))}
        assert collection_path(models[leaf["id"]], models) == "Moved/Leaf"
        assert collection_descendants(child["id"], models) == {child["id"], leaf["id"]}


def test_exact_classification_legacy_roots_and_subtree_delete(tree_client, config, pdf_bytes):
    client = tree_client
    paper_id = insert_paper(client, config, pdf_bytes)
    endpoint = "/api/v1/papers/" + paper_id
    root = create_folder(client, "Root")
    other = create_folder(client, "Other")
    child = create_folder(client, "Shared", root["id"])
    second = create_folder(client, "Shared", other["id"])
    leaf = create_folder(client, "Leaf", child["id"])
    classified = client.patch(
        endpoint, json={"collection_ids": [child["id"], second["id"], leaf["id"], leaf["id"]]}
    )
    assert classified.status_code == 200
    assert {row["path"] for row in classified.json()["collections"]} == {
        "Root/Shared",
        "Other/Shared",
        "Root/Shared/Leaf",
    }
    counts = {row["id"]: row["paper_count"] for row in client.get("/api/v1/collections").json()}
    assert counts[root["id"]] == 0 and counts[child["id"]] == counts[second["id"]] == 1
    assert client.get("/api/v1/papers", params={"collection": root["id"]}).json()["total"] == 0
    assert client.get("/api/v1/papers", params={"collection": child["id"]}).json()["total"] == 1
    assert client.patch(endpoint, json={"collection_ids": [str(uuid4())]}).status_code == 422
    assert client.patch(endpoint, json={"collection_ids": [], "collections": []}).status_code == 422
    assert len(client.get(endpoint).json()["collections"]) == 3
    assert client.delete("/api/v1/collections/" + root["id"]).status_code == 200
    assert [row["id"] for row in client.get(endpoint).json()["collections"]] == [second["id"]]
    assert client.get(endpoint + "/reading-position?mode=pdf").json()["pdf_page"] == 8
    assert client.get(endpoint + "/pdf").content == pdf_bytes
    legacy = client.patch(endpoint, json={"collections": ["Shared"]})
    assert legacy.status_code == 200
    assert len(legacy.json()["collections"]) == 1
    assert legacy.json()["collections"][0]["parent_id"] is None
    assert legacy.json()["collections"][0]["id"] != second["id"]
    assert client.patch(endpoint, json={"collection_ids": []}).json()["collections"] == []
    assert client.get("/api/v1/papers?unfiled=true").json()["total"] == 1


@pytest.mark.parametrize("fail_before_publish", [False, True])
def test_migration_with_foreign_keys_preserves_all_links_papers_and_positions(
    config, monkeypatch, fail_before_publish
):
    config.data_dir.mkdir()
    engine = create_engine("sqlite:///" + str(config.data_dir / "paperflow.sqlite3"))

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    alembic = AlembicConfig(str(ROOT / "backend/alembic.ini"))
    alembic.set_main_option("script_location", str(ROOT / "backend/alembic"))
    papers, collections = [uid(), uid()], [uid(), uid()]
    links = [(papers[0], collections[0]), (papers[0], collections[1]), (papers[1], collections[0])]
    with engine.begin() as connection:
        alembic.attributes["connection"] = connection
        command.upgrade(alembic, "0002")
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        for paper_id in papers:
            connection.execute(
                text(
                    "INSERT INTO papers (id,title,authors,abstract,arxiv_version,read_status,metadata_status,created_at,updated_at) "
                    "VALUES (:id,'Preserved','[\"Ada\"]','Abstract',0,'reading','local','2025','2025')"
                ),
                {"id": paper_id},
            )
            connection.execute(
                text(
                    "INSERT INTO reading_positions (paper_id,mode,pdf_page,pdf_scale,scroll_ratio,updated_at) "
                    "VALUES (:id,'pdf',8,1.25,0.4,'2025')"
                ),
                {"id": paper_id},
            )
        for collection_id, name in zip(collections, ("Robotics", "视觉")):
            connection.execute(
                text("INSERT INTO collections (id,name) VALUES (:id,:name)"),
                {"id": collection_id, "name": name},
            )
        for paper_id, collection_id in links:
            connection.execute(
                text("INSERT INTO paper_collections VALUES (:paper,:collection)"),
                {"paper": paper_id, "collection": collection_id},
            )
    engine.dispose()
    if fail_before_publish:
        from alembic.operations import Operations

        def fail_index(*args, **kwargs):
            raise RuntimeError("Simulated migration interruption")

        with monkeypatch.context() as patch:
            patch.setattr(Operations, "create_index", fail_index)
            with pytest.raises(RuntimeError, match="Simulated migration interruption"):
                create_app(config)
        # The failure occurred after DROP/RENAME. The old schema and links must
        # still be intact, and the next startup must be able to migrate again.
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0002"
            assert set(connection.execute(text("SELECT * FROM paper_collections")).all()) == set(links)
            assert "parent_id" not in {
                row[1] for row in connection.exec_driver_sql("PRAGMA table_info(collections)")
            }
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    app = create_app(config)
    with app.state.sessions() as session:
        assert set(session.execute(select(paper_collections)).all()) == set(links)
        assert [row.title for row in session.scalars(select(Paper))] == ["Preserved", "Preserved"]
        assert [
            (row.pdf_page, row.pdf_scale, row.scroll_ratio) for row in session.scalars(select(Position))
        ] == [(8, 1.25, 0.4)] * 2
        assert all(row.parent_id is None for row in session.scalars(select(Collection)))
        assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
        child = Collection(id=uid(), name="Nested", parent_id=collections[0])
        session.add(child)
        session.commit()
        assert child.name_key == "nested"
    app.state.sessions.kw["bind"].dispose()
