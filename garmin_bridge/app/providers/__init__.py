from ..config import get_settings
from .base import Provider
from .garmin import GarminProvider
from .terra import TerraProvider


def get_provider() -> Provider:
    settings = get_settings()
    if settings.wearable_provider == "terra":
        return TerraProvider(settings)
    if settings.wearable_provider == "garmin":
        return GarminProvider(settings)
    raise ValueError(f"Unknown provider: {settings.wearable_provider}")


__all__ = ["Provider", "TerraProvider", "GarminProvider", "get_provider"]
