"""Preserve existing classifications while allowing nested collections."""

import unicodedata

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    # SQLite's legacy transaction mode does not begin a transaction for DDL.
    # Start one before rebuilding tables so a failed migration is reversible.
    if not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    rows = connection.execute(sa.text("SELECT id, name FROM collections")).mappings().all()
    op.create_table(
        "_paperflow_collection_links",
        sa.Column("paper_id", sa.String(), primary_key=True),
        sa.Column("collection_id", sa.String(), primary_key=True),
    )
    op.execute(
        "INSERT INTO _paperflow_collection_links SELECT paper_id, collection_id FROM paper_collections"
    )
    # Dropping collections with foreign_keys=ON would cascade away all links.
    # Save and detach the association table before replacing its parent.
    op.drop_table("paper_collections")
    op.create_table(
        "_paperflow_collections_new",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("name_key", sa.String(), nullable=False),
        sa.Column(
            "parent_id", sa.String(), sa.ForeignKey("_paperflow_collections_new.id", ondelete="CASCADE")
        ),
    )
    for row in rows:
        connection.execute(
            sa.text(
                "INSERT INTO _paperflow_collections_new (id, name, name_key) VALUES (:id, :name, :name_key)"
            ),
            dict(row) | {"name_key": unicodedata.normalize("NFC", row["name"]).casefold()},
        )
    op.drop_table("collections")
    op.rename_table("_paperflow_collections_new", "collections")
    op.create_index(
        "uq_collections_parent_name",
        "collections",
        [sa.text("coalesce(parent_id, '')"), "name_key"],
        unique=True,
    )
    op.create_table(
        "paper_collections",
        sa.Column("paper_id", sa.String(), sa.ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "collection_id",
            sa.String(),
            sa.ForeignKey("collections.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.execute(
        "INSERT INTO paper_collections SELECT paper_id, collection_id FROM _paperflow_collection_links"
    )
    op.drop_table("_paperflow_collection_links")


def downgrade():
    raise RuntimeError("Destructive downgrade disabled. Restore a verified backup instead.")
