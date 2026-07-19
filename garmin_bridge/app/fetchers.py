"""Persist normalized provider results into the DB.

Runs from BackgroundTasks or an APScheduler worker. All upserts are
idempotent — replaying the same webhook is safe.
"""

from __future__ import annotations

import logging

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from . import alerts
from .models import Activity, DailySummary, HrSample, SleepSession, StressSample
from .providers.base import FetchResult

log = logging.getLogger(__name__)


async def run_fetch_and_store(session: AsyncSession, user_id: int, result: FetchResult) -> None:
    if result.dailies:
        await _upsert_dailies(session, user_id, result)
    if result.hr_samples:
        await _insert_hr_samples(session, user_id, result)
    if result.sleep_sessions:
        await _insert_sleep(session, user_id, result)
    if result.activities:
        await _upsert_activities(session, user_id, result)
    if result.stress_samples:
        await _insert_stress(session, user_id, result)
    await session.commit()

    # Fire the rule engine over the freshly written data.
    await alerts.evaluate_for_user(session, user_id, result)


async def _upsert_dailies(session: AsyncSession, user_id: int, r: FetchResult) -> None:
    for d in r.dailies:
        stmt = insert(DailySummary).values(
            user_id=user_id,
            day=d.day,
            steps=d.steps,
            distance_m=d.distance_m,
            active_calories=d.active_calories,
            resting_hr=d.resting_hr,
            avg_stress=d.avg_stress,
            intensity_minutes=d.intensity_minutes,
            raw=d.raw,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "day"],
            set_={
                "steps": stmt.excluded.steps,
                "distance_m": stmt.excluded.distance_m,
                "active_calories": stmt.excluded.active_calories,
                "resting_hr": stmt.excluded.resting_hr,
                "avg_stress": stmt.excluded.avg_stress,
                "intensity_minutes": stmt.excluded.intensity_minutes,
                "raw": stmt.excluded.raw,
            },
        )
        await session.execute(stmt)


async def _insert_hr_samples(session: AsyncSession, user_id: int, r: FetchResult) -> None:
    session.add_all(HrSample(user_id=user_id, ts=s.ts, bpm=s.bpm) for s in r.hr_samples)


async def _insert_sleep(session: AsyncSession, user_id: int, r: FetchResult) -> None:
    session.add_all(
        SleepSession(
            user_id=user_id,
            start_ts=s.start_ts,
            end_ts=s.end_ts,
            deep_s=s.deep_s,
            light_s=s.light_s,
            rem_s=s.rem_s,
            awake_s=s.awake_s,
            score=s.score,
            raw=s.raw,
        )
        for s in r.sleep_sessions
    )


async def _upsert_activities(session: AsyncSession, user_id: int, r: FetchResult) -> None:
    for a in r.activities:
        stmt = insert(Activity).values(
            user_id=user_id,
            provider_activity_id=a.provider_activity_id,
            kind=a.kind,
            start_ts=a.start_ts,
            duration_s=a.duration_s,
            avg_hr=a.avg_hr,
            max_hr=a.max_hr,
            calories=a.calories,
            raw=a.raw,
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["user_id", "provider_activity_id"])
        await session.execute(stmt)


async def _insert_stress(session: AsyncSession, user_id: int, r: FetchResult) -> None:
    session.add_all(
        StressSample(user_id=user_id, ts=ts, level=level, body_battery=bb)
        for (ts, level, bb) in r.stress_samples
    )
