"""watch_devices table for Connect IQ widget ingest

Revision ID: 002_watch_devices
Revises: 001_initial
Create Date: 2026-10-14
"""

from alembic import op
import sqlalchemy as sa

revision = "002_watch_devices"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watch_devices",
        sa.Column("device_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("label", sa.String(255)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_battery_pct", sa.Float),
    )


def downgrade() -> None:
    op.drop_table("watch_devices")
