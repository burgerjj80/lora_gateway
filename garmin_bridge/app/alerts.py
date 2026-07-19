"""Rule engine + notifier stubs.

Two rule shapes:
- single-signal: e.g. "resting_hr > 100"
- cross-signal: e.g. "lora.temperature_c > 35 AND garmin.avg_hr > 150"

Rules are stored in the `alert_rules` table as a JSON `spec` (see RuleSpec
TypedDict below). Evaluation runs on ingest for the freshly written data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AlertEvent, AlertRule
from .providers.base import FetchResult

log = logging.getLogger(__name__)


class RuleSpec(TypedDict, total=False):
    kind: Literal["single", "cross"]
    metric: str  # "hr_bpm" | "resting_hr" | "body_battery" | "avg_stress"
    op: Literal[">", "<", ">=", "<=", "=="]
    threshold: float
    window_s: int
    channels: list[str]  # "email" | "slack" | "sms" | "push"
    # cross-signal fields:
    when: str  # e.g. "lora.temperature_c > 35 AND garmin.avg_hr > 150"


async def evaluate_for_user(
    session: AsyncSession, user_id: int, result: FetchResult
) -> None:
    rules = (
        await session.scalars(
            select(AlertRule).where(
                (AlertRule.user_id == user_id) | (AlertRule.user_id.is_(None)),
                AlertRule.enabled.is_(True),
            )
        )
    ).all()

    for rule in rules:
        spec: RuleSpec = rule.spec  # type: ignore[assignment]
        if spec.get("kind") == "single":
            hits = _evaluate_single(spec, result)
            for context in hits:
                await _fire(session, rule, user_id, context)
        # "cross" rules are evaluated by the scheduled cross-evaluator, not
        # here — cross-signal rules need a time-window DB join.
    await session.commit()


def _evaluate_single(spec: RuleSpec, result: FetchResult) -> list[dict[str, Any]]:
    metric = spec.get("metric")
    op = spec.get("op", ">")
    thr = spec.get("threshold")
    if metric is None or thr is None:
        return []

    hits: list[dict[str, Any]] = []
    if metric == "hr_bpm":
        for s in result.hr_samples:
            if _cmp(s.bpm, op, thr):
                hits.append({"ts": s.ts.isoformat(), "bpm": s.bpm})
    elif metric == "resting_hr":
        for d in result.dailies:
            if d.resting_hr is not None and _cmp(d.resting_hr, op, thr):
                hits.append({"day": d.day.isoformat(), "resting_hr": d.resting_hr})
    elif metric == "avg_stress":
        for d in result.dailies:
            if d.avg_stress is not None and _cmp(d.avg_stress, op, thr):
                hits.append({"day": d.day.isoformat(), "avg_stress": d.avg_stress})
    elif metric == "body_battery":
        for ts, _lvl, bb in result.stress_samples:
            if bb is not None and _cmp(bb, op, thr):
                hits.append({"ts": ts.isoformat(), "body_battery": bb})
    return hits


def _cmp(a: float, op: str, b: float) -> bool:
    return {
        ">": a > b,
        "<": a < b,
        ">=": a >= b,
        "<=": a <= b,
        "==": a == b,
    }.get(op, False)


async def _fire(
    session: AsyncSession, rule: AlertRule, user_id: int, context: dict[str, Any]
) -> None:
    event = AlertEvent(
        rule_id=rule.id,
        user_id=user_id,
        fired_at=datetime.now(timezone.utc),
        context=context,
    )
    session.add(event)
    for channel in (rule.spec or {}).get("channels", []):
        await _notify(channel, rule, user_id, context)


async def _notify(
    channel: str, rule: AlertRule, user_id: int, context: dict[str, Any]
) -> None:
    """Actual delivery. Stubbed — replace with your notifier of choice."""
    log.warning(
        "ALERT [%s] rule=%s user=%s context=%s", channel, rule.name, user_id, context
    )
    # TODO:
    #   - email: aiosmtplib to ALERT_SMTP_URL
    #   - slack: httpx.post(ALERT_SLACK_WEBHOOK, json=...)
    #   - sms: Twilio / MessageBird
    #   - push: FCM / APNs
