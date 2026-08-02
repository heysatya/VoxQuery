"""
Durable executive memory repository.

Stores and retrieves explainable, user-scoped, tenant-scoped preferences and
recurring interests. Every query is scoped by BOTH tenant_id AND user_id.

Only stores memory types that can be explained plainly to the user:
- metric_interest: a metric the user asked about repeatedly
- dimension_interest: a business dimension (region, product, etc.) the user focuses on
- time_range: a recurring time window preference
- filter_preference: a recurring filter selection
- clarification_resolution: an explicit choice the user made to resolve ambiguity
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg

from app.models.contracts import AuthClaims

logger = logging.getLogger("voxquery.repositories.memory")

VALID_MEMORY_TYPES = frozenset({
    "metric_interest",
    "dimension_interest",
    "time_range",
    "filter_preference",
    "clarification_resolution",
})


class MemoryRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert_memory(
        self,
        claims: AuthClaims,
        *,
        memory_type: str,
        subject: str,
        label: str,
        source_turn_id: UUID | None = None,
        source_session_id: UUID | None = None,
        confidence: float = 0.8,
    ) -> dict[str, Any] | None:
        """
        Upsert an active memory item for the user within their tenant.

        On conflict (same tenant/user/type/subject, not archived): updates
        label, confidence, last_observed_at, updated_at, and source attribution.

        Returns the resulting row or None on error.
        """
        if memory_type not in VALID_MEMORY_TYPES:
            logger.warning("upsert_memory: invalid memory_type=%s – skipping", memory_type)
            return None
        if not subject or not subject.strip():
            return None
        if not label or not label.strip():
            return None

        subject = subject.strip().lower()[:200]
        label = label.strip()[:400]
        confidence = max(0.0, min(1.0, confidence))

        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO executive_memory
                        (tenant_id, user_id, memory_type, subject, label,
                         source_turn_id, source_session_id, confidence,
                         last_observed_at, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), NOW(), NOW())
                    ON CONFLICT ON CONSTRAINT uq_executive_memory_active
                    DO UPDATE SET
                        label             = EXCLUDED.label,
                        confidence        = EXCLUDED.confidence,
                        source_turn_id    = COALESCE(EXCLUDED.source_turn_id, executive_memory.source_turn_id),
                        source_session_id = COALESCE(EXCLUDED.source_session_id, executive_memory.source_session_id),
                        last_observed_at  = NOW(),
                        updated_at        = NOW()
                    RETURNING *
                    """,
                    claims.tenant_id,
                    claims.user_id,
                    memory_type,
                    subject,
                    label,
                    source_turn_id,
                    source_session_id,
                    confidence,
                )
            return dict(row) if row else None
        except Exception as exc:
            logger.warning("upsert_memory failed: %s", exc)
            return None

    async def get_active_memories(
        self,
        claims: AuthClaims,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Return all active (not archived) memories for the user in their tenant,
        ordered by most recently observed first.
        """
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, memory_type, subject, label, confidence,
                           last_observed_at, created_at, source_turn_id
                    FROM executive_memory
                    WHERE tenant_id = $1
                      AND user_id   = $2
                      AND archived_at IS NULL
                    ORDER BY last_observed_at DESC
                    LIMIT $3
                    """,
                    claims.tenant_id,
                    claims.user_id,
                    limit,
                )
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("get_active_memories failed: %s", exc)
            return []

    async def get_memory_context(
        self,
        claims: AuthClaims,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Return the most relevant active memories for injecting into the next
        conversation context. Returns highest-confidence items first.
        """
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT memory_type, subject, label, confidence
                    FROM executive_memory
                    WHERE tenant_id   = $1
                      AND user_id     = $2
                      AND archived_at IS NULL
                    ORDER BY confidence DESC, last_observed_at DESC
                    LIMIT $3
                    """,
                    claims.tenant_id,
                    claims.user_id,
                    limit,
                )
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("get_memory_context failed: %s", exc)
            return []

    async def archive_memory(
        self,
        claims: AuthClaims,
        memory_id: str,
    ) -> bool:
        """
        Soft-delete a single memory item. Scoped to tenant_id + user_id.
        Returns True if a row was archived, False if not found or already archived.
        """
        try:
            async with self._pool.acquire() as conn:
                result = await conn.fetchval(
                    """
                    UPDATE executive_memory
                    SET archived_at = NOW(), updated_at = NOW()
                    WHERE id        = $1
                      AND tenant_id = $2
                      AND user_id   = $3
                      AND archived_at IS NULL
                    RETURNING id
                    """,
                    memory_id,
                    claims.tenant_id,
                    claims.user_id,
                )
            return result is not None
        except Exception as exc:
            logger.warning("archive_memory failed: %s", exc)
            return False

    async def clear_all_memories(self, claims: AuthClaims) -> int:
        """
        Archive all active memories for the user in their tenant.
        Returns the number of items archived.
        """
        try:
            async with self._pool.acquire() as conn:
                count = await conn.fetchval(
                    """
                    WITH archived AS (
                        UPDATE executive_memory
                        SET archived_at = NOW(), updated_at = NOW()
                        WHERE tenant_id   = $1
                          AND user_id     = $2
                          AND archived_at IS NULL
                        RETURNING id
                    )
                    SELECT COUNT(*) FROM archived
                    """,
                    claims.tenant_id,
                    claims.user_id,
                )
            return int(count or 0)
        except Exception as exc:
            logger.warning("clear_all_memories failed: %s", exc)
            return 0


def extract_memory_candidates(
    turn_metadata: dict[str, Any],
    user_input: str,
    confidence: float,
) -> list[dict[str, Any]]:
    """
    Extract explainable memory candidates from a completed turn's metadata.

    Only extracts items that can be plainly described to the user. Never stores
    raw SQL, raw warehouse rows, or inferred personal attributes.

    Returns a list of dicts with keys: memory_type, subject, label, confidence
    """
    candidates: list[dict[str, Any]] = []

    source_tables: list[str] = turn_metadata.get("source_tables") or []
    filter_predicates: list[Any] = turn_metadata.get("filter_predicates") or []
    metric_name: str | None = turn_metadata.get("metric_name") or turn_metadata.get("metric")
    chart_type: str | None = turn_metadata.get("chart_type")

    # Metric interest — only from clearly identified metrics
    if metric_name and len(metric_name) <= 80:
        normalized = metric_name.strip().lower().replace(" ", "_")
        candidates.append({
            "memory_type": "metric_interest",
            "subject": normalized,
            "label": metric_name.strip(),
            "confidence": min(1.0, confidence + 0.1),
        })

    # Dimension interest — from source tables (not raw SQL names, but display names)
    for table in source_tables[:3]:
        if table and len(table) <= 60:
            normalized = table.strip().lower()
            display = table.strip().replace("_", " ").title()
            candidates.append({
                "memory_type": "dimension_interest",
                "subject": normalized,
                "label": f"Data from {display}",
                "confidence": confidence,
            })

    # Time range — detect common patterns in user_input
    lowered = user_input.lower()
    time_hints = [
        ("last quarter", "last_quarter", "Last quarter"),
        ("last month", "last_month", "Last month"),
        ("this year", "this_year", "This year"),
        ("ytd", "ytd", "Year to date"),
        ("last 30 days", "last_30d", "Last 30 days"),
        ("last 7 days", "last_7d", "Last 7 days"),
        ("this quarter", "this_quarter", "This quarter"),
        ("last year", "last_year", "Last year"),
    ]
    for phrase, subj, lbl in time_hints:
        if phrase in lowered:
            candidates.append({
                "memory_type": "time_range",
                "subject": subj,
                "label": lbl,
                "confidence": confidence,
            })
            break  # only one time range per turn

    # Filter preference — from explicit filter predicates
    for pred in filter_predicates[:2]:
        if not isinstance(pred, dict):
            continue
        col = str(pred.get("column") or "").strip()
        val = str(pred.get("value") or "").strip()
        if col and val and len(col) <= 60 and len(val) <= 80:
            normalized = f"{col}={val}".lower()
            candidates.append({
                "memory_type": "filter_preference",
                "subject": normalized,
                "label": f"{col.replace('_', ' ').title()} filtered to {val}",
                "confidence": max(0.5, confidence - 0.1),
            })

    return candidates
