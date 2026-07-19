from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass
class ConnectionTokens:
    provider_user_id: str
    access_token: str
    access_token_secret: str | None = None
    scopes: dict | None = None


@dataclass
class NormalizedDaily:
    day: date
    steps: int | None
    distance_m: float | None
    active_calories: int | None
    resting_hr: int | None
    avg_stress: int | None
    intensity_minutes: int | None
    raw: dict


@dataclass
class NormalizedHrSample:
    ts: datetime
    bpm: int


@dataclass
class NormalizedSleep:
    start_ts: datetime
    end_ts: datetime
    deep_s: int | None
    light_s: int | None
    rem_s: int | None
    awake_s: int | None
    score: int | None
    raw: dict


@dataclass
class NormalizedActivity:
    provider_activity_id: str
    kind: str
    start_ts: datetime
    duration_s: int
    avg_hr: int | None
    max_hr: int | None
    calories: int | None
    raw: dict


class Provider(ABC):
    """Interface every wearable provider adapter implements.

    Terra and direct-Garmin both return the normalized dataclasses above so the
    rest of the app (fetchers, correlator, alerts) is provider-agnostic.
    """

    name: str

    @abstractmethod
    async def authorize_url(self, user_id: int, return_url: str | None) -> str:
        """Return the URL to send the user to for provider-hosted auth."""

    @abstractmethod
    async def exchange_callback(self, query: dict[str, str]) -> ConnectionTokens:
        """Complete the auth handshake using the querystring from our callback."""

    @abstractmethod
    async def disconnect(self, tokens: ConnectionTokens) -> None:
        """Revoke/deregister the user's connection at the provider."""

    @abstractmethod
    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """Verify webhook signature. Return False → 401 the request."""

    @abstractmethod
    async def parse_and_fetch(
        self, headers: dict[str, str], body: dict[str, Any]
    ) -> "list[FetchJob]":
        """Turn a webhook body into a list of concrete fetch jobs to run in the
        background. The webhook handler ACKs 200 immediately; jobs run after."""

    @abstractmethod
    async def run_job(self, job: "FetchJob", tokens: ConnectionTokens) -> "FetchResult":
        """Execute one fetch job and return normalized data."""


@dataclass
class FetchJob:
    provider_user_id: str
    kind: str  # "dailies" | "hr" | "sleep" | "stress" | "activity" | ...
    url: str | None = None
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    extra: dict | None = None


@dataclass
class FetchResult:
    dailies: list[NormalizedDaily]
    hr_samples: list[NormalizedHrSample]
    sleep_sessions: list[NormalizedSleep]
    activities: list[NormalizedActivity]
    stress_samples: list[tuple[datetime, int | None, int | None]]  # (ts, level, body_battery)
