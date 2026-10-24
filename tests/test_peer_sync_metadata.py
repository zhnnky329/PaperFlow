"""Metadata values and their protection must survive as one synchronized edit."""

import pytest
from sqlalchemy import select

from app.db import Paper, Setting, SyncBaseline, SyncRecord
from app.metadata import FIELDS, apply_values
from app.peer_sync import Snapshot
from test_peer_sync import devices, patch, upload


def capture(peer):
    with peer.sessions() as session:
        peer.capture(session)
        session.commit()


def rows(peer):
    with peer.sessions() as session:
        return {r.key: (r.value, r.clock, r.device, r.phase) for r in session.scalars(select(SyncRecord))}


@pytest.mark.parametrize("independent_ids", [False, True])
def test_concurrent_manual_fields_remain_protected(tmp_path, monkeypatch, pdf_bytes, independent_ids):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        left = upload(mac, pdf_bytes)
        right = upload(ubuntu, pdf_bytes) if independent_ids else left
        peer.once()
        patch(mac, left["id"], title="Manually corrected title")
        patch(ubuntu, right["id"], abstract="Manually corrected abstract")
        capture(peer)
        capture(other)
        peer.once()
        before = rows(peer)
        peer.once()
        assert rows(peer) == before
        for device, identifier in ((peer, left["id"]), (other, right["id"])):
            with device.sessions() as session:
                paper = session.get(Paper, identifier)
                assert paper.title == "Manually corrected title"
                assert paper.abstract == "Manually corrected abstract"
                assert paper.metadata_sources["title"] == "manual"
                assert paper.metadata_sources["abstract"] == "manual"
                apply_values(paper, {"title": "Automatic title", "abstract": "Automatic abstract"}, "arxiv")
                assert paper.title == "Manually corrected title"
                assert paper.abstract == "Manually corrected abstract"


@pytest.mark.parametrize("winning_source", [None, "arxiv", "manual"])
def test_same_field_keeps_the_winning_value_and_source(tmp_path, monkeypatch, pdf_bytes, winning_source):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        peer.once()
        patch(mac, paper["id"], title="Losing manual title")
        capture(peer)
        with other.sessions() as session:
            row = session.get(Paper, paper["id"])
            row.title = "Winning title"
            sources = dict(row.metadata_sources)
            if winning_source is None:
                sources.pop("title", None)
            else:
                sources["title"] = winning_source
            row.metadata_sources = sources
            session.merge(Setting(key="sync_clock", value=10000))
            session.commit()
        capture(other)
        peer.once()
        peer.once()
        for device in (peer, other):
            with device.sessions() as session:
                row = session.get(Paper, paper["id"])
                assert row.title == "Winning title"
                assert row.metadata_sources.get("title") == winning_source


def test_source_only_edit_and_manual_clears(tmp_path, monkeypatch, pdf_bytes):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        patch(mac, paper["id"], doi="10.1234/original", year=2025, venue="Conference", venue_kind="conference",
              source_url="https://example.org/paper", abstract="Original", authors=["Author"],
              affiliations=[{"name": "University", "authors": []}])
        peer.once()
        with peer.sessions() as session:
            row = session.get(Paper, paper["id"])
            row.metadata_sources = dict(row.metadata_sources) | {"title": "crossref-confirmed"}
            session.commit()
        before = rows(peer)
        peer.once()
        assert rows(peer)[f"paper/{paper['id']}/title"][1] > before[f"paper/{paper['id']}/title"][1]
        cleared = {"doi": None, "year": None, "venue": None, "venue_kind": None, "source_url": None,
                   "abstract": "", "authors": [], "affiliations": []}
        patch(mac, paper["id"], **cleared)
        peer.once()
        for device in (peer, other):
            with device.sessions() as session:
                row = session.get(Paper, paper["id"])
                assert row.metadata_sources["title"] == "crossref-confirmed"
                for field, value in cleared.items():
                    assert getattr(row, field) == value
                    assert row.metadata_sources[field] == "manual"
                apply_values(row, {"doi": "10.1234/automatic", "year": 2026, "abstract": "Automatic"}, "arxiv")
                assert row.doi is None and row.year is None and row.abstract == ""


def make_legacy(peer):
    """Represent the last synchronized state exactly as the original v1 did."""
    with peer.sessions() as session:
        sources = {}
        for paper in session.scalars(select(Paper)):
            sources[paper.id] = dict(paper.metadata_sources)
        for model in (SyncRecord, SyncBaseline):
            for row in session.scalars(select(model)):
                parts = row.key.split("/")
                if parts[0] == "paper" and parts[2] in FIELDS and isinstance(row.value, dict):
                    row.value = row.value["value"]
            for paper_id, value in sources.items():
                key = f"paper/{paper_id}/metadata_sources"
                if model is SyncBaseline:
                    session.merge(model(key=key, value=value))
                else:
                    session.merge(model(key=key, value=value, clock=1, device=peer.device, phase=0))
        session.commit()


def test_legacy_baselines_preserve_versions_and_pending_edits(tmp_path, monkeypatch, pdf_bytes):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        left, right = upload(mac, pdf_bytes), upload(ubuntu, pdf_bytes)
        peer.once()
        for device in (peer, other):
            make_legacy(device)
            before = rows(device)
            capture(device)
            assert rows(device) == before  # Upgrading must not stamp every field as a new edit.
        patch(mac, left["id"], title="Pending Mac title", year=2026)
        patch(ubuntu, right["id"], abstract="Pending Ubuntu abstract")
        capture(peer)
        capture(other)
        peer.once()
        peer.once()
        for device, identifier in ((peer, left["id"]), (other, right["id"])):
            with device.sessions() as session:
                paper = session.get(Paper, identifier)
                assert paper.title == "Pending Mac title" and paper.year == 2026
                assert paper.abstract == "Pending Ubuntu abstract"
                assert all(paper.metadata_sources[field] == "manual" for field in ("title", "year", "abstract"))


def test_old_protocol_and_invalid_source_are_rejected_without_changes(tmp_path, monkeypatch, pdf_bytes):
    from test_peer_sync import PEER

    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        peer.once()
        with peer.sessions() as session:
            packet = peer.snapshot(session)
            session.commit()
        before = rows(other)
        packet["protocol"] = 1
        assert ubuntu.post("/peer/v1/exchange", json=packet, headers=PEER).status_code == 422
        assert rows(other) == before
        packet["protocol"] = 2
        for record in packet["records"]:
            if record["key"] == f"paper/{paper['id']}/title":
                record["value"] = {"value": "Bad", "source": {"manual": True}}
        assert ubuntu.post("/peer/v1/exchange", json=packet, headers=PEER).status_code == 422
        assert rows(other) == before
        assert Snapshot.model_validate({"protocol": 2, "device": peer.device}).protocol == 2


def test_legacy_null_fields_without_records_keep_manual_protection(tmp_path, monkeypatch, pdf_bytes):
    with devices(tmp_path, monkeypatch) as (mac, ubuntu, peer, other):
        paper = upload(mac, pdf_bytes)
        patch(mac, paper["id"], doi="10.1234/original", year=2025)
        patch(mac, paper["id"], doi=None, year=None)
        capture(peer)
        make_legacy(peer)
        with peer.sessions() as session:
            # v1's first capture omitted null-valued fields entirely.
            for row in session.scalars(select(SyncRecord)):
                if row.value is None:
                    session.delete(row)
            session.commit()
        before = rows(peer)
        capture(peer)
        assert rows(peer) == before
        peer.once()
        peer.once()
        for device in (peer, other):
            with device.sessions() as session:
                row = session.get(Paper, paper["id"])
                assert row.metadata_sources["doi"] == row.metadata_sources["year"] == "manual"
                apply_values(row, {"doi": "10.1234/automatic", "year": 2026}, "arxiv")
                assert row.doi is None and row.year is None
