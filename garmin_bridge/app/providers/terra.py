"""Terra API adapter — self-serve, works today.

Docs: https://docs.tryterra.co/reference
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from typing import Any

import httpx

from ..config import Settings
from .base import (
    ConnectionTokens,
    FetchJob,
    FetchResult,
    NormalizedActivity,
    NormalizedDaily,
    NormalizedHrSample,
    NormalizedSleep,
    Provider,
)

TERRA_API = "https://api.tryterra.co/v2"


class TerraProvider(Provider):
    name = "terra"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._headers = {
            "dev-id": settings.terra_dev_id,
            "x-api-key": settings.terra_api_key,
        }

    async def authorize_url(self, user_id: int, return_url: str | None) -> str:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.post(
                f"{TERRA_API}/auth/generateWidgetSession",
                headers=self._headers,
                json={
                    "reference_id": str(user_id),
                    "providers": "GARMIN,FITBIT,OURA,POLAR,WITHINGS,SUUNTO",
                    "auth_success_redirect_url": return_url or self.settings.public_base_url,
                    "auth_failure_redirect_url": return_url or self.settings.public_base_url,
                    "language": "en",
                },
            )
            r.raise_for_status()
            return r.json()["url"]

    async def exchange_callback(self, query: dict[str, str]) -> ConnectionTokens:
        # Terra pushes the connection via webhook (`type: "auth"`), not a
        # redirect callback with tokens. This method is present for interface
        # symmetry; the real token capture happens in parse_and_fetch when we
        # see an auth event.
        return ConnectionTokens(
            provider_user_id=query["user_id"],
            access_token=query.get("user_id", ""),
        )

    async def disconnect(self, tokens: ConnectionTokens) -> None:
        async with httpx.AsyncClient(timeout=15) as http:
            await http.delete(
                f"{TERRA_API}/auth/deauthenticateUser",
                headers=self._headers,
                params={"user_id": tokens.provider_user_id},
            )

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        secret = self.settings.terra_signing_secret
        if not secret:
            return True  # dev mode
        sig = headers.get("terra-signature", "")
        # terra-signature: t=<ts>,v1=<hex-hmac>
        parts = dict(item.split("=", 1) for item in sig.split(",") if "=" in item)
        ts, v1 = parts.get("t", ""), parts.get("v1", "")
        mac = hmac.new(secret.encode(), f"{ts}.{body.decode()}".encode(), hashlib.sha256)
        return hmac.compare_digest(mac.hexdigest(), v1)

    async def parse_and_fetch(
        self, headers: dict[str, str], body: dict[str, Any]
    ) -> list[FetchJob]:
        # Terra pushes normalized data inline in the webhook — no follow-up
        # fetch needed. We stash the whole payload in the job so run_job can
        # normalize it.
        return [
            FetchJob(
                provider_user_id=body.get("user", {}).get("user_id", ""),
                kind=body.get("type", "unknown"),
                extra={"body": body},
            )
        ]

    async def run_job(self, job: FetchJob, tokens: ConnectionTokens) -> FetchResult:
        body = (job.extra or {}).get("body", {})
        data = body.get("data", []) or []

        dailies: list[NormalizedDaily] = []
        hr_samples: list[NormalizedHrSample] = []
        sleep_sessions: list[NormalizedSleep] = []
        activities: list[NormalizedActivity] = []
        stress_samples: list[tuple[datetime, int | None, int | None]] = []

        if job.kind == "daily":
            for d in data:
                dailies.append(_normalize_terra_daily(d))
        elif job.kind == "sleep":
            for s in data:
                sleep_sessions.append(_normalize_terra_sleep(s))
        elif job.kind == "activity":
            for a in data:
                activities.append(_normalize_terra_activity(a))
                hr_samples.extend(_extract_hr_samples(a))

        return FetchResult(
            dailies=dailies,
            hr_samples=hr_samples,
            sleep_sessions=sleep_sessions,
            activities=activities,
            stress_samples=stress_samples,
        )


def _normalize_terra_daily(d: dict) -> NormalizedDaily:
    md = d.get("metadata", {})
    hr = d.get("heart_rate_data", {}).get("summary", {})
    return NormalizedDaily(
        day=datetime.fromisoformat(md["start_time"].replace("Z", "+00:00")).date(),
        steps=d.get("distance_data", {}).get("steps"),
        distance_m=d.get("distance_data", {}).get("distance_meters"),
        active_calories=d.get("calories_data", {}).get("net_activity_calories"),
        resting_hr=hr.get("resting_hr_bpm"),
        avg_stress=d.get("stress_data", {}).get("avg_stress_level"),
        intensity_minutes=d.get("active_durations_data", {}).get("activity_seconds"),
        raw=d,
    )


def _normalize_terra_sleep(s: dict) -> NormalizedSleep:
    md = s.get("metadata", {})
    dur = s.get("sleep_durations_data", {}).get("asleep", {})
    return NormalizedSleep(
        start_ts=datetime.fromisoformat(md["start_time"].replace("Z", "+00:00")),
        end_ts=datetime.fromisoformat(md["end_time"].replace("Z", "+00:00")),
        deep_s=dur.get("duration_deep_sleep_state_seconds"),
        light_s=dur.get("duration_light_sleep_state_seconds"),
        rem_s=dur.get("duration_REM_sleep_state_seconds"),
        awake_s=s.get("sleep_durations_data", {})
        .get("awake", {})
        .get("duration_awake_state_seconds"),
        score=s.get("scores", {}).get("sleep_score"),
        raw=s,
    )


def _normalize_terra_activity(a: dict) -> NormalizedActivity:
    md = a.get("metadata", {})
    hr = a.get("heart_rate_data", {}).get("summary", {})
    return NormalizedActivity(
        provider_activity_id=str(md.get("upload_id", md.get("summary_id", ""))),
        kind=md.get("name", "unknown"),
        start_ts=datetime.fromisoformat(md["start_time"].replace("Z", "+00:00")),
        duration_s=int(a.get("active_durations_data", {}).get("activity_seconds", 0)),
        avg_hr=hr.get("avg_hr_bpm"),
        max_hr=hr.get("max_hr_bpm"),
        calories=a.get("calories_data", {}).get("total_burned_calories"),
        raw=a,
    )


def _extract_hr_samples(a: dict) -> list[NormalizedHrSample]:
    samples = a.get("heart_rate_data", {}).get("detailed", {}).get("hr_samples", [])
    out: list[NormalizedHrSample] = []
    for s in samples:
        ts = s.get("timestamp")
        bpm = s.get("bpm")
        if ts and bpm:
            out.append(
                NormalizedHrSample(
                    ts=datetime.fromisoformat(ts.replace("Z", "+00:00")),
                    bpm=int(bpm),
                )
            )
    return out
