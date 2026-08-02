"""
Executive Memory Graph API Router (PRD V2.2 Feature 2).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, Request

from app.config import Settings, get_settings
from app.middleware.auth import get_current_user
from app.models.contracts import AuthClaims, MemoryGraphResponse
from app.services.memory_graph import generate_memory_graph
from app.repositories.turn_repository import TurnRepository

router = APIRouter()
logger = logging.getLogger("voxquery.api.memory_graph")


@router.get("/api/memory-graph/{session_id}", response_model=MemoryGraphResponse)
async def get_memory_graph(
    session_id: UUID,
    request: Request,
    claims: AuthClaims = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> MemoryGraphResponse:
    """
    Fetch the tenant-scoped analysis recap for a given session.
    """
    logger.info("Fetching analysis recap session_id=%s tenant_id=%s", session_id, claims.tenant_id)

    turns: list[dict[str, Any]] = []

    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool:
        try:
            repo = TurnRepository(db_pool)
            turns = await repo.get_session_turns(session_id, claims)
        except Exception as e:
            logger.warning("Could not fetch session turns from repository: %s", e)

    if not turns:
        pipeline = getattr(request.app.state, "pipeline", None)
        if pipeline and hasattr(pipeline, "turns"):
            mem_turns = [
                t
                for t in pipeline.turns.values()
                if t.session_id == session_id and t.tenant_id == claims.tenant_id
            ]
            mem_turns.sort(key=lambda x: x.created_at)
            turns = [
                {
                    "user_input": t.user_input,
                    "chart_type": t.chart_type.value if t.chart_type else "bar",
                    "source_tables": [],
                    "filter_predicates": [],
                }
                for t in mem_turns
            ]

    return await generate_memory_graph(session_id, settings, turns=turns)
