"""
Executive Memory Graph API Router (PRD V2.2 Feature 2).
"""

from __future__ import annotations

import logging
from uuid import UUID
from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.middleware.auth import get_current_user
from app.models.contracts import AuthClaims, MemoryGraphResponse
from app.services.memory_graph import generate_memory_graph

router = APIRouter()
logger = logging.getLogger("voxquery.api.memory_graph")


@router.get("/api/memory-graph/{session_id}", response_model=MemoryGraphResponse)
async def get_memory_graph(
    session_id: UUID,
    claims: AuthClaims = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> MemoryGraphResponse:
    """
    Fetch the multi-turn executive memory graph for a given session.
    """
    logger.info("Fetching memory graph session_id=%s tenant_id=%s", session_id, claims.tenant_id)
    return await generate_memory_graph(session_id, settings)
