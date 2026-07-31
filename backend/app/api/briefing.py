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


@router.get("/api/briefing/pdf")
async def get_briefing_pdf(
    claims: AuthClaims = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    from fastapi.responses import Response
    from app.services.pdf_exporter import generate_briefing_pdf
    briefing = await generate_morning_briefing(claims.tenant_id, settings, user_name="Executive")
    pdf_bytes = await generate_briefing_pdf(briefing, tenant_name=claims.tenant_id)
    return Response(content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=briefing.pdf"})


@router.get("/api/briefing/audio")
async def get_briefing_audio(
    claims: AuthClaims = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    from fastapi.responses import Response
    from app.services.briefing_audio import get_or_generate_briefing_audio_bytes
    audio_bytes, provider = await get_or_generate_briefing_audio_bytes(
        claims, settings, redis_client=None
    )
    return Response(content=audio_bytes, media_type="audio/mpeg")

