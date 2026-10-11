"""Add bibliographic information without changing existing library records."""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("doi", "venue", "venue_kind", "metadata_error"):
        op.add_column("papers", sa.Column(name, sa.String()))
    for name, default in (("affiliations", "[]"), ("metadata_sources", "{}"), ("metadata_candidates", "[]")):
        op.add_column("papers", sa.Column(name, sa.JSON(), nullable=False, server_default=default))
    # Earlier versions did not record manual edits. Protect populated fields of
    # existing records instead of assuming they are safe to overwrite.
    op.execute(
        'UPDATE papers SET metadata_sources = \'{"title":"legacy","authors":"legacy","abstract":"legacy","year":"legacy"}\''
    )


def downgrade():
    raise RuntimeError("Destructive downgrade disabled. Restore a verified backup instead.")
