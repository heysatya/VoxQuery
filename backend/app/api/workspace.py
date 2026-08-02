"""
Multi-Widget Workspace API Router.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.middleware.auth import get_current_user
from app.models.contracts import ApiError, AuthClaims, ErrorCode, StatusResponse
from app.repositories.workspace_repository import WorkspaceRepository

router = APIRouter()
logger = logging.getLogger("voxquery.api.workspace")


class CreateWidgetRequest(BaseModel):
    turn_id: UUID
    title: str = Field(..., max_length=200)
    layout_x: int = Field(default=0, ge=0)
    layout_y: int = Field(default=0, ge=0)
    layout_w: int = Field(default=4, ge=1, le=12)
    layout_h: int = Field(default=3, ge=1, le=12)


class UpdateLayoutRequest(BaseModel):
    layout_x: int = Field(..., ge=0)
    layout_y: int = Field(..., ge=0)
    layout_w: int = Field(..., ge=1, le=12)
    layout_h: int = Field(..., ge=1, le=12)


def get_workspace_repository(request: Request) -> WorkspaceRepository | None:
    pool = getattr(request.app.state, "db_pool", None)
    return WorkspaceRepository(pool) if pool else None


@router.get("/api/workspace/widgets")
async def get_widgets(
    claims: AuthClaims = Depends(get_current_user),
    repo: WorkspaceRepository | None = Depends(get_workspace_repository),
) -> list[dict[str, Any]]:
    """List current user's pinned workspace widgets with joined turn data."""
    if repo is None:
        return []
    return await repo.get_user_widgets(claims)


@router.post("/api/workspace/widgets")
async def create_widget(
    request_data: CreateWidgetRequest,
    claims: AuthClaims = Depends(get_current_user),
    repo: WorkspaceRepository | None = Depends(get_workspace_repository),
) -> dict[str, Any]:
    """Pin a widget to current user's workspace."""
    if repo is None:
        raise ApiError(ErrorCode.service_unavailable, status_code=501, detail="Database pool unavailable")
    created = await repo.create_widget(
        claims,
        turn_id=request_data.turn_id,
        title=request_data.title,
        layout_x=request_data.layout_x,
        layout_y=request_data.layout_y,
        layout_w=request_data.layout_w,
        layout_h=request_data.layout_h,
    )
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
    """Delete a pinned widget."""
    if repo is None:
        raise ApiError(ErrorCode.service_unavailable, status_code=501, detail="Database pool unavailable")
    success = await repo.delete_widget(widget_id, claims)
    if not success:
        raise ApiError(ErrorCode.turn_not_found, status_code=404, detail="Widget not found or forbidden")
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
        raise ApiError(ErrorCode.service_unavailable, status_code=501, detail="Database pool unavailable")
    success = await repo.update_widget_layout(
        widget_id,
        claims,
        layout_x=layout.layout_x,
        layout_y=layout.layout_y,
        layout_w=layout.layout_w,
        layout_h=layout.layout_h,
    )
    if not success:
        raise ApiError(ErrorCode.turn_not_found, status_code=404, detail="Widget not found or forbidden")
    return StatusResponse(status="updated")
