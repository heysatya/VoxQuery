"""
Morning Executive Briefing API Router (PRD V2.1 Feature 1).
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.middleware.auth import get_current_user
from app.models.contracts import AuthClaims, ExecutiveBriefingResponse
from app.services.briefing import generate_morning_briefing

router = APIRouter()
logger = logging.getLogger("voxquery.api.briefing")


@router.get("/api/briefing", response_model=ExecutiveBriefingResponse)
async def get_briefing(
    claims: AuthClaims = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> ExecutiveBriefingResponse:
    """
    Fetch the morning executive briefing for the authenticated tenant.
    """
    logger.info("Generating morning briefing for tenant_id=%s user_id=%s", claims.tenant_id, claims.user_id)
    return await generate_morning_briefing(claims.tenant_id, settings, user_name="Executive")
