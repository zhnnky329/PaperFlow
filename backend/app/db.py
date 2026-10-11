import uuid
from datetime import datetime, timezone
from sqlalchemy import JSON, Column, Float, ForeignKey, Integer, String, Table, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from alembic.config import Config as AlembicConfig
from alembic import command
from .config import ROOT


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


paper_tags = Table(
    "paper_tags",
    Base.metadata,
    Column("paper_id", ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)
paper_collections = Table(
    "paper_collections",
    Base.metadata,
    Column("paper_id", ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True),
    Column("collection_id", ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True),
)


class Paper(Base):
    __tablename__ = "papers"
    id = Column(String, primary_key=True, default=uid)
    title = Column(String, nullable=False)
    authors = Column(JSON, default=list, nullable=False)
    abstract = Column(String, default="", nullable=False)
    year = Column(Integer)
    arxiv_id = Column(String)
    arxiv_version = Column(Integer, nullable=False, default=0)  # 0 = latest; null uniqueness avoided
    source_url = Column(String)
    official_html_url = Column(String)
    pdf_path = Column(String)
    pdf_sha256 = Column(String, unique=True)
    html_path = Column(String)
    read_status = Column(String, nullable=False, default="unread")
    metadata_status = Column(String, nullable=False, default="local")
    doi = Column(String)
    venue = Column(String)
    venue_kind = Column(String)
    affiliations = Column(JSON, nullable=False, default=list)
    metadata_sources = Column(JSON, nullable=False, default=dict)
    metadata_candidates = Column(JSON, nullable=False, default=list)
    metadata_error = Column(String)
    created_at = Column(String, nullable=False, default=now)
    updated_at = Column(String, nullable=False, default=now)
    last_read_at = Column(String)


class Tag(Base):
    __tablename__ = "tags"
    id = Column(String, primary_key=True, default=uid)
    name = Column(String, unique=True, nullable=False)


class Collection(Base):
    __tablename__ = "collections"
    id = Column(String, primary_key=True, default=uid)
    name = Column(String, unique=True, nullable=False)


class Job(Base):
    __tablename__ = "conversion_jobs"
    id = Column(String, primary_key=True, default=uid)
    paper_id = Column(String, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False, default="queued")
    fingerprint = Column(String, nullable=False)
    settings = Column(JSON, nullable=False)
    progress_stage = Column(String, nullable=False, default="waiting")
    result_path = Column(String)
    error_code = Column(String)
    error_message = Column(String)
    attempt = Column(Integer, nullable=False, default=1)
    created_at = Column(String, nullable=False, default=now)
    started_at = Column(String)
    finished_at = Column(String)


class Position(Base):
    __tablename__ = "reading_positions"
    paper_id = Column(String, ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True)
    mode = Column(String, primary_key=True)
    pdf_page = Column(Integer, default=1)
    pdf_scale = Column(Float, default=1.0)
    html_anchor = Column(String, default="")
    scroll_ratio = Column(Float, default=0.0)
    updated_at = Column(String, nullable=False, default=now)


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(JSON, nullable=False)


def database(config):
    config.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        "sqlite:///" + str(config.data_dir / "paperflow.sqlite3"),
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def pragmas(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")

    alembic = AlembicConfig(str(ROOT / "backend/alembic.ini"))
    alembic.set_main_option("script_location", str(ROOT / "backend/alembic"))
    with engine.begin() as connection:
        alembic.attributes["connection"] = connection
        command.upgrade(alembic, "head")
    return engine, sessionmaker(engine, expire_on_commit=False)
