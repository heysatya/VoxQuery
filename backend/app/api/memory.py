"""
Executive Memory API Router.

Exposes durable, tenant-scoped, user-scoped memory via typed endpoints.
No internal IDs, raw SQL, or unexplained "entity" terminology is exposed.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Request

from app.middleware.auth import get_current_user
from app.models.contracts import (
    ApiError,
    AuthClaims,
    ErrorCode,
    MemorySummaryResponse,
    StatusResponse,
)

router = APIRouter()
logger = logging.getLogger("voxquery.api.memory")


def _get_db_pool(request: Request):
    return getattr(request.app.state, "db_pool", None)


@router.get("/api/memory", response_model=MemorySummaryResponse)
async def get_memory_summary(
    request: Request,
    claims: AuthClaims = Depends(get_current_user),
) -> MemorySummaryResponse:
    """
    Return the authenticated user's durable remembered preferences and interests
    within the active tenant.
    """
    db_pool = _get_db_pool(request)
    if db_pool is None:
        return MemorySummaryResponse(
            available=False,
            unavailable_reason="Memory storage is not configured.",
            items=[],
        )

    from app.repositories.memory_repository import MemoryRepository
    repo = MemoryRepository(db_pool)
    rows = await repo.get_active_memories(claims, limit=50)

    items = []
    for row in rows:
        items.append({
            "id": str(row["id"]),
            "memory_type": row["memory_type"],
            "label": row["label"],
            "confidence": float(row["confidence"]),
            "last_observed_at": row["last_observed_at"].isoformat() if row.get("last_observed_at") else None,
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "source_turn_id": str(row["source_turn_id"]) if row.get("source_turn_id") else None,
        })

    return MemorySummaryResponse(
        available=True,
        items=items,
    )


@router.delete("/api/memory/{memory_id}", response_model=StatusResponse)
async def delete_memory_item(
    memory_id: str,
    request: Request,
    claims: AuthClaims = Depends(get_current_user),
) -> StatusResponse:
    """Archive (soft-delete) a single remembered item."""
    db_pool = _get_db_pool(request)
    if db_pool is None:
        raise ApiError(ErrorCode.service_unavailable, status_code=503, detail="Memory storage unavailable.")

    from app.repositories.memory_repository import MemoryRepository
    repo = MemoryRepository(db_pool)
    found = await repo.archive_memory(claims, memory_id)
    if not found:
        raise ApiError(ErrorCode.turn_not_found, status_code=404, detail="Memory item not found or already removed.")
    return StatusResponse(status="deleted")


@router.delete("/api/memory", response_model=StatusResponse)
async def clear_all_memory(
    request: Request,
    claims: AuthClaims = Depends(get_current_user),
) -> StatusResponse:
    """Archive all remembered items for the authenticated user."""
    db_pool = _get_db_pool(request)
    if db_pool is None:
        raise ApiError(ErrorCode.service_unavailable, status_code=503, detail="Memory storage unavailable.")

    from app.repositories.memory_repository import MemoryRepository
    repo = MemoryRepository(db_pool)
    count = await repo.clear_all_memories(claims)
    return StatusResponse(status=f"cleared:{count}")
