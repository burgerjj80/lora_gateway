from datetime import datetime, date

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    wearable_accounts: Mapped[list["WearableAccount"]] = relationship(back_populates="user")


class WearableAccount(Base):
    """One row per (user, provider). Holds the credentials this service uses to
    fetch on the user's behalf."""

    __tablename__ = "wearable_accounts"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)  # "terra" | "garmin"
    provider_user_id: Mapped[str] = mapped_column(String(128), index=True)

    # Terra: single access token. Garmin OAuth1: token + secret. Both stored
    # encrypted at rest in production (KMS/age/pgcrypto — TODO).
    access_token: Mapped[str] = mapped_column(String(1024))
    access_token_secret: Mapped[str | None] = mapped_column(String(1024))

    scopes: Mapped[dict | None] = mapped_column(JSON)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="wearable_accounts")


# ---- Timeseries (hypertables in Timescale — see alembic migration) ---------


class DailySummary(Base):
    __tablename__ = "daily_summaries"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_user_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)

    steps: Mapped[int | None]
    distance_m: Mapped[float | None]
    active_calories: Mapped[int | None]
    resting_hr: Mapped[int | None]
    avg_stress: Mapped[int | None]
    intensity_minutes: Mapped[int | None]

    raw: Mapped[dict | None] = mapped_column(JSON)


class HrSample(Base):
    __tablename__ = "hr_samples"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    bpm: Mapped[int] = mapped_column(Integer)


class SleepSession(Base):
    __tablename__ = "sleep_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deep_s: Mapped[int | None]
    light_s: Mapped[int | None]
    rem_s: Mapped[int | None]
    awake_s: Mapped[int | None]
    score: Mapped[int | None]
    raw: Mapped[dict | None] = mapped_column(JSON)


class StressSample(Base):
    __tablename__ = "stress_samples"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    level: Mapped[int | None]
    body_battery: Mapped[int | None]


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint("user_id", "provider_activity_id", name="uq_user_activity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider_activity_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_s: Mapped[int]
    avg_hr: Mapped[int | None]
    max_hr: Mapped[int | None]
    calories: Mapped[int | None]
    raw: Mapped[dict | None] = mapped_column(JSON)


# ---- LoRa ingest (correlator writes/reads here) ----------------------------


class LoraDevice(Base):
    __tablename__ = "lora_devices"

    dev_eui: Mapped[str] = mapped_column(String(16), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(32))
    label: Mapped[str | None] = mapped_column(String(255))


class LoraUplink(Base):
    __tablename__ = "lora_uplinks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dev_eui: Mapped[str] = mapped_column(String(16), ForeignKey("lora_devices.dev_eui"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    rssi: Mapped[int | None]
    snr: Mapped[float | None]
    payload: Mapped[dict] = mapped_column(JSON)


# ---- Alerts ----------------------------------------------------------------


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    spec: Mapped[dict] = mapped_column(JSON)  # see alerts.RuleSpec
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    context: Mapped[dict] = mapped_column(JSON)
