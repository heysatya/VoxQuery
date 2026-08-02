"""
Multi-Widget Workspace API Router — Saved Findings.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.middleware.auth import get_current_user
from app.models.contracts import (
    ApiError,
    AuthClaims,
    ErrorCode,
    QueryRequest,
    StatusResponse,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.pipeline import PipelineOrchestrator

router = APIRouter()
logger = logging.getLogger("voxquery.api.workspace")


# ── Dependency helpers ─────────────────────────────────────────────────────────


def get_workspace_repository(request: Request) -> WorkspaceRepository | None:
    pool = getattr(request.app.state, "db_pool", None)
    return WorkspaceRepository(pool) if pool else None


def get_pipeline(request: Request) -> PipelineOrchestrator:
    return request.app.state.pipeline


def get_db_pool(request: Request):
    return getattr(request.app.state, "db_pool", None)


# ── Request models ─────────────────────────────────────────────────────────────


class CreateWidgetRequest(BaseModel):
    turn_id: UUID
    title: str = Field(..., max_length=200)
    note: str | None = None
    headline_value: float | None = None
    headline_label: str | None = None
    layout_x: int = Field(default=0, ge=0)
    layout_y: int = Field(default=0, ge=0)
    layout_w: int = Field(default=4, ge=1, le=12)
    layout_h: int = Field(default=3, ge=1, le=12)


class UpdateLayoutRequest(BaseModel):
    layout_x: int = Field(..., ge=0)
    layout_y: int = Field(..., ge=0)
    layout_w: int = Field(..., ge=1, le=12)
    layout_h: int = Field(..., ge=1, le=12)


class UpdateNoteRequest(BaseModel):
    note: str | None = None


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get("/api/workspace/widgets")
async def get_widgets(
    claims: AuthClaims = Depends(get_current_user),
    repo: WorkspaceRepository | None = Depends(get_workspace_repository),
) -> list[dict[str, Any]]:
    """List current user's saved findings with snapshot data."""
    if repo is None:
        return []
    return await repo.get_user_widgets(claims)


@router.post("/api/workspace/widgets")
async def create_widget(
    request_data: CreateWidgetRequest,
    claims: AuthClaims = Depends(get_current_user),
    repo: WorkspaceRepository | None = Depends(get_workspace_repository),
) -> dict[str, Any]:
    """Save a finding snapshot to current user's workspace."""
    if repo is None:
        raise ApiError(
            ErrorCode.service_unavailable, status_code=501, detail="Database pool unavailable"
        )
    try:
        created = await repo.create_widget(
            claims,
            turn_id=request_data.turn_id,
            title=request_data.title,
            note=request_data.note,
            headline_value=request_data.headline_value,
            headline_label=request_data.headline_label,
            layout_x=request_data.layout_x,
            layout_y=request_data.layout_y,
            layout_w=request_data.layout_w,
            layout_h=request_data.layout_h,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if created is None:
        raise ApiError(
            ErrorCode.turn_not_found,
            status_code=404,
            detail="Completed analysis not found or already saved.",
        )
    return created


@router.delete("/api/workspace/widgets/{widget_id}")
async def delete_widget(
    widget_id: UUID,
    claims: AuthClaims = Depends(get_current_user),
    repo: WorkspaceRepository | None = Depends(get_workspace_repository),
) -> StatusResponse:
    """Delete a saved finding."""
    if repo is None:
        raise ApiError(
            ErrorCode.service_unavailable, status_code=501, detail="Database pool unavailable"
        )
    success = await repo.delete_widget(widget_id, claims)
    if not success:
        raise ApiError(
            ErrorCode.turn_not_found, status_code=404, detail="Widget not found or forbidden"
        )
    return StatusResponse(status="deleted")


@router.patch("/api/workspace/widgets/{widget_id}")
async def update_widget_layout(
    widget_id: UUID,
    layout: UpdateLayoutRequest,
    claims: AuthClaims = Depends(get_current_user),
    repo: WorkspaceRepository | None = Depends(get_workspace_repository),
) -> StatusResponse:
    """Update widget grid layout position and size."""
    if repo is None:
        raise ApiError(
            ErrorCode.service_unavailable, status_code=501, detail="Database pool unavailable"
        )
    success = await repo.update_widget_layout(
        widget_id,
        claims,
        layout_x=layout.layout_x,
        layout_y=layout.layout_y,
        layout_w=layout.layout_w,
        layout_h=layout.layout_h,
    )
    if not success:
        raise ApiError(
            ErrorCode.turn_not_found, status_code=404, detail="Widget not found or forbidden"
        )
    return StatusResponse(status="updated")


@router.patch("/api/workspace/widgets/{widget_id}/note")
async def update_widget_note(
    widget_id: UUID,
    body: UpdateNoteRequest,
    claims: AuthClaims = Depends(get_current_user),
    repo: WorkspaceRepository | None = Depends(get_workspace_repository),
) -> StatusResponse:
    """Update the note on a saved finding."""
    if repo is None:
        raise ApiError(
            ErrorCode.service_unavailable, status_code=501, detail="Database pool unavailable"
        )
    success = await repo.update_widget_note(widget_id, claims, body.note)
    if not success:
        raise ApiError(
            ErrorCode.turn_not_found, status_code=404, detail="Widget not found or forbidden"
        )
    return StatusResponse(status="updated")


@router.post("/api/workspace/widgets/{widget_id}/check-now")
async def check_now(
    widget_id: UUID,
    claims: AuthClaims = Depends(get_current_user),
    repo: WorkspaceRepository | None = Depends(get_workspace_repository),
    pipeline: PipelineOrchestrator = Depends(get_pipeline),
) -> dict:
    """
    Re-run the original question for a saved finding in a throwaway session.

    Returns a turn_id immediately — the frontend polls GET /api/result/{turn_id}
    using the same existing 202-retry contract used for every other query in the app.
    This route never blocks waiting for the result.
    """
    if repo is None:
        raise HTTPException(status_code=501, detail="Database pool unavailable")
    widget = await repo.get_widget(widget_id, claims)
    if widget is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    if not widget.get("original_question"):
        raise HTTPException(
            status_code=400, detail="This finding has no original question stored to re-run"
        )

    # Throwaway session, separate from the user's real conversation, so this can never
    # collide with their active session's one-in-flight-per-session lock in
    # PipelineOrchestrator.submit_query. InMemorySessionStore already sweeps/expires
    # sessions on TTL — no explicit cleanup needed.
    throwaway_session, _ = await pipeline.sessions.create(claims)

    turn = await pipeline.submit_query(
        QueryRequest(
            session_id=throwaway_session.session_id, submitted_text=widget["original_question"]
        ),
        claims,
    )
    # Mirrors QueryAcceptedResponse exactly — the frontend polls GET /api/result/{turn_id},
    # the same existing endpoint and 202-retry contract used for every other query in the app.
    # Do NOT add any polling/waiting logic here — this route must return immediately.
    return {"turn_id": str(turn.turn_id), "status": "processing"}
