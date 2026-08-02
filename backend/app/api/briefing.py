"""
Morning Executive Briefing API Router (PRD V2.1 Feature 1).
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Query, Request, status

from app.config import Settings, get_settings
from app.middleware.auth import get_current_user
from app.models.contracts import ApiError, AuthClaims, ErrorCode, ExecutiveBriefingResponse
from app.services.briefing import generate_morning_briefing

router = APIRouter()
logger = logging.getLogger("voxquery.api.briefing")


def get_warehouse(request: Request):
    pipeline = getattr(request.app.state, "pipeline", None)
    return getattr(pipeline, "warehouse", None)


async def _enforce_rate_limit(request: Request, claims: AuthClaims) -> None:
    rate_limiter = request.app.state.rate_limiter
    rl_result = await rate_limiter.check_rate_limit(claims.user_id, claims.tenant_id)
    if not rl_result.available:
        raise ApiError(
            ErrorCode.service_unavailable,
            status_code=503,
            detail="Request protection is temporarily unavailable.",
        )
    if not rl_result.ok:
        raise ApiError(
            ErrorCode.rate_limit_exceeded,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Retry after {rl_result.retry_after_seconds}s",
        )


def _get_user_name(claims: AuthClaims) -> str:
    if claims.email and "@" in claims.email:
        name_part = claims.email.split("@")[0]
        if name_part and name_part != "user":
            return name_part.replace(".", " ").replace("_", " ").title()
    return "Executive"


@router.get("/api/briefing", response_model=ExecutiveBriefingResponse)
async def get_briefing(
    request: Request,
    claims: AuthClaims = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    warehouse = Depends(get_warehouse),
) -> ExecutiveBriefingResponse:
    """
    Fetch the morning executive briefing for the authenticated tenant.
    """
    await _enforce_rate_limit(request, claims)
    logger.info("Generating morning briefing for tenant_id=%s user_id=%s", claims.tenant_id, claims.user_id)
    user_name = _get_user_name(claims)
    return await generate_morning_briefing(
        claims.tenant_id,
        settings,
        user_name=user_name,
        warehouse=warehouse,
        snowflake_role=claims.snowflake_role,
        redis_client=getattr(getattr(request.app.state, "sessions", None), "client", None),
    )


@router.get("/api/briefing/pdf")
async def get_briefing_pdf(
    request: Request,
    claims: AuthClaims = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    warehouse = Depends(get_warehouse),
):
    from fastapi.responses import Response
    from app.services.pdf_exporter import generate_briefing_pdf
    await _enforce_rate_limit(request, claims)
    user_name = _get_user_name(claims)
    briefing = await generate_morning_briefing(
        claims.tenant_id,
        settings,
        user_name=user_name,
        warehouse=warehouse,
        snowflake_role=claims.snowflake_role,
        redis_client=getattr(getattr(request.app.state, "sessions", None), "client", None),
    )
    
    tenant_name = claims.tenant_name
    db_pool = getattr(request.app.state, "db_pool", None)
    if not tenant_name and db_pool:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow("SELECT name FROM tenants WHERE id = $1", claims.tenant_id)
                if row and row["name"]:
                    tenant_name = row["name"]
        except Exception:
            pass

    pdf_bytes = await generate_briefing_pdf(briefing, tenant_name=tenant_name or claims.tenant_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=briefing.pdf"},
    )


@router.get("/api/briefing/audio")
async def get_briefing_audio(
    request: Request,
    voice: str = Query(default="aura-asteria-en", description="TTS voice narrator model"),
    claims: AuthClaims = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    warehouse = Depends(get_warehouse),
):
    from fastapi.responses import Response
    from app.services.briefing_audio import get_or_generate_briefing_audio_bytes
    await _enforce_rate_limit(request, claims)
    audio_bytes, provider = await get_or_generate_briefing_audio_bytes(
        claims,
        settings,
        redis_client=getattr(getattr(request.app.state, "sessions", None), "client", None),
        voice=voice,
        warehouse=warehouse,
    )
    return Response(content=audio_bytes, media_type="audio/mpeg")

