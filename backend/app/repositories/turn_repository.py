"""Durable turn persistence repository. Replaces in-memory PipelineOrchestrator.turns."""
from __future__ import annotations
import json
import logging
from typing import Any
from uuid import UUID
import asyncpg

from app.models.contracts import TurnRecord, AuthClaims

logger = logging.getLogger(__name__)


class TurnRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def save(
        self,
        turn: TurnRecord,
        *,
        source_tables: list[str] | None = None,
        filter_predicates: list[dict[str, Any]] | None = None,
    ) -> None:
        """Persists a TurnRecord to Postgres with multi-tenant scoping and row capping."""
        source_tables = source_tables or []
        filter_predicates = filter_predicates or []

        # Cap full_result rows to 500 max per turn to bound storage payload
        full_result_json = None
        if turn.full_result:
            capped_result = turn.full_result.model_copy()
            if len(capped_result.rows) > 500:
                capped_result.rows = capped_result.rows[:500]
                capped_result.preview_row_count = 500
                capped_result.is_truncated = True
            full_result_json = capped_result.model_dump_json()

        result_json_str = turn.result_json.model_dump_json() if turn.result_json else "{}"
        modality_str = turn.input_modality.value if hasattr(turn.input_modality, "value") else str(turn.input_modality)
        chart_type_str = turn.chart_type.value if turn.chart_type else "table"
        confidence_tier_str = turn.confidence_tier.value if turn.confidence_tier else "high"

        async with self._pool.acquire() as conn:
            # Ensure tenant, user, session, and conversation records exist for foreign key constraints
            await conn.execute(
                "INSERT INTO tenants (id, name) VALUES ($1, 'Default Tenant') ON CONFLICT (id) DO NOTHING",
                turn.tenant_id,
            )
            await conn.execute(
                """
                INSERT INTO users (id, email)
                VALUES ($1, $2)
                ON CONFLICT (id) DO NOTHING
                """,
                turn.user_id, f"user-{turn.user_id}@system.local",
            )
            await conn.execute(
                """
                INSERT INTO sessions (session_id, tenant_id, user_id, last_active_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (session_id) DO UPDATE SET last_active_at = NOW()
                """,
                turn.session_id, turn.tenant_id, turn.user_id,
            )
            await conn.execute(
                """
                INSERT INTO conversations (id, user_id, tenant_id, title)
                VALUES ($1, $2, $3, 'Voice Session')
                ON CONFLICT (id) DO NOTHING
                """,
                turn.conversation_id, turn.user_id, turn.tenant_id,
            )

            await conn.execute(
                """
                INSERT INTO turns (
                    turn_id, session_id, conversation_id, parent_turn_id, tenant_id, user_id,
                    user_input, input_modality, generated_sql, source_tables, filter_predicates,
                    chart_type, chart_rationale, confidence_tier, composite_score,
                    result_json, full_result, anomalies, proactive_questions,
                    quality_flag, latency_ms, created_at, completed
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23)
                ON CONFLICT (turn_id) DO UPDATE SET
                    input_modality = EXCLUDED.input_modality,
                    generated_sql = EXCLUDED.generated_sql,
                    source_tables = EXCLUDED.source_tables,
                    filter_predicates = EXCLUDED.filter_predicates,
                    chart_type = EXCLUDED.chart_type,
                    chart_rationale = EXCLUDED.chart_rationale,
                    confidence_tier = EXCLUDED.confidence_tier,
                    composite_score = EXCLUDED.composite_score,
                    result_json = EXCLUDED.result_json,
                    full_result = EXCLUDED.full_result,
                    anomalies = EXCLUDED.anomalies,
                    proactive_questions = EXCLUDED.proactive_questions,
                    quality_flag = EXCLUDED.quality_flag,
                    latency_ms = EXCLUDED.latency_ms,
                    completed = EXCLUDED.completed
                """,
                turn.turn_id, turn.session_id, turn.conversation_id, turn.parent_turn_id,
                turn.tenant_id, turn.user_id, turn.user_input, modality_str, turn.generated_sql,
                source_tables, json.dumps(filter_predicates),
                chart_type_str, turn.chart_rationale or "",
                confidence_tier_str, turn.composite_score or 1.0,
                result_json_str,
                full_result_json,
                json.dumps([]),
                json.dumps(turn.proactive_questions),
                turn.quality_flag.value if hasattr(turn.quality_flag, "value") else str(turn.quality_flag),
                turn.latency_ms, turn.created_at, turn.completed,
            )

    async def get_session_turns(self, session_id: UUID, claims: AuthClaims, *, limit: int = 50) -> list[dict[str, Any]]:
        """Tenant-scoped turn fetch — enforces tenant_id = claims.tenant_id."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM turns
                WHERE session_id = $1 AND tenant_id = $2
                ORDER BY created_at ASC
                LIMIT $3
                """,
                session_id, claims.tenant_id, limit,
            )
        return [self._parse_row(r) for r in rows]

    async def get_turn(self, turn_id: UUID, claims: AuthClaims) -> dict[str, Any] | None:
        """Tenant-scoped single turn fetch."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM turns WHERE turn_id = $1 AND tenant_id = $2",
                turn_id, claims.tenant_id,
            )
        return self._parse_row(row) if row else None

    async def update_anomalies(self, turn_id: UUID, anomalies: list[dict[str, Any]]) -> None:
        """Update anomalies JSONB column for a completed turn."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE turns SET anomalies = $2 WHERE turn_id = $1",
                turn_id, json.dumps(anomalies),
            )

    def _parse_row(self, row: asyncpg.Record | None) -> dict[str, Any] | None:
        if row is None:
            return None
        d = dict(row)
        if isinstance(d.get("filter_predicates"), str):
            d["filter_predicates"] = json.loads(d["filter_predicates"])
        if isinstance(d.get("anomalies"), str):
            d["anomalies"] = json.loads(d["anomalies"])
        if isinstance(d.get("proactive_questions"), str):
            d["proactive_questions"] = json.loads(d["proactive_questions"])
        if isinstance(d.get("result_json"), str):
            d["result_json"] = json.loads(d["result_json"])
        if isinstance(d.get("full_result"), str):
            d["full_result"] = json.loads(d["full_result"])
        return d
