from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import DailySummary, HrSample, WearableAccount

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return HTMLResponse('<a href="/dashboard">dashboard</a>')


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)):
    since = datetime.now(timezone.utc) - timedelta(days=14)
    accounts = (await session.scalars(select(WearableAccount))).all()
    dailies = (
        await session.scalars(
            select(DailySummary).where(DailySummary.day >= since.date()).order_by(DailySummary.day)
        )
    ).all()
    hr = (
        await session.scalars(
            select(HrSample).where(HrSample.ts >= since).order_by(HrSample.ts).limit(500)
        )
    ).all()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"accounts": accounts, "dailies": dailies, "hr": hr},
    )
