import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import SessionLocal, get_session
from ..fetchers import run_fetch_and_store
from ..models import HrSample, LoraDevice, LoraUplink, WatchDevice, WearableAccount
from ..providers import Provider, get_provider
from ..providers.base import ConnectionTokens, FetchJob
from ..schemas import ConnectIqIn, LoraUplinkIn

log = logging.getLogger(__name__)
router = APIRouter()


def _provider() -> Provider:
    return get_provider()


@router.post("/wearable")
async def wearable_webhook(
    request: Request,
    bg: BackgroundTasks,
    provider: Provider = Depends(_provider),
):
    """Single endpoint for all provider PINGs.

    - Terra: one URL, all data types come in on it.
    - Garmin: register this URL for each data type in the developer portal.
    """
    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    if not provider.verify_webhook(headers, raw):
        raise HTTPException(401, "Bad signature")

    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON") from None

    jobs = await provider.parse_and_fetch(headers, body)
    log.info("webhook: provider=%s jobs=%d", provider.name, len(jobs))

    for job in jobs:
        # Background so we ACK the provider fast — provider will retry if the
        # response is slow.
        bg.add_task(_run_job_task, job.__dict__)

    return {"status": "accepted", "jobs": len(jobs)}


async def _run_job_task(job_dict: dict) -> None:
    provider = get_provider()
    job = FetchJob(**job_dict)
    async with SessionLocal() as session:
        account = await session.scalar(
            select(WearableAccount).where(
                WearableAccount.provider == provider.name,
                WearableAccount.provider_user_id == job.provider_user_id,
            )
        )
        if not account:
            log.warning("No account for provider_user_id=%s", job.provider_user_id)
            return
        tokens = ConnectionTokens(
            provider_user_id=account.provider_user_id,
            access_token=account.access_token,
            access_token_secret=account.access_token_secret,
        )
        result = await provider.run_job(job, tokens)
        await run_fetch_and_store(session, account.user_id, result)


@router.post("/lora/uplink")
async def lora_uplink(
    up: LoraUplinkIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Ingest from ChirpStack (or equivalent) app-server webhook.

    Configure ChirpStack → Integrations → HTTP with:
        URL: {PUBLIC_BASE_URL}/webhooks/lora/uplink
        Header: Authorization: Bearer {LORA_INGEST_TOKEN}
    """
    settings = get_settings()
    if settings.lora_ingest_token:
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {settings.lora_ingest_token}":
            raise HTTPException(401, "Bad token")

    # Ensure the device exists
    exists = await session.scalar(select(LoraDevice).where(LoraDevice.dev_eui == up.dev_eui))
    if not exists:
        session.add(LoraDevice(dev_eui=up.dev_eui, kind="unknown"))

    session.add(
        LoraUplink(
            dev_eui=up.dev_eui,
            ts=up.ts or datetime.now(timezone.utc),
            rssi=up.rssi,
            snr=up.snr,
            payload=up.payload,
        )
    )
    await session.commit()
    return {"status": "ok"}


@router.post("/connectiq")
async def connectiq_ingest(
    payload: ConnectIqIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Ingest from the a2zbridge Connect IQ widget running on a Fenix.

    Bearer-token authenticated with CONNECTIQ_INGEST_TOKEN; the same value
    goes into the widget's app settings.

    Device-to-user mapping is first-contact-wins: the first POST for a new
    device_id creates a WatchDevice with no user_id attached, which you then
    bind manually (admin UI or SQL) to the real user. All subsequent samples
    are stored against that user.
    """
    settings = get_settings()
    if not settings.connectiq_ingest_token:
        raise HTTPException(503, "CONNECTIQ_INGEST_TOKEN not configured")
    if request.headers.get("authorization", "") != f"Bearer {settings.connectiq_ingest_token}":
        raise HTTPException(401, "Bad token")

    now = datetime.now(timezone.utc)
    device = await session.get(WatchDevice, payload.device_id)
    if device is None:
        device = WatchDevice(
            device_id=payload.device_id,
            first_seen_at=now,
            last_seen_at=now,
            last_battery_pct=payload.watch.battery_pct if payload.watch else None,
        )
        session.add(device)
    else:
        device.last_seen_at = now
        if payload.watch and payload.watch.battery_pct is not None:
            device.last_battery_pct = payload.watch.battery_pct

    if device.user_id is None:
        # Unpaired watch — store the ping so first-contact is visible, but
        # don't drop HR into a user-scoped table yet.
        await session.commit()
        return {"status": "accepted", "paired": False}

    session.add_all(
        HrSample(user_id=device.user_id, ts=s.ts, bpm=s.bpm) for s in payload.samples.hr
    )
    await session.commit()
    log.info(
        "connectiq: device=%s user=%d hr=%d stress=%s bb=%s",
        payload.device_id,
        device.user_id,
        len(payload.samples.hr),
        payload.samples.stress,
        payload.samples.body_battery,
    )
    return {"status": "ok", "paired": True, "hr_samples": len(payload.samples.hr)}
