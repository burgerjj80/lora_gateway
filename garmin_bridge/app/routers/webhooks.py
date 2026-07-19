import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import SessionLocal, get_session
from ..fetchers import run_fetch_and_store
from ..models import LoraDevice, LoraUplink, WearableAccount
from ..providers import Provider, get_provider
from ..providers.base import ConnectionTokens, FetchJob
from ..schemas import LoraUplinkIn

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
