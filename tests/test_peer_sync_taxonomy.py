"""Taxonomy operations accepted locally must remain usable across peers."""

import pytest

from test_peer_sync import LOCAL, devices, papers, patch, upload


def test_sync_preserves_supported_tag_characters(tmp_path, monkeypatch, pdf_bytes):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        names = ["slam/ros", "c++:vision", ".draft"]
        patch(mac, paper["id"], tags=names)
        peer.once()
        assert {tag["name"] for tag in papers(ubuntu)[0]["tags"]} == set(names)


def test_offline_collection_name_swap_syncs_atomically(
    tmp_path, monkeypatch, pdf_bytes
):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        a = mac.post(
            "/api/v1/collections", json={"name": "First"}, headers=LOCAL
        ).json()
        b = mac.post(
            "/api/v1/collections", json={"name": "Second"}, headers=LOCAL
        ).json()
        patch(mac, paper["id"], collection_ids=[a["id"]])
        peer.once()
        for identifier, name in (
            (a["id"], "Temporary"),
            (b["id"], "First"),
            (a["id"], "Second"),
        ):
            response = mac.patch(
                f"/api/v1/collections/{identifier}", json={"name": name}, headers=LOCAL
            )
            assert response.status_code == 200, response.text
        peer.once()
        assert papers(ubuntu)[0]["collections"][0]["name"] == "Second"
        assert {row["name"] for row in ubuntu.get("/api/v1/collections").json()} == {
            "First",
            "Second",
        }


def test_offline_tag_name_swap_syncs_atomically(tmp_path, monkeypatch, pdf_bytes):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        a = mac.post("/api/v1/tags", json={"name": "first"}, headers=LOCAL).json()
        b = mac.post("/api/v1/tags", json={"name": "second"}, headers=LOCAL).json()
        patch(mac, paper["id"], tags=["first"])
        peer.once()
        for identifier, name in (
            (a["id"], "temporary"),
            (b["id"], "first"),
            (a["id"], "second"),
        ):
            response = mac.patch(
                f"/api/v1/tags/{identifier}", json={"name": name}, headers=LOCAL
            )
            assert response.status_code == 200, response.text
        peer.once()
        assert {tag["name"] for tag in papers(ubuntu)[0]["tags"]} == {"second"}


def test_collection_subtree_delete_preserves_paper(tmp_path, monkeypatch, pdf_bytes):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        parent = mac.post(
            "/api/v1/collections", json={"name": "Parent"}, headers=LOCAL
        ).json()
        child = mac.post(
            "/api/v1/collections",
            json={"name": "Child", "parent_id": parent["id"]},
            headers=LOCAL,
        ).json()
        patch(mac, paper["id"], collection_ids=[child["id"]])
        peer.once()
        assert (
            mac.delete(f"/api/v1/collections/{parent['id']}", headers=LOCAL).status_code
            == 200
        )
        peer.once()
        peer.once()
        assert ubuntu.get("/api/v1/collections").json() == []
        assert papers(ubuntu)[0]["has_pdf"] and not papers(ubuntu)[0]["collections"]


@pytest.mark.parametrize("kind", ["tags", "collections"])
def test_deleted_taxonomy_name_can_be_reused_offline(tmp_path, monkeypatch, kind):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        first = mac.post(
            f"/api/v1/{kind}", json={"name": "first"}, headers=LOCAL
        ).json()
        second = mac.post(
            f"/api/v1/{kind}", json={"name": "second"}, headers=LOCAL
        ).json()
        peer.once()
        assert (
            mac.delete(f"/api/v1/{kind}/{first['id']}", headers=LOCAL).status_code
            == 200
        )
        assert (
            mac.patch(
                f"/api/v1/{kind}/{second['id']}", json={"name": "first"}, headers=LOCAL
            ).status_code
            == 200
        )
        peer.once()
        assert [row["name"] for row in ubuntu.get(f"/api/v1/{kind}").json()] == [
            "first"
        ]
