"""Reconcile Finder classifications without replacing canonical paper assets."""

import hashlib
import json
import os
import re
import stat
import threading
import time
import unicodedata
from contextlib import ExitStack
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select

from .db import Collection, Paper, Setting, paper_collections, uid
from .storage import ingest


class FolderConflict(ValueError):
    pass


class FolderPending(Exception):
    """A Finder copy/rename is still in progress; retry without applying it."""


def folder_name(value):
    name = unicodedata.normalize("NFC", value.strip())
    if not name or name in (".", "..") or re.search(r"[/\\:\x00-\x1f\x7f]", name) or name.startswith("."):
        raise FolderConflict("文件夹名称不能包含 /、\\、冒号、控制字符，也不能以点开头")
    if len(name) > 80:
        raise FolderConflict("文件夹名称不能超过 80 个字符")
    return name


def signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


class Directory:
    """Directory-relative, no-follow I/O; paths are only used for display."""

    def __init__(self, name, parent=None):
        self.name, self.parent = name, parent
        self.fd = os.open(
            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent.fd if parent else None
        )
        self.identity = signature(os.fstat(self.fd))[:2]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        os.close(self.fd)

    def check(self):
        if self.parent:
            self.parent.check()
            try:
                info = os.stat(self.name, dir_fd=self.parent.fd, follow_symlinks=False)
            except FileNotFoundError:
                raise FolderPending() from None
            if not stat.S_ISDIR(info.st_mode) or signature(info)[:2] != self.identity:
                raise FolderPending()

    def info(self, name):
        return os.stat(name, dir_fd=self.fd, follow_symlinks=False)

    def read(self, name, limit):
        self.check()
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise FolderConflict(f"{name} 超过大小限制或不是普通文件")
            data = stream.read(limit + 1)
            if len(data) > limit:
                raise FolderConflict(f"{name} 超过大小限制")
            if signature(before) != signature(os.fstat(stream.fileno())):
                raise FolderPending()
            return data

    def write_manifest(self, data):
        self.check()
        temporary = ".paperflow-" + uid() + ".tmp"
        try:
            fd = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd
            )
            with os.fdopen(fd, "w") as stream:
                json.dump(data, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            self.check()
            os.replace(temporary, ".paperflow.json", src_dir_fd=self.fd, dst_dir_fd=self.fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=self.fd)
            except FileNotFoundError:
                pass


class FolderSync:
    def __init__(self, config, sessions, lock=None):
        self.config, self.sessions = config, sessions
        self.lock = lock or threading.RLock()
        self.event, self.stopping = threading.Event(), threading.Event()
        self.thread = None
        self.on_import = lambda paper_id: None
        self.new_papers = set()
        self.cache, self.observed = {}, {}
        self.rejected = {}

    @property
    def root(self):
        path = self.config.data_dir / "folders"
        if path.is_symlink():
            raise FolderConflict("文件夹根目录不能是符号链接")
        return path

    def directory(self, collection):
        try:
            name = folder_name(collection.name)
        except FolderConflict:
            name = "Folder-" + collection.id
        return self.config.data_dir / "folders" / name

    def state(self, value):
        with self.sessions() as session:
            row = session.get(Setting, "folder_sync")
            if not row or row.value != value:
                session.merge(Setting(key="folder_sync", value=value))
                session.commit()

    def request(self, retry=False):
        if not self.stopping.is_set():
            if retry:
                self.rejected.clear()
            self.state({"status": "queued", "error": None})
            self.event.set()

    def start(self):
        self.thread = threading.Thread(target=self.run, name="finder-folders", daemon=True)
        self.thread.start()
        self.request()

    def stop(self):
        self.stopping.set()
        self.event.set()
        if self.thread:
            self.thread.join()

    def run(self):
        while not self.stopping.is_set():
            explicit = self.event.wait(2)
            self.event.clear()
            if self.stopping.is_set():
                break
            if explicit:
                self.state({"status": "running", "error": None})
            try:
                self.sync()
                self.state({"status": "succeeded", "error": None})
            except (FolderPending, FileNotFoundError):
                self.state({"status": "queued", "error": None})
            except FolderConflict as exc:
                self.state({"status": "failed", "error": str(exc)})
            except Exception:
                self.state(
                    {
                        "status": "failed",
                        "error": "Finder 同步失败，请检查磁盘空间和目录权限后重试。原始 PDF 仍可阅读。",
                    }
                )
            finally:
                for paper_id in list(self.new_papers):
                    try:
                        self.on_import(paper_id)
                        self.new_papers.discard(paper_id)
                    except Exception:
                        self.state(
                            {"status": "failed", "error": "Finder 导入已保存，但后台识别未启动，请重试同步。"}
                        )

    def manifest(self, directory):
        with Directory(str(self.config.data_dir.resolve())) as base, Directory("folders", base) as root:
            with Directory(Path(directory).name, root) as handle:
                return self.read_manifest(handle)

    def read_manifest(self, directory):
        try:
            data = json.loads(directory.read(".paperflow.json", 2_000_000))
            UUID(data["id"])
            for filename, checksum in data["files"].items():
                if (
                    Path(filename).name != filename
                    or filename.startswith(".")
                    or not filename.lower().endswith(".pdf")
                    or not re.fullmatch(r"[a-f0-9]{64}", checksum)
                ):
                    raise ValueError()
            for filename, paper_id in data.get("papers", {}).items():
                UUID(paper_id)
                if filename not in data["files"]:
                    raise ValueError()
            return data
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise FolderConflict("目录缺少有效的 PaperFlow 管理记录，未修改文件") from exc

    def scan(self, root, stack):
        result, cache, observed = {}, {}, {}
        entries = os.listdir(root.fd)
        if len(entries) > 5000:
            raise FolderConflict("Finder 根目录条目过多，请分批整理论文")
        for name in entries:
            if name.startswith("."):
                continue
            info = root.info(name)
            if stat.S_ISLNK(info.st_mode):
                raise FolderConflict("Finder 中发现符号链接，请移开链接后重试")
            if not stat.S_ISDIR(info.st_mode):
                continue
            folder_name(name)
            directory = stack.enter_context(Directory(name, root))
            names = os.listdir(directory.fd)
            if len(names) > 5000:
                raise FolderConflict(f"{name} 中文件过多，请分批整理论文")
            data = self.read_manifest(directory) if ".paperflow.json" in names else None
            files = {}
            for filename in names:
                if filename.startswith(".") or not filename.lower().endswith(".pdf"):
                    continue
                info = directory.info(filename)
                if not stat.S_ISREG(info.st_mode):
                    raise FolderConflict(f"{name}/{filename} 不是普通 PDF 文件，请移开后重试")
                if info.st_size > self.config.max_upload_mb * 1024 * 1024:
                    raise FolderConflict(f"{name}/{filename} 超过 PDF 大小限制")
                key, stamp = name + "/" + filename, signature(info)
                old = self.observed.get(key)
                since = old[1] if old and old[0] == stamp else time.monotonic()
                observed[key] = (stamp, since)
                cached = self.cache.get(key)
                if cached and cached[0] == stamp:
                    checksum = cached[1]
                else:
                    contents = directory.read(filename, self.config.max_upload_mb * 1024 * 1024)
                    checksum = hashlib.sha256(contents).hexdigest()
                cache[key] = (stamp, checksum)
                files[filename] = {"sha256": checksum, "stable": time.monotonic() - since >= 0.5}
            result[name] = {"handle": directory, "manifest": data, "files": files}
        self.cache, self.observed = cache, observed
        return result

    def stage_pdf(self, directory, filename, checksum):
        stage = self.config.path("staging/finder-" + uid() + ".pdf")
        stage.parent.mkdir(exist_ok=True)
        contents = directory.read(filename, self.config.max_upload_mb * 1024 * 1024)
        if hashlib.sha256(contents).hexdigest() != checksum:
            raise FolderPending()
        with stage.open("xb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        return stage

    def remove_owned(self, directory, filename, checksum):
        try:
            before = directory.info(filename)
            contents = directory.read(filename, self.config.max_upload_mb * 1024 * 1024)
        except FileNotFoundError:
            return
        if hashlib.sha256(contents).hexdigest() == checksum:
            if signature(directory.info(filename)) != signature(before):
                raise FolderPending()
            directory.check()
            os.unlink(filename, dir_fd=directory.fd)
            return True
        return False

    def publish(self, directory, filename, source, checksum):
        # Link only the new temporary copy, never the canonical PDF. Publishing
        # cannot overwrite a file created by Finder between the scan and write.
        temporary = ".paperflow-" + uid() + ".tmp"
        directory.check()
        try:
            fd = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory.fd
            )
            with source.open("rb") as incoming, os.fdopen(fd, "wb") as output:
                while chunk := incoming.read(1024 * 1024):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if (
                hashlib.sha256(directory.read(temporary, self.config.max_upload_mb * 1024 * 1024)).hexdigest()
                != checksum
            ):
                raise FolderConflict("原始 PDF 校验失败，未发布副本")
            directory.check()
            os.link(
                temporary, filename, src_dir_fd=directory.fd, dst_dir_fd=directory.fd, follow_symlinks=False
            )
        except FileExistsError as exc:
            raise FolderConflict("Finder 中的同名文件已存在，未覆盖；请改名后重试") from exc
        finally:
            try:
                os.unlink(temporary, dir_fd=directory.fd)
            except FileNotFoundError:
                pass

    def sync(self):
        with self.lock, self.sessions() as session, ExitStack() as stack:
            row = session.get(Setting, "folder_sync_baseline")
            baseline = (
                json.loads(json.dumps(row.value)) if row else {"folders": {}, "suppressed": [], "ignored": {}}
            )
            previous = baseline["folders"]
            if previous and not self.root.exists():
                raise FolderConflict("Finder 根目录已移走，请放回 folders 目录后重试；论文库未删除")
            base = stack.enter_context(Directory(str(self.config.data_dir.resolve())))
            try:
                os.mkdir("folders", dir_fd=base.fd)
            except FileExistsError:
                pass
            root = stack.enter_context(Directory("folders", base))
            scanned = self.scan(root, stack)
            collections = {c.id: c for c in session.scalars(select(Collection))}
            papers = {p.id: p for p in session.scalars(select(Paper))}
            known = {p.pdf_sha256: p for p in papers.values() if p.pdf_sha256}
            members = {c: set() for c in collections}
            for paper_id, collection_id in session.execute(select(paper_collections)):
                members[collection_id].add(paper_id)
            owned = {}
            for name, item in scanned.items():
                data = item["manifest"]
                if data:
                    if data["id"] in owned:
                        first = owned[data["id"]]
                        original = previous.get(data["id"], {}).get("name")
                        if not original and data["id"] in collections:
                            original = self.directory(collections[data["id"]]).name
                        if folder_name(first) == original:
                            item["manifest"] = None  # Finder duplicated a whole folder.
                            continue
                        if folder_name(name) == original:
                            scanned[first]["manifest"] = None
                        else:
                            raise FolderConflict(
                                "出现重复的文件夹管理记录，无法确定原目录，请移开重复目录后重试"
                            )
                    owned[data["id"]] = name
            # A folder copied from another PaperFlow library carries a foreign
            # manifest. It is an import, never evidence that we may delete it.
            for identifier, name in list(owned.items()):
                if identifier not in collections and identifier not in previous:
                    scanned[name]["manifest"] = None
                    owned.pop(identifier)
            suppressed = set(baseline.get("suppressed", [])) & set(scanned)
            ignored = dict(baseline.get("ignored", {}))
            deleted_hashes = {
                old["files"][filename]
                for old in previous.values()
                for filename, paper_id in old.get("papers", {}).items()
                if paper_id not in papers
            }
            for name, item in scanned.items():
                for filename, info in item["files"].items():
                    if info["sha256"] in deleted_hashes:
                        ignored[name + "/" + filename] = info["sha256"]
            mapping, removed = {}, set()
            for collection_id, collection in collections.items():
                old = previous.get(collection_id)
                actual = owned.get(collection_id)
                if old and actual is None:
                    if old["name"] in scanned:
                        raise FolderConflict("文件夹管理记录已移走，请恢复 .paperflow.json 后重试")
                    if collection.name != old["name"] or members[collection_id] != set(old["members"]):
                        raise FolderConflict("应用与 Finder 同时修改了文件夹，请恢复 Finder 目录后重试")
                    removed.add(collection_id)
                    continue
                if actual:
                    mapping[collection_id] = actual
                    actual_name = folder_name(actual)
                    if old and actual_name != old["name"]:
                        if collection.name not in (old["name"], actual_name):
                            raise FolderConflict("应用与 Finder 同时改名，请统一文件夹名称后重试")
                        if any(
                            c.id != collection_id and c.name.casefold() == actual_name.casefold()
                            for c in collections.values()
                        ):
                            raise FolderConflict("Finder 改名与已有分类同名，请重新命名后重试")
                        collection.name = actual_name
            for collection_id in removed:
                session.delete(collections[collection_id])
                collections.pop(collection_id)
                members.pop(collection_id)
            orphan_names = {name for identifier, name in owned.items() if identifier not in collections}
            orphan_names |= {
                old["name"]
                for identifier, old in previous.items()
                if identifier not in collections and old["name"] in scanned
            }
            for name, item in scanned.items():
                if name in orphan_names or name in mapping.values():
                    continue
                matching = next(
                    (
                        c
                        for c in collections.values()
                        if self.directory(c).name.casefold() == folder_name(name).casefold()
                    ),
                    None,
                )
                if name in suppressed and not matching:
                    continue
                if matching:
                    if matching.id in mapping:
                        raise FolderConflict("Finder 中有大小写或字符规范化后同名的文件夹，请重新命名")
                    mapping[matching.id] = name
                else:
                    collection = Collection(id=uid(), name=folder_name(name))
                    session.add(collection)
                    collections[collection.id], members[collection.id] = collection, set()
                    mapping[collection.id] = name
                suppressed.discard(name)
            # Upgrade old manifests conservatively: do not treat their missing
            # copies as Finder deletions until a complete baseline is established.
            for collection_id, name in mapping.items():
                if collection_id not in previous:
                    item = scanned[name]
                    data = item["manifest"] or {"files": {}}
                    tracked = {f: h for f, h in data["files"].items() if f in item["files"] and h in known}
                    previous[collection_id] = {
                        "files": tracked,
                        "papers": {f: known[h].id for f, h in tracked.items()},
                        "members": [],
                        "name": name,
                    }
            for collection_id, name in mapping.items():
                old = previous[collection_id]
                for filename, info in scanned[name]["files"].items():
                    key = name + "/" + filename
                    if ignored.get(key) == info["sha256"]:
                        continue
                    expected, paper_id = old["files"].get(filename), old["papers"].get(filename)
                    if expected and expected != info["sha256"] and paper_id in members[collection_id]:
                        raise FolderConflict(
                            f"{name}/{filename} 内容已修改，原文未覆盖；请将修改版另存为新文件名后重试"
                        )
                    if info["sha256"] not in known and not info["stable"]:
                        if paper_id and paper_id not in members[collection_id]:
                            continue
                        raise FolderPending()
            session.flush()
            for collection_id, name in mapping.items():
                item, old = scanned[name], previous[collection_id]
                found = set()
                for filename, info in item["files"].items():
                    key, checksum = name + "/" + filename, info["sha256"]
                    if ignored.get(key) == checksum:
                        continue
                    prior_id = old["papers"].get(filename)
                    if prior_id and prior_id not in members[collection_id]:
                        continue
                    paper = known.get(checksum)
                    if not paper:
                        if checksum in self.rejected:
                            raise FolderConflict(f"{name}/{filename} 无法导入：{self.rejected[checksum]}")
                        stage = self.stage_pdf(item["handle"], filename, checksum)
                        try:
                            paper, duplicate = ingest(self.config, session, stage, filename)
                        except HTTPException as exc:
                            self.rejected = {checksum: exc.detail}
                            raise FolderConflict(f"{name}/{filename} 无法导入：{exc.detail}") from exc
                        finally:
                            stage.unlink(missing_ok=True)
                        known[checksum], papers[paper.id] = paper, paper
                        if not duplicate:
                            self.new_papers.add(paper.id)
                    found.add(paper.id)
                    if paper.id in old["members"] and paper.id not in members[collection_id]:
                        ignored[key] = checksum
                    if paper.id not in members[collection_id] and paper.id not in old["members"]:
                        session.execute(
                            paper_collections.insert().values(paper_id=paper.id, collection_id=collection_id)
                        )
                        members[collection_id].add(paper.id)
                for paper_id in set(old["papers"].values()) - found:
                    if paper_id in members[collection_id]:
                        session.execute(
                            delete(paper_collections).where(
                                paper_collections.c.paper_id == paper_id,
                                paper_collections.c.collection_id == collection_id,
                            )
                        )
                        members[collection_id].remove(paper_id)
            session.commit()
            result = {}
            for collection_id, collection in collections.items():
                target, actual = self.directory(collection).name, mapping.get(collection_id)
                if actual:
                    item, directory = scanned[actual], scanned[actual]["handle"]
                    if actual != target:
                        directory.check()
                        if target in scanned and scanned[target] is not item:
                            raise FolderConflict("同名 Finder 目录已经存在，请重新命名分类后重试")
                        os.rename(actual, target, src_dir_fd=root.fd, dst_dir_fd=root.fd)
                        directory.name = target
                        for key in list(ignored):
                            if key.startswith(actual + "/"):
                                ignored[target + key[len(actual) :]] = ignored.pop(key)
                else:
                    os.mkdir(target, dir_fd=root.fd)
                    directory = stack.enter_context(Directory(target, root))
                    item = {"files": {}, "manifest": None, "handle": directory}
                data = item["manifest"] or {"files": {}}
                wanted, file_ids = {}, {}
                for filename, info in item["files"].items():
                    paper = known.get(info["sha256"])
                    key = target + "/" + filename
                    if paper and paper.id in members[collection_id] and ignored.get(key) != info["sha256"]:
                        wanted[filename], file_ids[filename] = info["sha256"], paper.id
                for paper_id in members[collection_id] - set(file_ids.values()):
                    paper = papers[paper_id]
                    if not paper.pdf_path:
                        continue
                    source = self.config.path(paper.pdf_path)
                    if not source.is_file():
                        continue
                    title = re.sub(r"[/\\:\x00-\x1f\x7f]", "_", paper.title).strip(". ")[:90] or "Paper"
                    while len(title.encode("utf-8")) > 170:
                        title = title[:-1]
                    filename = title + "--" + paper.id + ".pdf"
                    data["files"][filename] = paper.pdf_sha256
                    directory.write_manifest({**data, "id": collection_id})
                    self.publish(directory, filename, source, paper.pdf_sha256)
                    wanted[filename], file_ids[filename] = paper.pdf_sha256, paper_id
                for filename, checksum in data["files"].items():
                    if filename not in wanted:
                        if self.remove_owned(directory, filename, checksum):
                            item["files"].pop(filename, None)
                            ignored.pop(target + "/" + filename, None)
                            continue
                        try:
                            leftover = hashlib.sha256(
                                directory.read(filename, self.config.max_upload_mb * 1024 * 1024)
                            ).hexdigest()
                            ignored[target + "/" + filename] = leftover
                            item["files"][filename] = {"sha256": leftover, "stable": True}
                        except FileNotFoundError:
                            pass
                record = {
                    "id": collection_id,
                    "name": target,
                    "files": wanted,
                    "papers": file_ids,
                    "members": sorted(members[collection_id]),
                }
                if item["manifest"] != record:
                    directory.write_manifest(record)
                result[collection_id] = record
            for name in orphan_names:
                item = scanned[name]
                directory, data = item["handle"], item["manifest"]
                if data:
                    for filename, checksum in data["files"].items():
                        if self.remove_owned(directory, filename, checksum):
                            item["files"].pop(filename, None)
                    directory.check()
                    os.unlink(".paperflow.json", dir_fd=directory.fd)
                if not os.listdir(directory.fd):
                    directory.check()
                    os.rmdir(name, dir_fd=root.fd)
                else:
                    suppressed.add(name)
            # Ignore only preserved copies that still exist unchanged. A later
            # deliberate re-add after removal can then be imported normally.
            handles = {item["handle"].name: item for item in scanned.values()}
            for key, checksum in list(ignored.items()):
                name, filename = key.split("/", 1)
                item = handles.get(name)
                if not item or item["files"].get(filename, {}).get("sha256") != checksum:
                    ignored.pop(key)
            updated = {"folders": result, "suppressed": sorted(suppressed), "ignored": ignored}
            if baseline != updated:
                session.merge(Setting(key="folder_sync_baseline", value=updated))
                session.commit()
