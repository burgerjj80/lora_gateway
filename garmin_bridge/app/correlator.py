"""Time-window joins between Garmin/wearable data and LoRa uplinks.

Kept as pure SQL helpers so they compose with either background jobs (via
apscheduler) or on-demand queries from the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class HrEnvCorrelation:
    ts: datetime
    bpm: int
    dev_eui: str
    temp_c: float | None
    humidity: float | None


async def hr_vs_environment(
    session: AsyncSession,
    user_id: int,
    window_start: datetime,
    window_end: datetime,
    dev_euis: list[str] | None = None,
    match_tolerance: timedelta = timedelta(minutes=1),
) -> list[HrEnvCorrelation]:
    """For each HR sample in the window, find the nearest LoRa environmental
    uplink within tolerance and return the joined pair.

    Assumes LoRa payloads carry `temperature_c` and `humidity` keys — swap the
    JSON path lookups if your devices use different keys.
    """
    dev_clause = "AND l.dev_eui = ANY(:devs)" if dev_euis else ""
    q = text(
        f"""
        SELECT h.ts, h.bpm, l.dev_eui,
               (l.payload->>'temperature_c')::float AS temp_c,
               (l.payload->>'humidity')::float AS humidity
        FROM hr_samples h
        JOIN LATERAL (
            SELECT lu.dev_eui, lu.payload
            FROM lora_uplinks lu
            WHERE lu.ts BETWEEN h.ts - :tol AND h.ts + :tol
              {dev_clause}
            ORDER BY ABS(EXTRACT(EPOCH FROM (lu.ts - h.ts)))
            LIMIT 1
        ) l ON TRUE
        WHERE h.user_id = :uid AND h.ts BETWEEN :start AND :end
        ORDER BY h.ts
        """
    )
    params = {
        "uid": user_id,
        "start": window_start,
        "end": window_end,
        "tol": match_tolerance,
    }
    if dev_euis:
        params["devs"] = dev_euis
    rows = (await session.execute(q, params)).all()
    return [HrEnvCorrelation(*row) for row in rows]


async def activity_zone_overlap(
    session: AsyncSession,
    user_id: int,
    dev_eui: str,
) -> list[dict]:
    """Activities whose start/end overlap with any LoRa uplink from `dev_eui`
    (e.g. a location beacon at a specific work zone)."""
    q = text(
        """
        SELECT a.id, a.kind, a.start_ts, a.duration_s,
               COUNT(l.id) AS beacon_hits
        FROM activities a
        JOIN lora_uplinks l
          ON l.dev_eui = :dev
         AND l.ts BETWEEN a.start_ts AND a.start_ts + (a.duration_s || ' seconds')::interval
        WHERE a.user_id = :uid
        GROUP BY a.id
        ORDER BY a.start_ts DESC
        """
    )
    rows = (await session.execute(q, {"uid": user_id, "dev": dev_eui})).mappings().all()
    return [dict(r) for r in rows]
