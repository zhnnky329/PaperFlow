"""One-way Finder mirrors. SQLite/canonical PDFs remain authoritative."""

import hashlib
import json
import os
import re
import shutil
import threading
import unicodedata
from pathlib import Path
from sqlalchemy import select
from .db import Collection, Paper, Setting, paper_collections, uid


class FolderConflict(ValueError):
    pass


def folder_name(value):
    name = unicodedata.normalize("NFC", value.strip())
    if not name or name in (".", "..") or re.search(r"[/\\:\x00-\x1f\x7f]", name) or name.startswith("."):
        raise FolderConflict("文件夹名称不能包含 /、\\、冒号、控制字符，也不能以点开头")
    if len(name) > 80:
        raise FolderConflict("文件夹名称不能超过 80 个字符")
    return name


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class FolderSync:
    def __init__(self, config, sessions):
        self.config, self.sessions = config, sessions
        self.event, self.stopping = threading.Event(), threading.Event()
        self.thread = None

    @property
    def root(self):
        path = self.config.data_dir / "folders"
        if path.is_symlink():
            raise FolderConflict("文件夹根目录不能是符号链接")
        return path

    def directory(self, collection):
        # Old Collections may contain names that predate filesystem validation.
        try:
            name = folder_name(collection.name)
        except FolderConflict:
            name = "Folder-" + collection.id
        return self.config.data_dir / "folders" / name

    def state(self, value):
        with self.sessions() as session:
            session.merge(Setting(key="folder_sync", value=value))
            session.commit()

    def request(self):
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
            self.event.wait()
            self.event.clear()
            if self.stopping.is_set():
                break
            self.state({"status": "running", "error": None})
            try:
                self.sync()
                self.state({"status": "succeeded", "error": None})
            except FolderConflict as exc:
                self.state({"status": "failed", "error": str(exc)})
            except Exception:
                self.state(
                    {
                        "status": "failed",
                        "error": "Finder 文件夹同步失败；请检查磁盘空间和目录权限后重试。原始 PDF 仍可阅读。",
                    }
                )

    def manifest(self, directory):
        path = directory / ".paperflow.json"
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            raise FolderConflict("目录缺少有效的 PaperFlow 管理记录，未覆盖其内容")
        data = json.loads(path.read_text())
        from uuid import UUID

        UUID(data["id"])
        for filename, checksum in data["files"].items():
            if (
                Path(filename).name != filename
                or not filename.endswith(".pdf")
                or not re.fullmatch(r"[a-f0-9]{64}", checksum)
            ):
                raise FolderConflict("文件夹管理记录无效，未修改文件")
        return data

    def write_manifest(self, directory, data):
        stage = directory / (".paperflow-" + uid() + ".tmp")
        try:
            stage.write_text(json.dumps(data, ensure_ascii=False))
            os.replace(stage, directory / ".paperflow.json")
        finally:
            stage.unlink(missing_ok=True)

    def remove_owned(self, directory, filename, checksum):
        path = directory / filename
        if path.is_symlink():
            raise FolderConflict("发现符号链接，未修改文件夹；请移开链接后重试")
        if path.is_file() and digest(path) == checksum:
            path.unlink()
        # A changed Finder copy belongs to the user and is deliberately preserved.

    def sync(self):
        root = self.root
        root.mkdir(parents=True, exist_ok=True)
        with self.sessions() as session:
            collections = list(session.scalars(select(Collection)))
            papers = {p.id: p for p in session.scalars(select(Paper))}
            memberships = list(session.execute(select(paper_collections)))
        owned = {}
        for directory in root.iterdir():
            if directory.is_symlink():
                continue
            if directory.is_dir() and (directory / ".paperflow.json").exists():
                data = self.manifest(directory)
                if data["id"] in owned:
                    raise FolderConflict("出现重复的文件夹管理记录，请移开重复目录后重试")
                owned[data["id"]] = (directory, data)
        for collection in collections:
            target = self.directory(collection)
            if target.is_symlink():
                raise FolderConflict("目标文件夹是符号链接，未写入；请移开链接后重试")
            previous = owned.pop(collection.id, None)
            if previous:
                directory, data = previous
                if directory != target:
                    if target.exists() and not directory.samefile(target):
                        raise FolderConflict("同名 Finder 目录已经存在，未覆盖；请移开该目录或重新命名分类")
                    directory.rename(target)
            else:
                if target.exists():
                    raise FolderConflict("同名 Finder 目录已经存在，未覆盖；请移开该目录或重新命名分类")
                target.mkdir()
                data = {"id": collection.id, "files": {}}
                self.write_manifest(target, data)
            wanted = {}
            for paper_id, collection_id in memberships:
                if collection_id != collection.id:
                    continue
                paper = papers.get(paper_id)
                if not paper or not paper.pdf_path:
                    continue
                source = self.config.path(paper.pdf_path)
                if not source.is_file():
                    continue
                title = re.sub(r"[/\\:\x00-\x1f\x7f]", "_", paper.title).strip(". ")[:90] or "Paper"
                while len(title.encode("utf-8")) > 170:
                    title = title[:-1]
                filename = title + "--" + paper.id + ".pdf"
                checksum = paper.pdf_sha256 or digest(source)
                destination = target / filename
                if destination.is_symlink():
                    raise FolderConflict("PDF 副本不能是符号链接，未覆盖")
                if destination.exists():
                    if filename not in data["files"] or digest(destination) != checksum:
                        raise FolderConflict(
                            "Finder 中的同名 PDF 已修改或不由 PaperFlow 管理；请移开该副本后重试"
                        )
                else:
                    staging = self.config.path("staging/folder-" + uid() + ".pdf")
                    staging.parent.mkdir(exist_ok=True)
                    try:
                        shutil.copyfile(source, staging)
                        if digest(staging) != checksum:
                            raise FolderConflict("原始 PDF 校验失败，未发布副本")
                        # Save ownership before publication so crash recovery can finish safely.
                        data["files"][filename] = checksum
                        self.write_manifest(target, data)
                        os.replace(staging, destination)
                    finally:
                        staging.unlink(missing_ok=True)
                wanted[filename] = checksum
            for filename, checksum in data["files"].items():
                if filename not in wanted:
                    self.remove_owned(target, filename, checksum)
            self.write_manifest(target, {"id": collection.id, "files": wanted})
        for directory, data in owned.values():
            for filename, checksum in data["files"].items():
                self.remove_owned(directory, filename, checksum)
            (directory / ".paperflow.json").unlink()
            if not any(directory.iterdir()):
                directory.rmdir()
