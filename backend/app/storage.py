import hashlib
import os
import shutil
from pathlib import Path
from pypdf import PdfReader
from fastapi import HTTPException
from .db import uid


def validate_pdf(path: Path):
    try:
        with path.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise ValueError("PDF signature missing")
            stream.seek(0)
            reader = PdfReader(stream, strict=True)
            if reader.is_encrypted or not len(reader.pages):
                raise ValueError("Empty or encrypted PDF")
            title = str((reader.metadata or {}).get("/Title", "")).strip()
            author = str((reader.metadata or {}).get("/Author", "")).strip()
        return title[:1000], [author[:500]] if author else []
    except Exception as exc:
        raise HTTPException(422, "PDF 无法解析，可能已损坏、加密或不是真实 PDF") from exc


def ingest(config, session, source: Path, filename: str, paper=None):
    from sqlalchemy import select
    from .db import Paper

    title, authors = validate_pdf(source)
    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    existing = session.scalar(select(Paper).where(Paper.pdf_sha256 == digest))
    if existing:
        return existing, True
    paper = paper or Paper(id=uid(), title=title or Path(filename).stem[:1000] or "Untitled", authors=authors)
    relative = f"papers/{paper.id}/original.pdf"
    target = config.path(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, target)
    paper.pdf_path, paper.pdf_sha256 = relative, digest
    session.add(paper)
    try:
        session.commit()
    except Exception:
        session.rollback()
        target.unlink(missing_ok=True)
        raise
    return paper, False


def delete_assets(config, paper_id):
    path = config.path(f"papers/{paper_id}")
    if path.exists():
        shutil.rmtree(path)
