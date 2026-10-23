"""Two local libraries exchanging versioned records and content-addressed assets.

Only library data is replicated. Settings, secrets, Discovery, and local jobs
stay on their originating device. A Lamport clock orders concurrent changes;
each field/membership and each device's reading position has its own record.
"""

import hashlib
import json
import os
import re
import shutil
import threading
import zipfile
from datetime import datetime, timezone
from uuid import UUID

import httpx
from bs4 import BeautifulSoup
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select, func

from .collection_tree import MAX_COLLECTION_DEPTH, collection_path
from .db import (
    Collection,
    Job,
    Paper,
    PeerReceipt,
    Position,
    RemoteConversion,
    Setting,
    SyncAlias,
    SyncBaseline,
    SyncRecord,
    Tag,
    now,
    paper_collections,
    paper_tags,
    uid,
)
from .folders import folder_name
from .html import publish_html
from .metadata import FIELDS as METADATA_FIELDS
from .schemas import PaperPatch, ReadingPosition
from .storage import delete_assets, validate_pdf
from .worker import job_dict, settings

PAPER_FIELDS = (
    "title",
    "authors",
    "abstract",
    "year",
    "arxiv_id",
    "arxiv_version",
    "source_url",
    "official_html_url",
    "doi",
    "venue",
    "venue_kind",
    "affiliations",
    "metadata_sources",
    "created_at",
    "last_read_at",
    "read_status",
)
MODELS = {"paper": Paper, "tag": Tag, "collection": Collection}
HASH = r"[a-f0-9]{64}"


class WireRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(max_length=300)
    value: object = None
    clock: int = Field(ge=1, le=2**53 - 1)
    device: UUID
    phase: int = Field(0, ge=0, le=1)

    @field_validator("key")
    @classmethod
    def valid_key(cls, key):
        parts = key.split("/")
        if len(parts) < 2:
            raise ValueError("Invalid sync key")
        kind = parts[0]
        UUID(parts[1])
        if kind == "paper" and len(parts) == 3 and parts[2] in (*PAPER_FIELDS, "exists"):
            return key
        if kind in ("tag", "collection", "pdf", "html") and len(parts) == 2:
            return key
        if kind in ("tags", "collections") and len(parts) == 3:
            UUID(parts[2])
            return key
        if kind == "position" and len(parts) == 4 and parts[2] in ("pdf", "local_html"):
            UUID(parts[3])
            return key
        raise ValueError("Unknown sync field")


class Identity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern="^(paper|tag|collection)$")
    id: UUID
    name: str = Field("", max_length=80)
    parent_id: UUID | None = None
    pdf_sha256: str | None = Field(None, pattern="^" + HASH + "$")
    arxiv_id: str | None = Field(None, pattern=r"^(\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})$")
    arxiv_version: int = Field(0, ge=0, le=100000)


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern="^(pdf|html)$")
    digest: str = Field(pattern="^" + HASH + "$")
    size: int = Field(ge=0, le=1024**3)


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol: int = Field(2, ge=2, le=2)
    device: UUID
    identities: list[Identity] = Field(default_factory=list, max_length=100000)
    records: list[WireRecord] = Field(default_factory=list, max_length=100000)
    assets: list[Asset] = Field(default_factory=list, max_length=100000)


class ConversionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    paper_id: UUID
    pdf_sha256: str = Field(pattern="^" + HASH + "$")
    mode: str = Field(pattern="^(fast|balanced)$")
    force_rebuild: bool = False
    clock: int = Field(ge=1, le=2**53 - 1)
    device: UUID
    canceled: bool = False


def rank(record):
    return record.clock, str(record.device), record.phase


def remote_dict(job):
    return {
        "id": job.id,
        "status": job.status,
        "progress_stage": job.progress_stage,
        "error_message": job.error_message,
        "attempt": job.attempt,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "execution_target": "ubuntu",
        "cancel_requested": job.cancel_requested,
    }


class PeerSync:
    def __init__(self, config, sessions, worker, folder_sync, lock):
        self.config, self.sessions, self.worker = config, sessions, worker
        self.folders, self.lock = folder_sync, lock
        self.stop_event, self.wake = threading.Event(), threading.Event()
        self.thread = None
        self.transfer_lock = threading.Lock()
        self.last_success = None
        self.error = None
        self.online = False
        self.transport = None  # HTTPX transport injection for isolated two-device tests.
        self.archive_cache = {}
        with sessions() as session:
            device = session.get(Setting, "sync_device_id")
            if not device:
                device = Setting(key="sync_device_id", value=uid())
                session.add(device)
                session.commit()
            self.device = device.value
        if config.sync_enabled:
            worker.on_enqueue = self.reserve
            worker.on_publish = self.complete

    def start(self):
        if self.config.sync_enabled:
            self.thread = threading.Thread(target=self.run, name="peer-sync", daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        if self.thread:
            self.thread.join()

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.once()
            except Exception as exc:
                # Never echo URLs, credentials, HTTP bodies, or document contents.
                self.online = False
                self.error = (
                    exc.detail
                    if isinstance(exc, HTTPException)
                    else "设备同步未完成，请检查连接、配对密钥和两端版本；本地阅读可继续。"
                )
            self.wake.wait(self.config.sync_interval)
            self.wake.clear()

    def status(self):
        with self.sessions() as session:
            pending = len(
                list(
                    session.scalars(
                        select(RemoteConversion).where(RemoteConversion.status.in_(["queued", "running"]))
                    )
                )
            )
        recent = bool(
            self.last_success
            and (datetime.now(timezone.utc) - datetime.fromisoformat(self.last_success)).total_seconds()
            < self.config.sync_interval * 3
        )
        return {
            "enabled": self.config.sync_enabled,
            "device_id": self.device,
            "peer_configured": bool(self.config.sync_peer_url),
            "online": self.online and recent,
            "accept_conversions": self.config.sync_accept_conversions,
            "last_success": self.last_success,
            "error": self.error,
            "pending_conversions": pending,
        }

    def clock(self, session):
        row = session.get(Setting, "sync_clock")
        value = max(row.value if row else 0, session.scalar(select(func.max(SyncRecord.clock))) or 0) + 1
        session.merge(Setting(key="sync_clock", value=value))
        session.flush()
        return value

    def local_id(self, session, kind, identifier):
        alias = session.get(SyncAlias, f"{kind}/{identifier}")
        return alias.local_id if alias else str(identifier)

    def logical(self, session, key, aliases=None):
        parts = key.split("/")
        kind = parts[0]
        entity = kind if kind in MODELS else "paper"

        def resolve(kind, identifier):
            return (
                aliases.get(f"{kind}/{identifier}", identifier)
                if aliases is not None
                else self.local_id(session, kind, identifier)
            )

        parts[1] = resolve(entity, parts[1])
        if kind in ("tags", "collections"):
            parts[2] = resolve("tag" if kind == "tags" else "collection", parts[2])
        return "/".join(parts)

    def winners(self, session):
        result = {}
        aliases = {r.key: r.local_id for r in session.scalars(select(SyncAlias))}
        for record in session.scalars(select(SyncRecord)):
            key = self.logical(session, record.key, aliases)
            if key not in result or rank(record) > rank(result[key]):
                result[key] = record
        return result

    def record(self, session, key, value, version=None, phase=0):
        version = version or (self.clock(session), self.device)
        row = SyncRecord(key=key, value=value, clock=version[0], device=version[1], phase=phase)
        current = self.winners(session).get(self.logical(session, key))
        if current and rank(current) > rank(row):
            return current
        session.merge(row)
        session.flush()
        return row

    def baseline(self, session, snapshot):
        existing = {r.key: r for r in session.scalars(select(SyncBaseline))}
        for key, value in snapshot.items():
            if key not in existing:
                session.add(SyncBaseline(key=key, value=value))
            elif existing[key].value != value:
                existing[key].value = value
        for row in existing.values():
            if row.key not in snapshot:
                row.value = None
        session.flush()

    def blob_path(self, kind, digest):
        if kind not in ("pdf", "html") or not re.fullmatch(HASH, digest):
            raise HTTPException(422, "资源标识无效")
        return self.config.path(f"peer-cache/{kind}/{digest}")

    def asset_path(self, session, kind, digest):
        cached = self.blob_path(kind, digest)
        if cached.is_file():
            return cached
        if kind == "pdf":
            paper = session.scalar(select(Paper).where(Paper.pdf_sha256 == digest))
            if paper and paper.pdf_path and self.config.path(paper.pdf_path).is_file():
                return self.config.path(paper.pdf_path)
        return None

    def html_asset(self, path):
        files = sorted(path.parent.iterdir())
        stamp = tuple((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in files if p.is_file())
        cached = self.archive_cache.get(str(path))
        if cached and cached[0] == stamp and self.blob_path("html", cached[1]).is_file():
            return cached[1]
        stage = self.config.path("staging/peer-html-" + uid())
        stage.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(stage, "w", zipfile.ZIP_DEFLATED) as archive:
                for file in files:
                    if (
                        file.is_symlink()
                        or not file.is_file()
                        or not re.fullmatch(r"article\.html|manifest\.json|asset-\d+\.png", file.name)
                    ):
                        raise HTTPException(409, "HTML 资源目录不完整或包含不支持的文件")
                    info = zipfile.ZipInfo(file.name, date_time=(2020, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, file.read_bytes())
            digest = hashlib.sha256(stage.read_bytes()).hexdigest()
            target = self.blob_path("html", digest)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage, target)
            self.archive_cache[str(path)] = stamp, digest
            return digest
        finally:
            stage.unlink(missing_ok=True)

    def values(self, session):
        values = {}
        for paper in session.scalars(select(Paper)):
            prefix = f"paper/{paper.id}/"
            values[prefix + "exists"] = True
            for field in PAPER_FIELDS:
                if field == "metadata_sources":
                    continue  # Old aggregate records remain readable, but are never written again.
                value = getattr(paper, field)
                if field in METADATA_FIELDS:
                    value = {"value": value, "source": (paper.metadata_sources or {}).get(field)}
                values[prefix + field] = value
            if paper.pdf_path and self.config.path(paper.pdf_path).is_file():
                values[f"pdf/{paper.id}"] = {"digest": paper.pdf_sha256}
            if paper.html_path and self.config.path(paper.html_path).is_file():
                values[f"html/{paper.id}"] = {
                    "digest": self.html_asset(self.config.path(paper.html_path)),
                    "pdf_sha256": paper.pdf_sha256,
                }
        for kind, model in (("tag", Tag), ("collection", Collection)):
            for row in session.scalars(select(model)):
                values[f"{kind}/{row.id}"] = {"name": row.name}
                if kind == "collection":
                    values[f"{kind}/{row.id}"]["parent_id"] = row.parent_id
        for kind, table in (("tags", paper_tags), ("collections", paper_collections)):
            for paper_id, item_id in session.execute(select(table)):
                values[f"{kind}/{paper_id}/{item_id}"] = True
        for row in session.scalars(select(Position)):
            values[f"position/{row.paper_id}/{row.mode}/{self.device}"] = {
                field: getattr(row, field)
                for field in ("pdf_page", "pdf_scale", "html_anchor", "scroll_ratio", "updated_at")
            }
        return values

    def capture(self, session):
        aliases = {r.key for r in session.scalars(select(SyncAlias))}
        for kind, model in MODELS.items():
            for row in session.scalars(select(model)):
                key = f"{kind}/{row.id}"
                if key not in aliases:
                    session.add(SyncAlias(key=key, local_id=row.id))
        session.flush()
        values = self.values(session)
        baseline = {r.key: r.value for r in session.scalars(select(SyncBaseline))}
        previous = dict(baseline)
        for key in values.keys() & baseline.keys():
            parts = key.split("/")
            if parts[0] == "paper" and parts[2] in METADATA_FIELDS and not isinstance(baseline[key], dict):
                # Compare a v1 baseline without turning an upgrade into an edit of every field.
                sources = baseline.get(f"paper/{parts[1]}/metadata_sources") or {}
                previous[key] = {"value": baseline[key], "source": sources.get(parts[2])}
        changed = [
            key for key in values.keys() | previous.keys()
            if not key.endswith("/metadata_sources") and values.get(key) != previous.get(key)
        ]
        if changed:
            version = self.clock(session), self.device
            for key in sorted(changed):
                session.merge(
                    SyncRecord(key=key, value=values.get(key), clock=version[0], device=version[1], phase=0)
                )
            self.baseline(session, values)
        session.flush()

    def snapshot(self, session):
        self.capture(session)
        identities = []
        for alias in session.scalars(select(SyncAlias)):
            kind, identifier = alias.key.split("/")
            row = session.get(MODELS[kind], alias.local_id)
            if not row:
                continue
            item = {"kind": kind, "id": identifier}
            if kind == "paper":
                item.update(pdf_sha256=row.pdf_sha256, arxiv_id=row.arxiv_id, arxiv_version=row.arxiv_version)
            else:
                item["name"] = row.name
                if kind == "collection":
                    item["parent_id"] = row.parent_id
            identities.append(item)
        records = [
            {"key": r.key, "value": r.value, "clock": r.clock, "device": r.device, "phase": r.phase}
            for r in session.scalars(select(SyncRecord))
        ]
        assets = {}
        for row in self.winners(session).values():
            kind = row.key.split("/")[0]
            if kind in ("pdf", "html") and row.value and row.value.get("digest"):
                digest = row.value["digest"]
                path = self.asset_path(session, kind, digest)
                if path:
                    assets[kind, digest] = {"kind": kind, "digest": digest, "size": path.stat().st_size}
        return {
            "protocol": 2,
            "device": self.device,
            "identities": identities,
            "records": records,
            "assets": list(assets.values()),
        }

    def resolve_identities(self, session, identities):
        # Parents are resolved before children. Aliases preserve existing local
        # primary keys, jobs, Discovery links, and previously imported libraries.
        pending = list(identities)
        for _ in range(MAX_COLLECTION_DEPTH + 1):
            remaining = []
            for item in pending:
                identifier = str(item.id)
                alias_key = f"{item.kind}/{identifier}"
                if session.get(SyncAlias, alias_key):
                    continue
                model = MODELS[item.kind]
                row = session.get(model, identifier)
                if not row and item.kind == "paper":
                    if item.pdf_sha256:
                        row = session.scalar(select(Paper).where(Paper.pdf_sha256 == item.pdf_sha256))
                    if not row and item.arxiv_id:
                        row = session.scalar(
                            select(Paper).where(
                                Paper.arxiv_id == item.arxiv_id, Paper.arxiv_version == item.arxiv_version
                            )
                        )
                parent_id = None
                if item.kind == "collection" and item.parent_id:
                    parent_id = self.local_id(session, "collection", str(item.parent_id))
                    if not session.get(Collection, parent_id):
                        remaining.append(item)
                        continue
                if item.kind in ("tag", "collection"):
                    name = (
                        folder_name(item.name) if item.kind == "collection" else item.name.strip().casefold()
                    )
                    if not name or len(name) > 80:
                        raise HTTPException(422, "同步分类名称无效")
                    if not row:
                        row = next(
                            (
                                r
                                for r in session.scalars(select(model))
                                if r.name.casefold() == name.casefold()
                                and (item.kind != "collection" or r.parent_id == parent_id)
                            ),
                            None,
                        )
                    if not row:
                        row = model(id=identifier, name=name)
                        if item.kind == "collection":
                            row.parent_id = parent_id
                elif not row:
                    row = Paper(id=identifier, title="Untitled", pdf_sha256=item.pdf_sha256)
                session.add(row)
                session.flush()
                session.add(SyncAlias(key=alias_key, local_id=row.id))
                session.flush()
            if not remaining:
                return
            pending = remaining
        raise HTTPException(409, "同步文件夹层级存在循环或缺少上级目录")

    def validate_value(self, record):
        kind, *parts = record.key.split("/")
        value = record.value
        if value is None:
            return
        if kind == "paper":
            field = parts[1]
            if field == "exists":
                if value is not True:
                    raise ValueError("Invalid paper existence")
            elif field in METADATA_FIELDS and isinstance(value, dict):
                if set(value) != {"value", "source"}:
                    raise ValueError("Invalid metadata field")
                source = value["source"]
                if source is not None and (not isinstance(source, str) or len(source) > 100):
                    raise ValueError("Invalid metadata source")
                if value["value"] is None and field in ("title", "authors", "abstract", "affiliations"):
                    raise ValueError("Invalid empty metadata field")
                PaperPatch.model_validate({field: value["value"]})
            elif field in PaperPatch.model_fields:
                PaperPatch.model_validate({field: value})
            elif field == "arxiv_id":
                if value is not None and not re.fullmatch(r"\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7}", str(value)):
                    raise ValueError("Invalid arXiv ID")
            elif field == "arxiv_version":
                if not isinstance(value, int) or not 0 <= value <= 100000:
                    raise ValueError("Invalid version")
            elif field == "official_html_url":
                if value and not re.fullmatch(r"https://arxiv.org/html/[\w./-]+", str(value)):
                    raise ValueError("Invalid official HTML URL")
            elif field == "metadata_sources":
                if not isinstance(value, dict) or len(value) > 100:
                    raise ValueError("Invalid metadata sources")
            elif not isinstance(value, str) or len(value) > 100:
                raise ValueError("Invalid timestamp")
        elif kind in ("tags", "collections"):
            if value is not True:
                raise ValueError("Invalid membership")
        elif kind in ("tag", "collection"):
            if not isinstance(value, dict) or set(value) - {"name", "parent_id"}:
                raise ValueError("Invalid taxonomy")
            folder_name(value["name"])
            if value.get("parent_id"):
                UUID(value["parent_id"])
        elif kind == "position":
            if not isinstance(value, dict) or set(value) - {
                "pdf_page",
                "pdf_scale",
                "html_anchor",
                "scroll_ratio",
                "updated_at",
            }:
                raise ValueError("Invalid reading position")
            ReadingPosition.model_validate(value)
            if not isinstance(value.get("updated_at"), str) or len(value["updated_at"]) > 100:
                raise ValueError("Invalid position timestamp")
        elif kind in ("pdf", "html"):
            if not isinstance(value, dict) or set(value) - {"digest", "pdf_sha256"}:
                raise ValueError("Invalid asset")
            for key, digest in value.items():
                if digest is not None and not re.fullmatch(HASH, str(digest)):
                    raise ValueError("Invalid asset hash")

    def merge(self, session, packet):
        if str(packet.device) == self.device:
            raise HTTPException(409, "两端设备 ID 相同；请勿复制整库来配置第二台设备")
        self.capture(session)
        for record in packet.records:
            try:
                self.validate_value(record)
            except (ValueError, KeyError, TypeError) as exc:
                raise HTTPException(422, "同步记录格式无效") from exc
        self.resolve_identities(session, packet.identities)
        existing = {r.key: r for r in session.scalars(select(SyncRecord))}
        for record in packet.records:
            current = existing.get(record.key)
            if current is None or rank(record) > rank(current):
                session.merge(SyncRecord(**record.model_dump(mode="json")))
        session.flush()
        self.materialize(session)
        self.baseline(session, self.values(session))

    def commit(self, session):
        session.commit()
        # A rolled-back exchange must never remove the original files.
        for paper_id in session.info.pop("peer_deleted_assets", set()):
            if not session.get(Paper, paper_id):
                delete_assets(self.config, paper_id)

    def materialize(self, session):
        winners = self.winners(session)
        # Validate the entire proposed tree before mutating filesystem state.
        collections = {r.id: r for r in session.scalars(select(Collection))}
        deleted_collections = set()
        for key, record in winners.items():
            parts = key.split("/")
            if parts[0] == "collection" and parts[1] in collections:
                row = collections[parts[1]]
                if record.value is None:
                    deleted_collections.add(row.id)
                else:
                    row.name = record.value["name"]
                    parent = record.value.get("parent_id")
                    row.parent_id = self.local_id(session, "collection", parent) if parent else None
        live = {k: v for k, v in collections.items() if k not in deleted_collections}
        with session.no_autoflush:
            names = set()
            for row in live.values():
                if row.parent_id in deleted_collections:
                    row.parent_id = None
                collection_path(row, live)
                name = row.parent_id, row.name.casefold()
                if name in names:
                    raise HTTPException(409, "两端文件夹改名冲突，请修改同名文件夹后重试同步")
                names.add(name)
        # Flush independent paper fields after taxonomy validation.
        deleted_papers = set()
        for key, record in winners.items():
            parts = key.split("/")
            if parts[0] != "paper":
                continue
            paper = session.get(Paper, parts[1])
            if not paper:
                continue
            field, value, source = parts[2], record.value, None
            if field == "metadata_sources":
                # v1 omitted null fields on first capture. Their manual-clear
                # protection can therefore exist only in this legacy aggregate.
                missing = {
                    name: source for name, source in (value or {}).items()
                    if name in METADATA_FIELDS and f"paper/{paper.id}/{name}" not in winners
                }
                paper.metadata_sources = dict(paper.metadata_sources or {}) | missing
                continue
            if field in METADATA_FIELDS:
                if isinstance(value, dict):
                    value, source = value["value"], value["source"]
                else:
                    legacy = winners.get(f"paper/{paper.id}/metadata_sources")
                    source = (legacy.value or {}).get(field) if legacy else None
            if field == "exists":
                if value is None:
                    deleted_papers.add(paper.id)
            elif value is not None or field in (
                "year",
                "arxiv_id",
                "source_url",
                "official_html_url",
                "doi",
                "venue",
                "venue_kind",
                "last_read_at",
            ):
                setattr(paper, field, value)
                if field in METADATA_FIELDS:
                    sources = dict(paper.metadata_sources or {})
                    if source is None:
                        sources.pop(field, None)
                    else:
                        sources[field] = source
                    paper.metadata_sources = sources
        for key, record in winners.items():
            kind, *parts = key.split("/")
            if kind == "tag":
                row = session.get(Tag, parts[0])
                if row and record.value is None:
                    session.delete(row)
                elif row:
                    row.name = record.value["name"]
            if kind in ("tags", "collections"):
                table, model = (paper_tags, Tag) if kind == "tags" else (paper_collections, Collection)
                fk = "tag_id" if kind == "tags" else "collection_id"
                clause = (table.c.paper_id == parts[0]) & (table.c[fk] == parts[1])
                if record.value and session.get(Paper, parts[0]) and session.get(model, parts[1]):
                    if not session.execute(select(table).where(clause)).first():
                        session.execute(table.insert().values(paper_id=parts[0], **{fk: parts[1]}))
                else:
                    session.execute(delete(table).where(clause))
        positions = {}
        for key, record in winners.items():
            parts = key.split("/")
            if parts[0] == "position" and record.value:
                group = parts[1], parts[2]
                if group not in positions or rank(record) > rank(positions[group]):
                    positions[group] = record
        for (paper_id, mode), record in positions.items():
            if not session.get(Paper, paper_id):
                continue
            row = session.get(Position, (paper_id, mode)) or Position(
                paper_id=paper_id, mode=mode, pdf_scale=1
            )
            for field, value in record.value.items():
                if field != "pdf_scale":  # Zoom belongs to this screen, not the remote screen.
                    setattr(row, field, value)
            session.add(row)
        for identifier in deleted_collections:
            session.execute(delete(paper_collections).where(paper_collections.c.collection_id == identifier))
        for identifier in deleted_collections:
            # Bulk deletion avoids an autoflush of temporarily dangling children.
            session.execute(delete(Collection).where(Collection.id == identifier))
        for identifier in deleted_papers:
            paper = session.get(Paper, identifier)
            if paper:
                for job in session.scalars(select(Job).where(Job.paper_id == identifier)):
                    if (
                        self.worker.process
                        and getattr(self.worker, "current_job", None) == job.id
                        and self.worker.process.poll() is None
                    ):
                        self.worker.kill(self.worker.process)
                session.delete(paper)
        session.info.setdefault("peer_deleted_assets", set()).update(deleted_papers)
        session.flush()
        self.materialize_assets(session)

    def materialize_assets(self, session):
        winners = self.winners(session)
        for key, record in winners.items():
            kind, *parts = key.split("/")
            if kind not in ("pdf", "html") or not record.value or not record.value.get("digest"):
                continue
            paper = session.get(Paper, parts[0])
            if not paper:
                continue
            digest = record.value["digest"]
            source = self.asset_path(session, kind, digest)
            if source is None:
                continue
            if kind == "pdf":
                if paper.pdf_sha256 and paper.pdf_sha256 != digest:
                    raise HTTPException(409, "论文 PDF 内容冲突，原文未覆盖")
                relative = f"papers/{paper.id}/original.pdf"
                target = self.config.path(relative)
                if not target.is_file():
                    validate_pdf(source)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temp = target.with_name("peer-" + uid() + ".pdf")
                    try:
                        shutil.copyfile(source, temp)
                        os.replace(temp, target)
                    finally:
                        temp.unlink(missing_ok=True)
                paper.pdf_path, paper.pdf_sha256 = relative, digest
            else:
                if not paper.pdf_sha256 or record.value.get("pdf_sha256") != paper.pdf_sha256:
                    continue
                relative = f"papers/{paper.id}/derivatives/peer/{digest}/article.html"
                target = self.config.path(relative)
                if not target.is_file():
                    self.install_html(source, target.parent, paper.id)
                paper.html_path = relative
        session.flush()

    def install_html(self, source, target, paper_id):
        stage = self.config.path("staging/peer-unpack-" + uid())
        raw, clean = stage / "raw", stage / "clean"
        raw.mkdir(parents=True)
        try:
            with zipfile.ZipFile(source) as archive:
                entries = archive.infolist()
                names = [entry.filename for entry in entries]
                if (
                    len(names) != len(set(names))
                    or len(names) > 10000
                    or not {"article.html", "manifest.json"} <= set(names)
                    or sum(e.file_size for e in entries) > self.config.max_upload_mb * 1024**2
                    or any(
                        not re.fullmatch(r"article\.html|manifest\.json|asset-\d+\.png", e.filename)
                        or (e.external_attr >> 16) & 0o170000 == 0o120000
                        for e in entries
                    )
                ):
                    raise HTTPException(422, "HTML 资源包不安全或超过大小限制")
                for entry in entries:
                    (raw / entry.filename).write_bytes(archive.read(entry))
            manifest = json.loads((raw / "manifest.json").read_text())
            if not isinstance(manifest.get("assets"), dict) or any(
                name != value or name not in names for name, value in manifest["assets"].items()
            ):
                raise HTTPException(422, "HTML 图片资源不完整")
            article = raw / "article.html"
            soup = BeautifulSoup(article.read_text(), "html.parser")
            for image in soup.find_all("img"):
                match = re.fullmatch(r"/paper-assets/[0-9a-f-]{36}/(asset-\d+\.png)", image.get("src", ""))
                if not match or match[1] not in manifest["assets"]:
                    raise HTTPException(422, "HTML 图片引用无效")
                image["src"] = match[1]
            article.write_text(str(soup))
            publish_html(article, clean, paper_id)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(clean, target)
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def reserve(self, session, paper, job, version=None):
        self.capture(session)
        version = version or (self.clock(session), self.device)
        self.record(session, f"html/{paper.id}", {"digest": None, "pdf_sha256": paper.pdf_sha256}, version)
        job.settings = {**job.settings, "sync_generation": list(version)}

    def complete(self, session, paper, job, target):
        version = job.settings.get("sync_generation")
        if not version:
            version = self.clock(session), self.device
        value = {"digest": self.html_asset(target / "article.html"), "pdf_sha256": paper.pdf_sha256}
        record = self.record(session, f"html/{paper.id}", value, version, phase=1)
        if rank(record) != (*version, 1):
            return False
        session.merge(SyncBaseline(key=f"html/{paper.id}", value=value))
        return True

    def enqueue_remote(self, session, paper, force=False, attempt=1):
        if not self.config.sync_enabled or not self.config.sync_peer_url:
            raise HTTPException(409, "请先配置双机同步和 Ubuntu 地址")
        if not paper.pdf_path or not paper.pdf_sha256:
            raise HTTPException(409, "请先下载或导入 PDF")
        active = session.scalar(
            select(RemoteConversion).where(
                RemoteConversion.paper_id == paper.id, RemoteConversion.status.in_(["queued", "running"])
            )
        )
        if active:
            return active, False
        if (
            len(
                list(
                    session.scalars(
                        select(RemoteConversion).where(RemoteConversion.status.in_(["queued", "running"]))
                    )
                )
            )
            >= 30
        ):
            raise HTTPException(429, "远程转换队列已满")
        self.capture(session)
        version = self.clock(session), self.device
        identifier = uid()
        payload = {
            "id": identifier,
            "paper_id": paper.id,
            "pdf_sha256": paper.pdf_sha256,
            "mode": settings(session)["marker_mode"],
            "force_rebuild": force,
            "clock": version[0],
            "device": version[1],
            "canceled": False,
        }
        self.record(session, f"html/{paper.id}", {"digest": None, "pdf_sha256": paper.pdf_sha256}, version)
        job = RemoteConversion(id=identifier, paper_id=paper.id, payload=payload, attempt=attempt)
        session.add(job)
        session.commit()
        self.wake.set()
        return job, False

    def accept_conversion(self, session, request):
        if not self.config.sync_accept_conversions:
            raise HTTPException(409, "此设备未启用接收远程转换")
        identifier = str(request.id)
        receipt = session.get(PeerReceipt, identifier)
        payload = request.model_dump(mode="json")
        if receipt and any(receipt.payload[k] != payload[k] for k in payload if k != "canceled"):
            raise HTTPException(409, "转换请求 ID 已被其他参数使用")
        paper_id = self.local_id(session, "paper", str(request.paper_id))
        paper = session.get(Paper, paper_id)
        if not receipt:
            receipt = PeerReceipt(id=identifier, paper_id=paper_id, payload=payload)
            session.add(receipt)
        if request.canceled:
            receipt.canceled = True
            session.commit()  # A cancellation tombstone also covers a request not delivered yet.
        job = session.get(Job, receipt.job_id or identifier)
        if receipt.canceled:
            if job:
                self.worker.cancel(session, job)
            return {
                "id": identifier,
                "status": "canceled",
                "progress_stage": "complete",
                "error_message": None,
            }
        if not paper or paper.pdf_sha256 != request.pdf_sha256 or not paper.pdf_path:
            raise HTTPException(409, "等待论文 PDF 同步完成")
        if not job:
            if session.scalar(
                select(Job).where(Job.paper_id == paper.id, Job.status.in_(["queued", "running"]))
            ):
                raise HTTPException(429, "请等待此论文当前的本机转换完成")
            job, cached = self.worker.enqueue(
                session,
                paper,
                request.force_rebuild,
                mode=request.mode,
                job_id=identifier,
                sync_generation=(request.clock, str(request.device)),
            )
            receipt = session.get(PeerReceipt, identifier)
            receipt.job_id = job.id
            if cached and job.result_path:
                # Reuse bytes while publishing them under this new request's generation.
                value = {
                    "digest": self.html_asset(self.config.path(job.result_path)),
                    "pdf_sha256": paper.pdf_sha256,
                }
                self.record(session, f"html/{paper.id}", value, (request.clock, str(request.device)), phase=1)
        session.commit()
        result = job_dict(job)
        result["id"] = identifier
        return result

    def receive_asset(self, kind, digest, stage):
        if hashlib.sha256(stage.read_bytes()).hexdigest() != digest:
            raise HTTPException(422, "资源校验失败")
        if kind == "pdf":
            validate_pdf(stage)
        target = self.blob_path(kind, digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(stage, target)

    def http(self, client, method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        return response

    def once(self):
        if not self.config.sync_enabled or not self.transfer_lock.acquire(blocking=False):
            return
        try:
            with self.worker.lock, self.lock, self.sessions() as session:
                outgoing = self.snapshot(session)
                session.commit()
            if not self.config.sync_peer_url:
                return
            with httpx.Client(
                base_url=self.config.sync_peer_url,
                timeout=30,
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
                headers={"Authorization": "Bearer " + self.config.sync_token.get_secret_value()},
            ) as client:
                response = self.http(client, "POST", "/peer/v1/exchange", json=outgoing).json()
                incoming = Snapshot.model_validate(response["snapshot"])
                with self.worker.lock, self.lock, self.sessions() as session:
                    self.merge(session, incoming)
                    for job in session.scalars(
                        select(RemoteConversion).where(RemoteConversion.progress_stage == "downloading")
                    ):
                        paper = session.get(Paper, job.paper_id)
                        winner = self.winners(session).get(f"html/{job.paper_id}")
                        expected = job.payload["clock"], job.payload["device"]
                        if winner and rank(winner)[:2] > expected:
                            job.status, job.progress_stage, job.finished_at = "succeeded", "superseded", now()
                        elif (
                            winner
                            and rank(winner) == (*expected, 1)
                            and winner.value
                            and winner.value.get("digest")
                            and paper
                            and paper.pdf_sha256 == winner.value.get("pdf_sha256") == job.payload["pdf_sha256"]
                            # materialize_assets points here only after the verified
                            # archive has been installed; an older HTML may still exist.
                            and paper.html_path
                            == f"papers/{paper.id}/derivatives/peer/{winner.value['digest']}/article.html"
                            and self.config.path(paper.html_path).is_file()
                        ):
                            job.status, job.progress_stage, job.finished_at = "succeeded", "complete", now()
                    self.commit(session)
                for asset in response["needed"]:
                    if self.stop_event.is_set():
                        return
                    descriptor = Asset.model_validate(asset)
                    with self.sessions() as session:
                        path = self.asset_path(session, descriptor.kind, descriptor.digest)
                    if path:
                        with path.open("rb") as stream:
                            self.http(
                                client,
                                "PUT",
                                f"/peer/v1/assets/{descriptor.kind}/{descriptor.digest}",
                                content=stream,
                                headers={"Content-Type": "application/octet-stream"},
                            )
                self.download_assets(client, incoming.assets)
                self.process_requests(client)
                # Re-read after task acceptance/completion, so ready HTML and its
                # generation travel together, including a cached conversion.
                response = self.http(client, "GET", "/peer/v1/snapshot").json()
                incoming = Snapshot.model_validate(response)
                self.download_assets(client, incoming.assets)
                with self.worker.lock, self.lock, self.sessions() as session:
                    self.merge(session, incoming)
                    self.commit(session)
                self.folders.request()
                self.online, self.error, self.last_success = True, None, now()
        finally:
            self.transfer_lock.release()

    def download_assets(self, client, assets):
        for asset in assets:
            if self.stop_event.is_set():
                return
            with self.sessions() as session:
                if self.asset_path(session, asset.kind, asset.digest):
                    continue
            if asset.size > self.config.max_upload_mb * 1024**2:
                raise HTTPException(413, "同步资源超过本机上传大小限制")
            stage = self.config.path("staging/peer-download-" + uid())
            stage.parent.mkdir(parents=True, exist_ok=True)
            try:
                with client.stream("GET", f"/peer/v1/assets/{asset.kind}/{asset.digest}") as response:
                    response.raise_for_status()
                    size = 0
                    with stage.open("wb") as output:
                        for chunk in response.iter_bytes(1024 * 1024):
                            size += len(chunk)
                            if size > self.config.max_upload_mb * 1024**2:
                                raise HTTPException(413, "同步资源超过大小限制")
                            output.write(chunk)
                self.receive_asset(asset.kind, asset.digest, stage)
            finally:
                stage.unlink(missing_ok=True)

    def process_requests(self, client):
        with self.sessions() as session:
            identifiers = list(
                session.scalars(
                    select(RemoteConversion.id).where(RemoteConversion.status.in_(["queued", "running"]))
                )
            )
        for identifier in identifiers:
            if self.stop_event.is_set():
                return
            with self.sessions() as session:
                job = session.get(RemoteConversion, identifier)
                if not job:
                    continue
                payload = {**job.payload, "canceled": job.cancel_requested}
            response = client.post("/peer/v1/conversions", json=payload)
            if response.status_code in (409, 429, 503):
                with self.sessions() as session:
                    job = session.get(RemoteConversion, identifier)
                    if job:
                        job.error_message = "Ubuntu 暂时无法接收任务，请检查 PDF 同步、队列和 Marker 配置。"
                        session.commit()
                continue
            response.raise_for_status()
            result = response.json()
            with self.sessions() as session:
                job = session.get(RemoteConversion, identifier)
                if not job:
                    continue
                job.status = "running" if result["status"] == "succeeded" else result["status"]
                job.progress_stage = (
                    "downloading"
                    if result["status"] == "succeeded"
                    else result.get("progress_stage", "waiting")
                )
                job.error_message = result.get("error_message")
                if job.status in ("succeeded", "failed", "canceled"):
                    job.finished_at = result.get("finished_at") or now()
                session.commit()
