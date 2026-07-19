import logging

from fastapi import FastAPI

from .config import get_settings
from .routers import dashboard, health, oauth, webhooks

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="garmin_bridge",
    version="0.1.0",
    description="Wearable ingest + LoRa correlation for a2zwarehouse",
)

app.include_router(health.router)
app.include_router(oauth.router, prefix="/oauth", tags=["oauth"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
app.include_router(dashboard.router)
