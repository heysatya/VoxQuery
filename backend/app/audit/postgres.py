import asyncio
import json
import logging
import threading
from typing import Any

import asyncpg

from app.audit.store import AuditStore, AuditIdentity, AuditClarification
from app.models.contracts import TurnRecord
from app.services.telemetry import emit

logger = logging.getLogger(__name__)

class PostgresAuditStore(AuditStore):
    """
    PostgreSQL implementation of AuditStore.
    Uses a background thread and asyncio loop to manage an asyncpg connection pool
    and process audit writes without blocking the caller.
    """
    
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._pool: asyncpg.Pool | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        
    async def start(self) -> None:
        self._worker_thread = threading.Thread(target=self._run_worker, daemon=True)
        self._worker_thread.start()
        # Wait until the background loop and queue are ready
        while self._loop is None or self._queue is None:
            await asyncio.sleep(0.01)
            
    async def stop(self) -> None:
        self._stop_event.set()
        if self._worker_thread:
            # We don't await thread join, we just run it in executor or block lightly
            # since stop() is usually called during graceful shutdown
            await asyncio.get_running_loop().run_in_executor(None, self._worker_thread.join, 5.0)
            
    def enqueue_turn(self, turn: TurnRecord, identity: AuditIdentity, clarification: AuditClarification | None = None) -> None:
        try:
            # EXPLICIT INVARIANT: Never serialize or store full_result (raw rows)
            turn_data = turn.model_dump(exclude={"full_result"}, mode="json")
            
            # Explicit runtime validation guard against raw data leakage
            result_json = turn_data.get("result_json") or {}
            if "rows" in result_json:
                emit("audit.turn.security_violation", tier=1, turn_id=str(turn.turn_id))
                return
                
            if self._loop and self._queue:
                payload = {
                    "turn": turn_data,
                    "identity": identity.__dict__,
                    "clarification": clarification.__dict__ if clarification else None
                }
                self._loop.call_soon_threadsafe(self._queue.put_nowait, ("turn", payload))
        except Exception as e:
            emit("audit.turn.enqueue_error", tier=1, error=str(e), turn_id=str(turn.turn_id))

    def enqueue_feedback(self, turn_id: str, quality_flag: str) -> None:
        if self._loop and self._queue:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, ("feedback", turn_id, quality_flag))
            
    async def check_health(self) -> str:
        """Check Postgres connectivity within a strict 100ms timeout."""
        try:
            conn = await asyncio.wait_for(asyncpg.connect(self.dsn), timeout=0.1)
            await conn.close()
            return "ok"
        except Exception as e:
            logger.warning(f"Audit store health check failed: {e}")
            return "degraded"
            
    def _run_worker(self) -> None:
        """Entry point for the background thread."""
        asyncio.run(self._async_worker_loop())
        
    async def _async_worker_loop(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._queue is None:
            self._queue = asyncio.Queue()
        
        try:
            self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)
        except Exception as e:
            logger.error(f"Failed to create asyncpg pool for audit store: {e}")
            return
            
        while not self._stop_event.is_set():
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                emit("audit.worker.queue_read_error", tier=1, error=str(e))
                continue
                
            try:
                op = item[0]
                if op == "turn":
                    await self._insert_turn(item[1])
                elif op == "feedback":
                    await self._update_feedback(item[1], item[2])
                self._queue.task_done()
            except Exception as e:
                emit("audit.worker.process_error", tier=1, op=item[0], error=str(e))
                
        if self._pool:
            await self._pool.close()
            
    async def _insert_turn(self, payload: dict[str, Any]) -> None:
        turn_data = payload["turn"]
        identity = payload["identity"]
        clarification = payload.get("clarification")
        
        result_json_str = json.dumps(turn_data["result_json"]) if turn_data.get("result_json") else "{}"
        
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # 1. Upsert tenant
                await conn.execute("""
                    INSERT INTO tenants (id, name) VALUES ($1::uuid, $2)
                    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                """, identity["tenant_id"], identity.get("tenant_name", "Unknown"))
                
                # 2. Upsert user
                await conn.execute("""
                    INSERT INTO users (id, email, role, tenant_id) VALUES ($1::uuid, $2, $3, $4::uuid)
                    ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email, role = EXCLUDED.role, tenant_id = EXCLUDED.tenant_id
                """, identity["user_id"], identity.get("email", ""), identity.get("role", "viewer"), identity["tenant_id"])
                
                # 3. Upsert user_snowflake_roles
                if identity.get("snowflake_role"):
                    await conn.execute("""
                        INSERT INTO user_snowflake_roles (user_id, snowflake_role) VALUES ($1::uuid, $2)
                        ON CONFLICT (user_id) DO UPDATE SET snowflake_role = EXCLUDED.snowflake_role
                    """, identity["user_id"], identity["snowflake_role"])
                    
                # 4. Upsert conversation
                await conn.execute("""
                    INSERT INTO conversations (id, tenant_id, user_id, title) VALUES ($1::uuid, $2::uuid, $3::uuid, $4)
                    ON CONFLICT (id) DO NOTHING
                """, identity["conversation_id"], identity["tenant_id"], identity["user_id"], identity.get("conversation_title", "New Conversation"))
                
                # 5. Insert turn
                await conn.execute("""
                    INSERT INTO turns (
                        id, conversation_id, user_id, tenant_id, user_input, raw_transcript,
                        deepgram_confidence_raw, generated_sql, result_json, chart_type,
                        chart_rationale, confidence_tier, composite_score, clarification_triggered,
                        quality_flag, source, input_modality, latency_ms, created_at
                    ) VALUES (
                        $1::uuid, $2::uuid, $3::uuid, $4::uuid, $5, $6, $7, $8, $9::jsonb, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19::timestamptz
                    ) ON CONFLICT (id) DO NOTHING
                """,
                    turn_data["turn_id"], turn_data["conversation_id"], turn_data["user_id"], turn_data["tenant_id"],
                    turn_data["user_input"], turn_data.get("raw_transcript"), turn_data.get("deepgram_confidence_raw"),
                    turn_data.get("generated_sql", ""), result_json_str, turn_data.get("chart_type", "stat"),
                    turn_data.get("chart_rationale", ""), turn_data.get("confidence_tier", "low"),
                    float(turn_data.get("composite_score", 0.0) or 0.0), bool(turn_data.get("clarification_triggered", False)),
                    turn_data.get("quality_flag", "ok"), turn_data.get("source", "user"), turn_data.get("input_modality", "text"),
                    int(turn_data.get("latency_ms", 0) or 0), turn_data["created_at"]
                )
                
                # 6. Insert clarification if present
                if clarification:
                    await conn.execute("""
                        INSERT INTO clarifications (
                            turn_id, status, requested_at, resolution_type, options_json
                        ) VALUES (
                            $1::uuid, $2, $3::timestamptz, $4, $5::jsonb
                        ) ON CONFLICT (turn_id) DO NOTHING
                    """,
                        clarification["turn_id"], clarification["status"], clarification["requested_at"],
                        clarification["resolution_type"], json.dumps(clarification.get("options", []))
                    )
            
    async def _update_feedback(self, turn_id: str, quality_flag: str) -> None:
        query = "UPDATE turns SET quality_flag = $1 WHERE id = $2::uuid"
        async with self._pool.acquire() as conn:
            await conn.execute(query, quality_flag, turn_id)
