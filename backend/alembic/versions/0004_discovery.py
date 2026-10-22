"""Add an independent discovery pool without rewriting existing user tables."""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    op.create_table(
        "discovery_papers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("arxiv_id", sa.String(), nullable=False, unique=True),
        sa.Column("arxiv_aliases", sa.JSON(), nullable=False),
        sa.Column("arxiv_version", sa.Integer(), nullable=False),
        sa.Column("doi", sa.String()),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("authors", sa.JSON(), nullable=False),
        sa.Column("abstract", sa.String(), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("venue", sa.String()),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("analysis_status", sa.String(), nullable=False),
        sa.Column("analysis", sa.JSON()),
        sa.Column("analyzed_hash", sa.String()),
        sa.Column("analyzed_at", sa.String()),
        sa.Column("analysis_error", sa.String()),
        sa.Column("feedback", sa.String(), nullable=False),
        sa.Column("paper_id", sa.String(), sa.ForeignKey("papers.id", ondelete="SET NULL")),
        sa.Column("first_seen_at", sa.String(), nullable=False),
        sa.Column("last_seen_at", sa.String(), nullable=False),
        sa.Column("recommendation_run_id", sa.String()),
    )
    op.create_index("ix_discovery_papers_doi", "discovery_papers", ["doi"])
    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        *[
            sa.Column(name, sa.Integer(), nullable=False)
            for name in (
                "fetched_count",
                "new_count",
                "analyzed_count",
                "recommended_count",
                "tokens_used",
                "tokens_reserved",
            )
        ],
        sa.Column("error_code", sa.String()),
        sa.Column("error_message", sa.String()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("started_at", sa.String()),
        sa.Column("finished_at", sa.String()),
    )
    op.create_index(
        "uq_discovery_active",
        "discovery_runs",
        [sa.text("(1)")],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade():
    raise RuntimeError("Destructive downgrade disabled. Restore a verified backup instead.")
