"""Durable peer changes, aliases, and remote conversion requests."""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    op.create_table(
        "sync_records",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.JSON()),
        sa.Column("clock", sa.Integer(), nullable=False),
        sa.Column("device", sa.String(), nullable=False),
        sa.Column("phase", sa.Integer(), nullable=False),
    )
    op.create_table(
        "sync_baselines", sa.Column("key", sa.String(), primary_key=True), sa.Column("value", sa.JSON())
    )
    op.create_table(
        "sync_aliases",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("local_id", sa.String(), nullable=False),
    )
    op.create_table(
        "remote_conversions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("paper_id", sa.String(), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("progress_stage", sa.String(), nullable=False),
        sa.Column("error_message", sa.String()),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String()),
    )
    op.create_table(
        "peer_receipts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String()),
        sa.Column("paper_id", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("canceled", sa.Boolean(), nullable=False),
    )


def downgrade():
    for name in ("peer_receipts", "remote_conversions", "sync_aliases", "sync_baselines", "sync_records"):
        op.drop_table(name)
