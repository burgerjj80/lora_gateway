from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import WearableAccount
from ..providers import Provider, get_provider
from ..schemas import ConnectRequest, ConnectResponse

router = APIRouter()


def _provider() -> Provider:
    return get_provider()


@router.post("/connect", response_model=ConnectResponse)
async def connect(req: ConnectRequest, provider: Provider = Depends(_provider)):
    url = await provider.authorize_url(req.user_id, req.return_url)
    return ConnectResponse(authorize_url=url)


@router.get("/{provider_name}/callback")
async def callback(
    provider_name: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    provider: Provider = Depends(_provider),
):
    if provider_name != provider.name:
        raise HTTPException(400, f"Provider mismatch: expected {provider.name}")

    tokens = await provider.exchange_callback(dict(request.query_params))

    # TODO: correlate to real user (session cookie, signed state, etc).
    # For scaffolding we associate to user_id=1 if it exists.
    user_id = int(request.query_params.get("user_id", "1"))

    existing = await session.scalar(
        select(WearableAccount).where(
            WearableAccount.user_id == user_id,
            WearableAccount.provider == provider.name,
        )
    )
    if existing:
        existing.access_token = tokens.access_token
        existing.access_token_secret = tokens.access_token_secret
        existing.provider_user_id = tokens.provider_user_id
        existing.disconnected_at = None
    else:
        session.add(
            WearableAccount(
                user_id=user_id,
                provider=provider.name,
                provider_user_id=tokens.provider_user_id,
                access_token=tokens.access_token,
                access_token_secret=tokens.access_token_secret,
                connected_at=datetime.now(timezone.utc),
            )
        )
    await session.commit()
    return RedirectResponse("/dashboard")


@router.post("/{provider_name}/disconnect")
async def disconnect(
    provider_name: str,
    user_id: int,
    session: AsyncSession = Depends(get_session),
    provider: Provider = Depends(_provider),
):
    account = await session.scalar(
        select(WearableAccount).where(
            WearableAccount.user_id == user_id,
            WearableAccount.provider == provider_name,
        )
    )
    if not account:
        raise HTTPException(404, "Not connected")
    from ..providers.base import ConnectionTokens

    await provider.disconnect(
        ConnectionTokens(
            provider_user_id=account.provider_user_id,
            access_token=account.access_token,
            access_token_secret=account.access_token_secret,
        )
    )
    account.disconnected_at = datetime.now(timezone.utc)
    await session.commit()
    return {"status": "disconnected"}
