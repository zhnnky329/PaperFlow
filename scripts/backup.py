"""Stopped-server, checksummed SQLite+assets backup and safe empty-directory restore."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import Config  # noqa: E402


def backup(data_dir: Path, output: Path):
    data_dir = data_dir.resolve()
    if not (data_dir / "paperflow.sqlite3").is_file():
        raise ValueError("Data directory has no PaperFlow database")
    with (data_dir / "server.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Stop PaperFlow before backup") from exc
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            with sqlite3.connect(data_dir / "paperflow.sqlite3") as source:
                with sqlite3.connect(stage / "paperflow.sqlite3") as target:
                    source.backup(target)
            for name in ("papers", "folders"):
                directory = data_dir / name
                if directory.exists():
                    if directory.is_symlink() or any(file.is_symlink() for file in directory.rglob("*")):
                        raise ValueError("Symlink in library; backup refused")
                    shutil.copytree(directory, stage / name)
            checksums = {
                str(p.relative_to(stage)): hashlib.file_digest(p.open("rb"), "sha256").hexdigest()
                for p in stage.rglob("*")
                if p.is_file()
            }
            (stage / "backup-manifest.json").write_text(json.dumps({"version": 1, "sha256": checksums}))
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.exists():
                raise ValueError("Backup output already exists; choose a new filename")
            temp = output.with_suffix(".partial")
            try:
                with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
                    for file in stage.rglob("*"):
                        if file.is_file():
                            archive.write(file, str(file.relative_to(stage)))
                os.replace(temp, output)
            finally:
                temp.unlink(missing_ok=True)
    return output


def restore(archive_path: Path, target: Path):
    target = target.resolve()
    if target.exists():
        raise ValueError(
            "Restore requires a new, nonexistent target directory; existing data is never overwritten"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        stage = Path(tmp)
        with zipfile.ZipFile(archive_path) as archive:
            total = 0
            names = set()
            for item in archive.infolist():
                path = (stage / item.filename).resolve()
                if (
                    not path.is_relative_to(stage)
                    or item.filename.startswith("/")
                    or "\\" in item.filename
                    or item.filename in names
                    or ((item.external_attr >> 16) & 0o170000) == 0o120000
                ):
                    raise ValueError("Unsafe backup member")
                names.add(item.filename)
                total += item.file_size
                if total > 50 * 1024**3:
                    raise ValueError("Backup exceeds restore size limit")
                if item.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item) as source, path.open("wb") as output:
                        shutil.copyfileobj(source, output)
        manifest = json.loads((stage / "backup-manifest.json").read_text())
        if manifest.get("version") != 1:
            raise ValueError("Unsupported backup version")
        files = {str(p.relative_to(stage)) for p in stage.rglob("*") if p.is_file()} - {
            "backup-manifest.json"
        }
        if files != set(manifest["sha256"]):
            raise ValueError("Backup contents do not match manifest")
        for relative, checksum in manifest["sha256"].items():
            path = (stage / relative).resolve()
            if (
                not path.is_relative_to(stage)
                or hashlib.file_digest(path.open("rb"), "sha256").hexdigest() != checksum
            ):
                raise ValueError("Backup checksum mismatch")
        with sqlite3.connect(stage / "paperflow.sqlite3") as database:
            if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Database integrity check failed")
        (stage / "backup-manifest.json").unlink()
        os.replace(stage, target)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("--data-dir", type=Path, default=Config().data_dir)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--target", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "backup":
            destination = args.archive or args.data_dir / "backups" / (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".zip"
            )
            print(backup(args.data_dir, destination))
        else:
            if not args.archive or not args.target:
                parser.error("restore requires --archive and --target (new directory)")
            print(restore(args.archive, args.target))
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        print(f"Recovery error: {exc}", file=sys.stderr)
        sys.exit(1)
