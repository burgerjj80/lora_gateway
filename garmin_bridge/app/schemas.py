from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class ConnectRequest(BaseModel):
    user_id: int
    return_url: str | None = None


class ConnectResponse(BaseModel):
    authorize_url: str


class TerraWebhook(BaseModel):
    """Terra's canonical webhook envelope. See tryterra.co/docs."""

    type: str
    user: dict[str, Any]
    data: list[dict[str, Any]] | None = None


class GarminPing(BaseModel):
    """Single PING entry inside a Garmin webhook body."""

    userId: str
    userAccessToken: str | None = None
    summaryId: str | None = None
    callbackURL: str | None = None
    uploadStartTimeInSeconds: int | None = None
    uploadEndTimeInSeconds: int | None = None


class GarminWebhook(BaseModel):
    """Garmin webhook bodies are keyed by data type — e.g. {"dailies": [...]}"""

    dailies: list[GarminPing] | None = None
    sleeps: list[GarminPing] | None = None
    stressDetails: list[GarminPing] | None = None
    hrv: list[GarminPing] | None = None
    pulseox: list[GarminPing] | None = None
    respiration: list[GarminPing] | None = None
    bodyComps: list[GarminPing] | None = None
    activities: list[GarminPing] | None = None
    activityDetails: list[GarminPing] | None = None
    deregistrations: list[GarminPing] | None = None


class LoraUplinkIn(BaseModel):
    dev_eui: str
    ts: datetime
    rssi: int | None = None
    snr: float | None = None
    payload: dict[str, Any]


class ConnectIqHrSample(BaseModel):
    ts: datetime
    bpm: int


class ConnectIqSamples(BaseModel):
    hr: list[ConnectIqHrSample] = []
    stress: int | None = None
    body_battery: int | None = None
    steps_today: int | None = None
    calories_today: int | None = None


class ConnectIqWatch(BaseModel):
    battery_pct: float | None = None


class ConnectIqIn(BaseModel):
    """Payload posted by the a2zbridge Connect IQ widget on each background wake."""

    device_id: str
    ts: datetime
    watch: ConnectIqWatch | None = None
    samples: ConnectIqSamples


class DailyOut(BaseModel):
    day: date
    steps: int | None
    resting_hr: int | None
    avg_stress: int | None


class HrWindowOut(BaseModel):
    ts: datetime
    bpm: int
