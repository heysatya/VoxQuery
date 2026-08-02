"""
Secure Share Links API Router.

Implements create, retrieve, revoke, and list endpoints for share links.
Tokens are never stored in plaintext; only SHA-256 hashes persist.
Cross-tenant access is blocked at the repository level.
Default: only authenticated users within the same tenant may view shared results.
Unauthenticated public sharing is not enabled.
"""
from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.middleware.auth import get_current_user
from app.models.contracts import (
    ApiError,
    AuthClaims,
    ErrorCode,
    ShareLinkCreateRequest,
    ShareLinkCreateResponse,
    ShareLinkListResponse,
    ShareLinkItem,
    SharedResultResponse,
    StatusResponse,
)

router = APIRouter()
logger = logging.getLogger("voxquery.api.share")


def _get_db_pool(request: Request):
    return getattr(request.app.state, "db_pool", None)


@router.post("/api/share", response_model=ShareLinkCreateResponse, status_code=201)
async def create_share_link(
    body: ShareLinkCreateRequest,
    request: Request,
    claims: AuthClaims = Depends(get_current_user),
) -> ShareLinkCreateResponse:
    """
    Create a secure, expiring share link for a completed query result.
    The raw token is returned once and never stored.
    """
    db_pool = _get_db_pool(request)
    if db_pool is None:
        raise ApiError(ErrorCode.service_unavailable, status_code=503, detail="Share link storage unavailable.")

    from app.repositories.share_repository import ShareRepository, DEFAULT_TTL_HOURS, MAX_TTL_HOURS, MIN_TTL_HOURS
    ttl = body.ttl_hours if body.ttl_hours is not None else DEFAULT_TTL_HOURS
    if not (MIN_TTL_HOURS <= ttl <= MAX_TTL_HOURS):
        raise ApiError(
            ErrorCode.internal_error, status_code=400,
            detail=f"ttl_hours must be between {MIN_TTL_HOURS} and {MAX_TTL_HOURS}.",
        )

    repo = ShareRepository(db_pool)
    result = await repo.create_share_link(
        claims,
        body.turn_id,
        label=body.label,
        ttl_hours=ttl,
    )
    if result is None:
        raise ApiError(
            ErrorCode.turn_not_found, status_code=404,
            detail="Turn not found, not completed, or not in your tenant.",
        )

    # Build the shareable URL using the request's base URL
    base_url = str(request.base_url).rstrip("/")
    share_url = f"{base_url}/share/{result['token']}"

    return ShareLinkCreateResponse(
        link_id=result["link_id"],
        url=share_url,
        token=result["token"],
        expires_at=result["expires_at"],
    )


@router.get("/api/share/{token}", response_model=SharedResultResponse)
async def get_shared_result(
    token: str,
    request: Request,
    claims: AuthClaims = Depends(get_current_user),
) -> SharedResultResponse:
    """
    Retrieve the shared result snapshot by its opaque token.
    Requires authentication within the same tenant as the link creator.
    Never issues a new warehouse query; returns the stored snapshot.
    """
    db_pool = _get_db_pool(request)
    if db_pool is None:
        raise ApiError(ErrorCode.service_unavailable, status_code=503, detail="Share link storage unavailable.")

    from app.repositories.share_repository import ShareRepository
    repo = ShareRepository(db_pool)
    result = await repo.get_share_by_token(token, claims.tenant_id)

    if result is None:
        raise ApiError(ErrorCode.turn_not_found, status_code=404, detail="Share link not found.")

    error_state = result.get("_error")
    if error_state == "expired":
        raise ApiError(ErrorCode.session_expired, status_code=410, detail="This share link has expired.")
    if error_state == "revoked":
        raise ApiError(ErrorCode.turn_forbidden, status_code=403, detail="This share link has been revoked.")
    if error_state == "not_found":
        raise ApiError(ErrorCode.turn_not_found, status_code=404, detail="The shared result is no longer available.")

    return SharedResultResponse(
        link_id=result["link_id"],
        turn_id=result["turn_id"],
        label=result.get("label"),
        user_input=result.get("user_input", ""),
        chart_type=result.get("chart_type"),
        confidence_tier=result.get("confidence_tier"),
        full_result=result.get("full_result"),
        created_at=result["created_at"],
        expires_at=result["expires_at"],
        is_snapshot=True,
    )


@router.delete("/api/share/{link_id}", response_model=StatusResponse)
async def revoke_share_link(
    link_id: str,
    request: Request,
    claims: AuthClaims = Depends(get_current_user),
) -> StatusResponse:
    """Revoke a share link. Only the creator can revoke their own links."""
    db_pool = _get_db_pool(request)
    if db_pool is None:
        raise ApiError(ErrorCode.service_unavailable, status_code=503, detail="Share link storage unavailable.")

    from app.repositories.share_repository import ShareRepository
    repo = ShareRepository(db_pool)
    revoked = await repo.revoke_share_link(claims, link_id)
    if not revoked:
        raise ApiError(ErrorCode.turn_not_found, status_code=404, detail="Share link not found or already revoked.")
    return StatusResponse(status="revoked")


@router.get("/api/share", response_model=ShareLinkListResponse)
async def list_share_links(
    request: Request,
    claims: AuthClaims = Depends(get_current_user),
) -> ShareLinkListResponse:
    """List the authenticated user's active (non-expired, non-revoked) share links."""
    db_pool = _get_db_pool(request)
    if db_pool is None:
        return ShareLinkListResponse(items=[])

    from app.repositories.share_repository import ShareRepository
    repo = ShareRepository(db_pool)
    links = await repo.list_active_share_links(claims)

    base_url = str(request.base_url).rstrip("/")
    items = [
        ShareLinkItem(
            link_id=lnk["link_id"],
            turn_id=lnk["turn_id"],
            label=lnk.get("label"),
            user_input=lnk.get("user_input", ""),
            created_at=lnk["created_at"],
            expires_at=lnk["expires_at"],
            access_count=lnk["access_count"],
            url=f"{base_url}/share/[token]",  # URL pattern; actual token not re-exposed after creation
        )
        for lnk in links
    ]
    return ShareLinkListResponse(items=items)
