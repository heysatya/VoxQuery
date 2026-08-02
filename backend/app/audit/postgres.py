import asyncio
import json
import logging
from datetime import datetime
from typing import Any

import asyncpg

from app.audit.store import AuditStore, AuditIdentity, AuditClarification
from app.models.contracts import TurnRecord
from app.services.telemetry import emit

logger = logging.getLogger(__name__)


class PostgresAuditStore(AuditStore):
    """
    PostgreSQL implementation of AuditStore.
    Uses a same-loop asyncio.Task to manage an asyncpg connection pool
    and process audit writes without blocking the caller.
    """

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._worker_task: asyncio.Task | None = None
        self._pool: asyncpg.Pool | None = None
        self._queue: asyncio.Queue | None = None

    async def start(self) -> None:
        if self._queue is None:
            self._queue = asyncio.Queue()
        try:
            self._pool = await asyncpg.create_pool(
                self.dsn, min_size=1, max_size=5, statement_cache_size=0
            )
        except Exception as e:
            logger.error(f"Failed to create asyncpg pool for audit store: {e}")
            return

        self._worker_task = asyncio.create_task(self._async_worker_loop())

    async def stop(self) -> None:
        if self._queue:
            self._queue.put_nowait(("stop", None))
        if self._worker_task:
            try:
                await asyncio.wait_for(self._worker_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._worker_task.cancel()
        if self._pool:
            await self._pool.close()

    def enqueue_turn(
        self,
        turn: TurnRecord,
        identity: AuditIdentity,
        clarification: AuditClarification | None = None,
    ) -> None:
        try:
            # EXPLICIT INVARIANT: Never serialize or store full_result (raw rows)
            turn_data = turn.model_dump(exclude={"full_result"}, mode="json")

            # Explicit runtime validation guard against raw data leakage
            result_json = turn_data.get("result_json") or {}
            if "rows" in result_json:
                emit("audit.turn.security_violation", tier=1, turn_id=str(turn.turn_id))
                return

            if self._queue:
                payload = {
                    "turn": turn_data,
                    "identity": identity.__dict__,
                    "clarification": clarification.__dict__ if clarification else None,
                }
                self._queue.put_nowait(("turn", payload))
        except Exception as e:
            emit("audit.turn.enqueue_error", tier=1, error=str(e), turn_id=str(turn.turn_id))

    def enqueue_feedback(self, turn_id: str, quality_flag: str) -> None:
        if self._queue:
            self._queue.put_nowait(("feedback", turn_id, quality_flag))

    async def check_health(self) -> str:
        """Check Postgres connectivity with a 10-second timeout."""
        try:
            conn = await asyncio.wait_for(asyncpg.connect(self.dsn), timeout=10.0)
            await conn.close()
            return "ok"
        except Exception as e:
            logger.warning(f"Audit store health check failed: {e}")
            return "degraded"

    async def _async_worker_loop(self) -> None:
        while True:
            try:
                item = await self._queue.get()

                op = item[0]
                if op == "stop":
                    self._queue.task_done()
                    break
            except Exception as e:
                emit("audit.worker.queue_read_error", tier=1, error=str(e))
                continue

            try:
                if op == "turn":
                    await self._insert_turn(item[1])
                elif op == "feedback":
                    await self._update_feedback(item[1], item[2])
                self._queue.task_done()
            except Exception as e:
                emit("audit.worker.process_error", tier=1, op=item[0], error=str(e))

    async def _insert_turn(self, payload: dict[str, Any]) -> None:
        turn_data = payload["turn"]
        identity = payload["identity"]
        clarification = payload.get("clarification")

        result_json_str = (
            json.dumps(turn_data["result_json"]) if turn_data.get("result_json") else "{}"
        )

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # 1. Upsert tenant
                await conn.execute(
                    """
                    INSERT INTO tenants (id, name) VALUES ($1, $2)
                    ON CONFLICT (id) DO NOTHING
                """,
                    identity["tenant_id"],
                    identity.get("tenant_name", "Unknown"),
                )

                # 2. Upsert user
                await conn.execute(
                    """
                    INSERT INTO users (id, email) VALUES ($1, $2)
                    ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email
                """,
                    identity["user_id"],
                    identity.get("email", ""),
                )

                # 2b. Upsert tenant_memberships
                await conn.execute(
                    """
                    INSERT INTO tenant_memberships (tenant_id, user_id, role) VALUES ($1, $2, $3)
                    ON CONFLICT (tenant_id, user_id) DO UPDATE
                    SET role = EXCLUDED.role, updated_at = NOW()
                    WHERE tenant_memberships.deleted_at IS NULL
                """,
                    identity["tenant_id"],
                    identity["user_id"],
                    identity.get("role", "viewer"),
                )

                # 3. Upsert user_snowflake_roles
                if identity.get("snowflake_role"):
                    await conn.execute(
                        """
                        INSERT INTO user_snowflake_roles (tenant_id, user_id, snowflake_role) VALUES ($1, $2, $3)
                        ON CONFLICT (tenant_id, user_id) DO UPDATE SET snowflake_role = EXCLUDED.snowflake_role
                    """,
                        identity["tenant_id"],
                        identity["user_id"],
                        identity["snowflake_role"],
                    )

                # 4. Upsert conversation
                await conn.execute(
                    """
                    INSERT INTO conversations (id, tenant_id, user_id, title) VALUES ($1::uuid, $2, $3, $4)
                    ON CONFLICT (id) DO NOTHING
                """,
                    identity["conversation_id"],
                    identity["tenant_id"],
                    identity["user_id"],
                    identity.get("conversation_title", "New Conversation"),
                )

                # 5. Insert turn (handling turns.turn_id vs turns.id)
                turn_col = "turn_id" if "turn_id" in turn_data else "id"
                await conn.execute(
                    f"""
                    INSERT INTO turns (
                        {turn_col}, conversation_id, user_id, tenant_id, user_input, raw_transcript,
                        deepgram_confidence_raw, generated_sql, result_json, chart_type,
                        chart_rationale, confidence_tier, composite_score, clarification_triggered,
                        quality_flag, source, input_modality, latency_ms, created_at
                    ) VALUES (
                        $1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19::timestamptz
                    ) ON CONFLICT ({turn_col}) DO NOTHING
                """,
                    turn_data.get("turn_id") or turn_data.get("id"),
                    turn_data["conversation_id"],
                    turn_data["user_id"],
                    turn_data["tenant_id"],
                    turn_data["user_input"],
                    turn_data.get("raw_transcript"),
                    turn_data.get("deepgram_confidence_raw"),
                    turn_data.get("generated_sql", ""),
                    result_json_str,
                    turn_data.get("chart_type", "stat"),
                    turn_data.get("chart_rationale", ""),
                    turn_data.get("confidence_tier", "low"),
                    float(turn_data.get("composite_score", 0.0) or 0.0),
                    bool(turn_data.get("clarification_triggered", False)),
                    turn_data.get("quality_flag", "ok"),
                    turn_data.get("source", "user"),
                    turn_data.get("input_modality", "text"),
                    int(turn_data.get("latency_ms", 0) or 0),
                    datetime.fromisoformat(turn_data["created_at"].replace("Z", "+00:00")),
                )

                # 6. Insert clarification if present
                if clarification:
                    await conn.execute(
                        """
                        INSERT INTO clarifications (
                            id, turn_id, prompt_sent, user_choice, resolution_type, created_at
                        ) VALUES (
                            gen_random_uuid(), $1::uuid, $2, $3, $4, now()
                        )
                    """,
                        clarification["turn_id"],
                        clarification["prompt_sent"],
                        clarification.get("user_choice"),
                        clarification["resolution_type"],
                    )

    async def _update_feedback(self, turn_id: str, quality_flag: str) -> None:
        query = (
            "UPDATE turns SET quality_flag = $1, feedback_submitted = TRUE WHERE turn_id = $2::uuid"
        )
        async with self._pool.acquire() as conn:
            await conn.execute(query, quality_flag, turn_id)

    async def get_low_quality_feedback(
        self, limit: int = 50, offset: int = 0, tenant_id: str | None = None
    ) -> list[dict]:
        query = """
            SELECT COALESCE(t.turn_id, t.id) as turn_id, t.conversation_id, t.user_input, t.raw_transcript, 
                   t.generated_sql, t.chart_type, t.created_at, u.email as user_email
            FROM turns t
            LEFT JOIN users u ON t.user_id = u.id
            WHERE t.quality_flag = 'low'
              AND ($1::text IS NULL OR t.tenant_id = $1::text)
            ORDER BY t.created_at DESC
            LIMIT $2 OFFSET $3
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, tenant_id, limit, offset)
            return [dict(row) for row in rows]
