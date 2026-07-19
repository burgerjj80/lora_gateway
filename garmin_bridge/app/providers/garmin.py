"""Direct Garmin Health API adapter (OAuth 1.0a).

Stubbed. Enable once developer.garmin.com approves the application and
GARMIN_CONSUMER_KEY / GARMIN_CONSUMER_SECRET are in .env.

Docs (behind login): https://developer.garmin.com/gc-developer-program/health-api/
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from requests_oauthlib import OAuth1

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

GARMIN_API = "https://apis.garmin.com"
GARMIN_CONNECT = "https://connectapi.garmin.com"

REQUEST_TOKEN_URL = f"{GARMIN_CONNECT}/oauth-service/oauth/request_token"
AUTHORIZE_URL = f"{GARMIN_CONNECT}/oauth-confirm/oauth/authorize"
ACCESS_TOKEN_URL = f"{GARMIN_CONNECT}/oauth-service/oauth/access_token"


class GarminProvider(Provider):
    name = "garmin"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # In-memory store of request tokens keyed by oauth_token so the
        # callback can look up the matching request_token_secret. In prod put
        # this in Redis or a short-TTL DB table.
        self._pending_request_secrets: dict[str, tuple[int, str]] = {}

    def _oauth1(self, token: str | None = None, secret: str | None = None) -> OAuth1:
        return OAuth1(
            self.settings.garmin_consumer_key,
            self.settings.garmin_consumer_secret,
            resource_owner_key=token,
            resource_owner_secret=secret,
        )

    async def authorize_url(self, user_id: int, return_url: str | None) -> str:
        callback = f"{self.settings.public_base_url}/oauth/garmin/callback"
        # requests_oauthlib is sync — fine, this happens once per connect.
        import requests

        resp = requests.post(
            REQUEST_TOKEN_URL,
            auth=self._oauth1(),
            params={"oauth_callback": callback},
            timeout=15,
        )
        resp.raise_for_status()
        parsed = dict(item.split("=", 1) for item in resp.text.split("&"))
        oauth_token = parsed["oauth_token"]
        oauth_token_secret = parsed["oauth_token_secret"]
        self._pending_request_secrets[oauth_token] = (user_id, oauth_token_secret)
        return f"{AUTHORIZE_URL}?oauth_token={oauth_token}"

    async def exchange_callback(self, query: dict[str, str]) -> ConnectionTokens:
        import requests

        oauth_token = query["oauth_token"]
        oauth_verifier = query["oauth_verifier"]
        _user_id, request_secret = self._pending_request_secrets.pop(oauth_token, (0, ""))
        resp = requests.post(
            ACCESS_TOKEN_URL,
            auth=self._oauth1(oauth_token, request_secret),
            params={"oauth_verifier": oauth_verifier},
            timeout=15,
        )
        resp.raise_for_status()
        parsed = dict(item.split("=", 1) for item in resp.text.split("&"))
        access_token = parsed["oauth_token"]
        access_secret = parsed["oauth_token_secret"]

        # Fetch garmin user_id
        r = httpx.get(
            f"{GARMIN_API}/wellness-api/rest/user/id",
            auth=self._oauth1(access_token, access_secret),
            timeout=15,
        )
        r.raise_for_status()
        garmin_user_id = r.json().get("userId", "")

        return ConnectionTokens(
            provider_user_id=garmin_user_id,
            access_token=access_token,
            access_token_secret=access_secret,
        )

    async def disconnect(self, tokens: ConnectionTokens) -> None:
        import requests

        requests.delete(
            f"{GARMIN_API}/wellness-api/rest/user/registration",
            auth=self._oauth1(tokens.access_token, tokens.access_token_secret),
            timeout=15,
        )

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        # Garmin doesn't sign PINGs; rely on network-level ACL (or a shared
        # secret in the callback path segment). Return True; add IP allow-list
        # at the reverse proxy in production.
        return True

    async def parse_and_fetch(
        self, headers: dict[str, str], body: dict[str, Any]
    ) -> list[FetchJob]:
        jobs: list[FetchJob] = []
        for kind_key, kind_name in (
            ("dailies", "dailies"),
            ("sleeps", "sleep"),
            ("stressDetails", "stress"),
            ("activities", "activity"),
            ("activityDetails", "activity_detail"),
        ):
            for ping in body.get(kind_key, []) or []:
                jobs.append(
                    FetchJob(
                        provider_user_id=ping["userId"],
                        kind=kind_name,
                        url=ping.get("callbackURL"),
                        start_ts=_epoch(ping.get("uploadStartTimeInSeconds")),
                        end_ts=_epoch(ping.get("uploadEndTimeInSeconds")),
                    )
                )
        return jobs

    async def run_job(self, job: FetchJob, tokens: ConnectionTokens) -> FetchResult:
        if not job.url:
            return _empty()
        auth = self._oauth1(tokens.access_token, tokens.access_token_secret)
        # httpx doesn't natively speak OAuth1; use requests here for signing.
        import requests

        r = requests.get(job.url, auth=auth, timeout=30)
        r.raise_for_status()
        payload = r.json()

        if job.kind == "dailies":
            return FetchResult(
                dailies=[_normalize_garmin_daily(d) for d in payload],
                hr_samples=[],
                sleep_sessions=[],
                activities=[],
                stress_samples=[],
            )
        if job.kind == "sleep":
            return FetchResult(
                dailies=[],
                hr_samples=[],
                sleep_sessions=[_normalize_garmin_sleep(s) for s in payload],
                activities=[],
                stress_samples=[],
            )
        # Extend for activity / activity_detail / stress / hrv / pulseox …
        return _empty()


def _empty() -> FetchResult:
    return FetchResult([], [], [], [], [])


def _epoch(v: int | None) -> datetime | None:
    return datetime.fromtimestamp(v, tz=timezone.utc) if v is not None else None


def _normalize_garmin_daily(d: dict) -> NormalizedDaily:
    return NormalizedDaily(
        day=datetime.fromtimestamp(d["startTimeInSeconds"], tz=timezone.utc).date(),
        steps=d.get("steps"),
        distance_m=d.get("distanceInMeters"),
        active_calories=d.get("activeKilocalories"),
        resting_hr=d.get("restingHeartRateInBeatsPerMinute"),
        avg_stress=d.get("averageStressLevel"),
        intensity_minutes=(d.get("moderateIntensityDurationInSeconds", 0) or 0)
        + (d.get("vigorousIntensityDurationInSeconds", 0) or 0),
        raw=d,
    )


def _normalize_garmin_sleep(s: dict) -> NormalizedSleep:
    start = datetime.fromtimestamp(s["startTimeInSeconds"], tz=timezone.utc)
    end = datetime.fromtimestamp(
        s["startTimeInSeconds"] + s.get("durationInSeconds", 0), tz=timezone.utc
    )
    return NormalizedSleep(
        start_ts=start,
        end_ts=end,
        deep_s=s.get("deepSleepDurationInSeconds"),
        light_s=s.get("lightSleepDurationInSeconds"),
        rem_s=s.get("remSleepInSeconds"),
        awake_s=s.get("awakeDurationInSeconds"),
        score=None,
        raw=s,
    )


# Deliberately unused imports to hint at the shape when this file gets
# extended: NormalizedHrSample, NormalizedActivity.
_ = (NormalizedHrSample, NormalizedActivity)
