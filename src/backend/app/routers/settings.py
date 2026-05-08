"""Settings endpoint — lets users view AI service configuration."""

import logging

from fastapi import APIRouter, Request

from app.config import get_settings
from app.models import AIServiceStatus

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=AIServiceStatus)
async def get_settings_endpoint(request: Request) -> AIServiceStatus:
    """Return current AI service config status."""
    settings = get_settings()
    return AIServiceStatus(
        configured=bool(settings.foundry_endpoint),
        foundryEndpoint=settings.foundry_endpoint,
        foundryModelDeployment=settings.foundry_model_deployment,
    )
