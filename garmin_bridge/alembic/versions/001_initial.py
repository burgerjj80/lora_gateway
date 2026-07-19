"""initial schema + timescale hypertables

Revision ID: 001_initial
Revises:
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("display_name", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "wearable_accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
        sa.Column("provider", sa.String(32), index=True, nullable=False),
        sa.Column("provider_user_id", sa.String(128), index=True, nullable=False),
        sa.Column("access_token", sa.String(1024), nullable=False),
        sa.Column("access_token_secret", sa.String(1024)),
        sa.Column("scopes", sa.JSON),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disconnected_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_provider"),
    )

    op.create_table(
        "daily_summaries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
        sa.Column("day", sa.Date, index=True, nullable=False),
        sa.Column("steps", sa.Integer),
        sa.Column("distance_m", sa.Float),
        sa.Column("active_calories", sa.Integer),
        sa.Column("resting_hr", sa.Integer),
        sa.Column("avg_stress", sa.Integer),
        sa.Column("intensity_minutes", sa.Integer),
        sa.Column("raw", sa.JSON),
        sa.UniqueConstraint("user_id", "day", name="uq_user_day"),
    )

    op.create_table(
        "hr_samples",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
        sa.Column("ts", sa.DateTime(timezone=True), index=True, nullable=False),
        sa.Column("bpm", sa.Integer, nullable=False),
    )
    op.execute("SELECT create_hypertable('hr_samples', 'ts', if_not_exists => TRUE)")

    op.create_table(
        "sleep_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
        sa.Column("start_ts", sa.DateTime(timezone=True), index=True, nullable=False),
        sa.Column("end_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deep_s", sa.Integer),
        sa.Column("light_s", sa.Integer),
        sa.Column("rem_s", sa.Integer),
        sa.Column("awake_s", sa.Integer),
        sa.Column("score", sa.Integer),
        sa.Column("raw", sa.JSON),
    )

    op.create_table(
        "stress_samples",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
        sa.Column("ts", sa.DateTime(timezone=True), index=True, nullable=False),
        sa.Column("level", sa.Integer),
        sa.Column("body_battery", sa.Integer),
    )
    op.execute("SELECT create_hypertable('stress_samples', 'ts', if_not_exists => TRUE)")

    op.create_table(
        "activities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
        sa.Column("provider_activity_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("start_ts", sa.DateTime(timezone=True), index=True, nullable=False),
        sa.Column("duration_s", sa.Integer, nullable=False),
        sa.Column("avg_hr", sa.Integer),
        sa.Column("max_hr", sa.Integer),
        sa.Column("calories", sa.Integer),
        sa.Column("raw", sa.JSON),
        sa.UniqueConstraint("user_id", "provider_activity_id", name="uq_user_activity"),
    )

    op.create_table(
        "lora_devices",
        sa.Column("dev_eui", sa.String(16), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("label", sa.String(255)),
    )

    op.create_table(
        "lora_uplinks",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("dev_eui", sa.String(16), sa.ForeignKey("lora_devices.dev_eui"), index=True),
        sa.Column("ts", sa.DateTime(timezone=True), index=True, nullable=False),
        sa.Column("rssi", sa.Integer),
        sa.Column("snr", sa.Float),
        sa.Column("payload", sa.JSON, nullable=False),
    )
    op.execute("SELECT create_hypertable('lora_uplinks', 'ts', if_not_exists => TRUE)")

    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("spec", sa.JSON, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "alert_events",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("rule_id", sa.Integer, sa.ForeignKey("alert_rules.id", ondelete="CASCADE"), index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("fired_at", sa.DateTime(timezone=True), index=True, nullable=False),
        sa.Column("context", sa.JSON, nullable=False),
    )


def downgrade() -> None:
    for t in (
        "alert_events",
        "alert_rules",
        "lora_uplinks",
        "lora_devices",
        "activities",
        "stress_samples",
        "sleep_sessions",
        "hr_samples",
        "daily_summaries",
        "wearable_accounts",
        "users",
    ):
        op.drop_table(t)
