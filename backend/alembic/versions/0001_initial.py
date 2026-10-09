"""Initial durable local library. Never drop data on startup."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "papers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("authors", sa.JSON(), nullable=False),
        sa.Column("abstract", sa.String(), nullable=False),
        sa.Column("year", sa.Integer()),
        sa.Column("arxiv_id", sa.String()),
        sa.Column("arxiv_version", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.String()),
        sa.Column("official_html_url", sa.String()),
        sa.Column("pdf_path", sa.String()),
        sa.Column("pdf_sha256", sa.String(), unique=True),
        sa.Column("html_path", sa.String()),
        sa.Column("read_status", sa.String(), nullable=False),
        sa.Column("metadata_status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("last_read_at", sa.String()),
        sa.UniqueConstraint("arxiv_id", "arxiv_version"),
    )
    for name in ("tags", "collections"):
        op.create_table(
            name,
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(), unique=True, nullable=False),
        )
    for kind in ("tags", "collections"):
        op.create_table(
            "paper_" + kind,
            sa.Column(
                "paper_id", sa.String(), sa.ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
            ),
            sa.Column(
                kind[:-1] + "_id",
                sa.String(),
                sa.ForeignKey(kind + ".id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )
    op.create_table(
        "conversion_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("paper_id", sa.String(), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("progress_stage", sa.String(), nullable=False),
        sa.Column("result_path", sa.String()),
        sa.Column("error_code", sa.String()),
        sa.Column("error_message", sa.String()),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("started_at", sa.String()),
        sa.Column("finished_at", sa.String()),
    )
    op.create_table(
        "reading_positions",
        sa.Column("paper_id", sa.String(), sa.ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("mode", sa.String(), primary_key=True),
        sa.Column("pdf_page", sa.Integer()),
        sa.Column("pdf_scale", sa.Float()),
        sa.Column("html_anchor", sa.String()),
        sa.Column("scroll_ratio", sa.Float()),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
    )


def downgrade():
    raise RuntimeError("Destructive downgrade disabled. Restore a verified backup instead.")
