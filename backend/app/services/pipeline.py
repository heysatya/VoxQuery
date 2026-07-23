from __future__ import annotations
from typing import Any
import asyncio
import hashlib
import json
import logging
from time import perf_counter

logger = logging.getLogger(__name__)
from uuid import UUID

from app.audit.store import AuditStore, AuditClarification
from app.config import Settings, get_settings
from app.core.session import InMemorySessionStore
from app.models.contracts import (
    ApiError,
    AuthClaims,
    ClarificationResolutionType,
    ErrorCode,
    ERROR_MESSAGES,
    PipelineErrorEvent,
    PipelineProgressEvent,
    PipelineStage,
    QueryRequest,
    ResultPayload,
    ResultShape,
    ResultWarning,
    TurnRecord,
)
from app.services.events import PipelineEventBus
from app.rag.retriever import SchemaRetriever
from app.llm.adapter import LlmAdapter, Storyteller
from app.warehouse.connector import WarehouseConnector
from app.services.providers import (
    FakeChartSelector,
    FakeSchemaRetriever,
    FakeSqlGenerator,
    FakeStoryteller,
    FakeWarehouseConnector,
)
from app.observability.langfuse import tracer


class PipelineOrchestrator:
    def __init__(
        self,
        sessions: InMemorySessionStore,
        events: PipelineEventBus,
        audit: AuditStore,
        settings: Settings | None = None,
        schema: SchemaRetriever | None = None,
        llm: LlmAdapter | None = None,
        warehouse: WarehouseConnector | None = None,
        story: Storyteller | None = None,
        db_pool: Any = None,
    ) -> None:
        self.sessions = sessions
        self.events = events
        self.audit = audit
        self.settings = settings or get_settings()
        self.schema = schema or FakeSchemaRetriever()
        self.llm = llm or FakeSqlGenerator()
        self.warehouse = warehouse or FakeWarehouseConnector()
        self.chart = FakeChartSelector()
        self.story = story or FakeStoryteller()
        self.db_pool = db_pool
        self.turns: dict[UUID, TurnRecord] = {}
        self._in_flight: set[UUID] = set()
        self._background_tasks: set[asyncio.Task] = set()

    async def submit_query(self, request: QueryRequest, claims: AuthClaims) -> TurnRecord:
        session = await self.sessions.get_for_claims(claims, request.session_id)
        if session is None:
            raise ApiError(ErrorCode.session_not_found, status_code=404)
        if request.session_id in self._in_flight:
            raise ApiError(ErrorCode.pipeline_in_flight, status_code=409)

        if request.parent_turn_id is not None:
            self._validate_parent_turn(request.parent_turn_id, session, claims)

        turn = TurnRecord(
            session_id=session.session_id,
            conversation_id=session.conversation_id,
            parent_turn_id=request.parent_turn_id,
            user_id=claims.user_id,
            tenant_id=claims.tenant_id,
            user_input=request.submitted_text,
            raw_transcript=request.raw_transcript,
            deepgram_confidence_raw=request.stt_confidence,
            transcript_edited=request.transcript_edited,
            input_modality=request.input_modality,
        )
        self.turns[turn.turn_id] = turn

        self._in_flight.add(request.session_id)
        self._schedule_pipeline_task(self._run_turn_background(session, turn, claims), session.session_id)
        return turn

    def _validate_parent_turn(self, parent_turn_id: UUID, session, claims: AuthClaims) -> TurnRecord:
        parent = self.turns.get(parent_turn_id)
        if parent is None:
            raise ApiError(ErrorCode.turn_not_found, status_code=404)
        if parent.user_id != claims.user_id or parent.tenant_id != claims.tenant_id:
            raise ApiError(ErrorCode.turn_forbidden, status_code=403)
        if parent.session_id != session.session_id or parent.conversation_id != session.conversation_id:
            raise ApiError(ErrorCode.turn_forbidden, status_code=403)
        if not parent.completed:
            raise ApiError(ErrorCode.turn_processing, status_code=409)
        return parent

    async def resolve_clarification(
        self,
        *,
        session_id: UUID,
        turn_id: UUID,
        selection: str | None,
        resolution_type: ClarificationResolutionType,
        claims: AuthClaims,
    ) -> TurnRecord | None:
        session = await self.sessions.get_for_claims(claims, session_id)
        if session is None:
            raise ApiError(ErrorCode.session_not_found, status_code=404)
        state = session.clarification_state
        if state is None or state.turn_id != turn_id:
            raise ApiError(ErrorCode.clarification_not_found, status_code=404)

        if resolution_type == ClarificationResolutionType.escaped:
            await self.sessions.clear_pending_clarification(session)
            self.turns.pop(turn_id, None)
            return None

        if turn_id not in self.turns:
            raise ApiError(ErrorCode.clarification_not_found, status_code=404)

        if selection not in state.options:
            raise ApiError(ErrorCode.clarification_not_found, status_code=404)

        await self.sessions.add_resolved_entity(
            session,
            state.ambiguous_term or "unknown_term",
            selection.lower().replace(" ", "_"),
            selection,
        )
        await self.sessions.clear_pending_clarification(session)
        turn = self.turns[turn_id]
        turn.user_input = f"{state.original_query} ({selection})"
        self._in_flight.add(session.session_id)
        clarification = AuditClarification(
            turn_id=turn_id,
            prompt_sent=state.question,
            user_choice=selection,
            resolution_type=resolution_type
        )
        self._schedule_pipeline_task(
            self._run_turn_background(
                session,
                turn,
                claims,
                clarification_triggered=True,
                clarification=clarification
            ),
            session.session_id,
        )
        return turn



    def get_turn_for_user(self, turn_id: UUID, claims: AuthClaims) -> TurnRecord:
        turn = self.turns.get(turn_id)
        if turn is None:
            raise ApiError(ErrorCode.turn_not_found, status_code=404)
        if turn.user_id != claims.user_id or turn.tenant_id != claims.tenant_id:
            raise ApiError(ErrorCode.turn_forbidden, status_code=403)
        return turn

    def _schedule_pipeline_task(self, coroutine, session_id: UUID) -> None:
        task = asyncio.create_task(coroutine, name=f"pipeline-{session_id}")
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _run_turn_background(self, session, turn: TurnRecord, claims: AuthClaims, *, clarification_triggered: bool = False, clarification: AuditClarification | None = None) -> None:
        await asyncio.sleep(0.05)
        with tracer.start_trace(turn) as trace:
            try:
                await self._run_until_confidence_or_result(session, turn, claims, trace, clarification_triggered=clarification_triggered, clarification=clarification)
            except ApiError as exc:
                tracer.span_turn_completed(trace, turn.latency_ms, success=False, error_code=exc.code.value)
                await self.events.publish(
                    session.session_id,
                    PipelineErrorEvent(
                        turn_id=turn.turn_id,
                        code=exc.code.value,
                        message=ERROR_MESSAGES.get(exc.code, exc.code.value),
                    ),
                )
                logger.warning(
                    "Background pipeline turn ended with ApiError: turn_id=%s session_id=%s tenant_id=%s code=%s detail=%s",
                    turn.turn_id,
                    session.session_id,
                    session.tenant_id,
                    exc.code.value,
                    exc.detail,
                )
            except Exception as exc:
                tracer.span_turn_completed(trace, turn.latency_ms, success=False)
                await self.events.publish(
                    session.session_id,
                    PipelineErrorEvent(
                        turn_id=turn.turn_id,
                        code=ErrorCode.internal_error.value,
                        message=ERROR_MESSAGES[ErrorCode.internal_error],
                    ),
                )
                logger.exception(
                    "Background pipeline turn failed: turn_id=%s session_id=%s tenant_id=%s error=%s",
                    turn.turn_id,
                    session.session_id,
                    session.tenant_id,
                    str(exc)
                )
                raise exc
            finally:
                self._in_flight.discard(session.session_id)

    async def _run_until_confidence_or_result(self, session, turn: TurnRecord, claims: AuthClaims, trace: Any = None, clarification_triggered: bool = False, clarification: AuditClarification | None = None) -> None:
        """
        Execute the full analytical pipeline for one turn via the LangGraph graph.

        This method now delegates all orchestration logic to app.services.graph,
        which implements the same checkpoints (RAG → SQL-gen → retry → ambiguity →
        clarification or execution → render) as explicit graph nodes and conditional
        edges, rather than an imperative asyncio sequence.
        """
        from app.services.graph import run_pipeline_graph
        from app.audit.store import AuditIdentity

        tracer.span_stt_capture(trace, turn.raw_transcript, turn.user_input, turn.deepgram_confidence_raw)
        started = perf_counter()

        identity = AuditIdentity(
            tenant_id=claims.tenant_id,
            tenant_name="Default Tenant",
            user_id=claims.user_id,
            email=claims.email,
            role=claims.role,
            snowflake_role=claims.snowflake_role,
            conversation_id=session.conversation_id,
            conversation_title="Voice Session",
        )

        await run_pipeline_graph(
            session=session,
            turn=turn,
            claims=claims,
            settings=self.settings,
            schema_retriever=self.schema,
            llm=self.llm,
            warehouse=self.warehouse,
            chart=self.chart,
            story=self.story,
            sessions=self.sessions,
            events=self.events,
            audit=self.audit,
            tracer=tracer,
            trace=trace,
            clarification_triggered=clarification_triggered,
            clarification=clarification,
            audit_identity=identity,
            orchestrator=self,
            db_pool=self.db_pool,
            started=started,
        )


    async def _get_cached_result(self, tenant_id: UUID, sql: str) -> tuple[ResultPayload, ResultShape] | None:
        if self.settings.result_cache_ttl_seconds <= 0:
            return None
        client = getattr(self.sessions, "client", None)
        if client is None:
            return None
        try:
            raw = await client.get(self._cache_key(tenant_id, sql))
        except Exception:
            return None
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            payload = json.loads(raw)
            return (
                ResultPayload.model_validate(payload["result"]),
                ResultShape.model_validate(payload["shape"]),
            )
        except Exception:
            return None

    async def _store_cached_result(
        self,
        tenant_id: UUID,
        sql: str,
        result: ResultPayload,
        shape: ResultShape,
    ) -> None:
        if self.settings.result_cache_ttl_seconds <= 0:
            return
        client = getattr(self.sessions, "client", None)
        if client is None:
            return
        payload = json.dumps(
            {
                "result": result.model_dump(mode="json"),
                "shape": shape.model_dump(mode="json"),
            }
        )
        try:
            await client.setex(self._cache_key(tenant_id, sql), self.settings.result_cache_ttl_seconds, payload)
        except Exception:
            return

    @staticmethod
    def _cache_key(tenant_id: UUID, sql: str) -> str:
        sql_hash = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        return f"query_cache:{tenant_id}:{sql_hash}"

    async def _publish_stage(
        self, session_id: UUID, turn_id: UUID, stage: PipelineStage, started: float
    ) -> None:
        await self.events.publish(
            session_id,
            PipelineProgressEvent(
                stage=stage,
                turn_id=turn_id,
                elapsed_ms=int((perf_counter() - started) * 1000),
            ),
        )


def detect_possible_duplication(sql: str, result: ResultPayload) -> ResultWarning | None:
    lowered = sql.lower()
    if result.row_count < 100:
        return None
    if " join " not in lowered or "distinct" in lowered:
        return None
    return ResultWarning(
        code="possible_duplication",
        message="The join returned many rows; duplicate source records may be inflating this result.",
        suggested_sql=_suggest_distinct_sql(sql),
    )


def _suggest_distinct_sql(sql: str) -> str:
    stripped = sql.lstrip()
    leading = sql[: len(sql) - len(stripped)]
    if stripped[:6].lower() == "select":
        return f"{leading}SELECT DISTINCT{stripped[6:]}"
    return sql
