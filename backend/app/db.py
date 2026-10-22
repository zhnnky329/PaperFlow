import uuid
import unicodedata
from datetime import datetime, timezone
from sqlalchemy import (
    JSON,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    create_engine,
    event,
    func,
)
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
    name = Column(String, nullable=False)
    parent_id = Column(String, ForeignKey("collections.id", ondelete="CASCADE"))
    name_key = Column(String, nullable=False)
    __table_args__ = (
        Index("uq_collections_parent_name", func.coalesce(parent_id, ""), name_key, unique=True),
    )


@event.listens_for(Collection, "before_insert")
@event.listens_for(Collection, "before_update")
def collection_name_key(mapper, connection, collection):
    collection.name_key = unicodedata.normalize("NFC", collection.name).casefold()


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


class DiscoveryPaper(Base):
    __tablename__ = "discovery_papers"
    id = Column(String, primary_key=True, default=uid)
    arxiv_id = Column(String, unique=True, nullable=False)
    arxiv_aliases = Column(JSON, nullable=False, default=list)
    arxiv_version = Column(Integer, nullable=False, default=0)
    doi = Column(String, index=True)
    title = Column(String, nullable=False)
    authors = Column(JSON, nullable=False, default=list)
    abstract = Column(String, nullable=False, default="")
    categories = Column(JSON, nullable=False, default=list)
    published_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    source_url = Column(String, nullable=False)
    venue = Column(String)
    content_hash = Column(String, nullable=False)
    analysis_status = Column(String, nullable=False, default="pending")
    analysis = Column(JSON)
    analyzed_hash = Column(String)
    analyzed_at = Column(String)
    analysis_error = Column(String)
    feedback = Column(String, nullable=False, default="none")
    paper_id = Column(String, ForeignKey("papers.id", ondelete="SET NULL"))
    first_seen_at = Column(String, nullable=False, default=now)
    last_seen_at = Column(String, nullable=False, default=now)
    recommendation_run_id = Column(String)


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"
    id = Column(String, primary_key=True, default=uid)
    status = Column(String, nullable=False, default="queued")
    trigger = Column(String, nullable=False)
    stage = Column(String, nullable=False, default="waiting")
    options = Column(JSON, nullable=False, default=dict)
    fetched_count = Column(Integer, nullable=False, default=0)
    new_count = Column(Integer, nullable=False, default=0)
    analyzed_count = Column(Integer, nullable=False, default=0)
    recommended_count = Column(Integer, nullable=False, default=0)
    tokens_used = Column(Integer, nullable=False, default=0)
    tokens_reserved = Column(Integer, nullable=False, default=0)
    error_code = Column(String)
    error_message = Column(String)
    created_at = Column(String, nullable=False, default=now)
    started_at = Column(String)
    finished_at = Column(String)


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
