from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    public_base_url: str = Field(..., description="Publicly reachable HTTPS URL of this service")
    secret_key: str = Field(..., min_length=16)
    log_level: str = "INFO"

    database_url: str

    wearable_provider: Literal["terra", "garmin"] = "terra"

    terra_dev_id: str = ""
    terra_api_key: str = ""
    terra_signing_secret: str = ""

    garmin_consumer_key: str = ""
    garmin_consumer_secret: str = ""

    alert_email_from: str = ""
    alert_smtp_url: str = ""
    alert_slack_webhook: str = ""

    lora_ingest_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
