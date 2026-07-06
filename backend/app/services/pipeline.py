from __future__ import annotations
from typing import Any
import asyncio
import threading
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID

from app.audit.store import AuditStore, AuditIdentity, AuditClarification
from app.config import Settings, get_settings
from app.core.ambiguity import detect_ambiguity
from app.core.confidence import compute_confidence
from app.core.session import InMemorySessionStore
from app.models.contracts import (
    ApiError,
    AuthClaims,
    ClarificationRequestEvent,
    ClarificationResolutionType,
    ClarificationState,
    ClarificationTimeoutWarningEvent,
    ErrorCode,
    ERROR_MESSAGES,
    PipelineProgressEvent,
    PipelineStage,
    PipelineErrorEvent,
    QueryRequest,
    ResultReadyEvent,
    TurnRecord,
)
from app.services.events import PipelineEventBus
from app.rag.retriever import SchemaRetriever
from app.llm.adapter import LlmAdapter
from app.warehouse.connector import WarehouseConnector
from app.services.providers import (
    FakeChartSelector,
    FakeSchemaRetriever,
    FakeSqlGenerator,
    FakeStoryteller,
    FakeWarehouseConnector,
    clarification_options_for_signal,
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
    ) -> None:
        self.sessions = sessions
        self.events = events
        self.audit = audit
        self.settings = settings or get_settings()
        self.schema = schema or FakeSchemaRetriever()
        self.llm = llm or FakeSqlGenerator()
        self.warehouse = warehouse or FakeWarehouseConnector()
        self.chart = FakeChartSelector()
        self.story = FakeStoryteller()
        self.turns: dict[UUID, TurnRecord] = {}
        self._in_flight: set[UUID] = set()

    async def submit_query(self, request: QueryRequest, claims: AuthClaims) -> TurnRecord:
        session = self.sessions.get_for_claims(claims, request.session_id)
        if session is None:
            raise ApiError(ErrorCode.session_not_found, status_code=404)
        await self.expire_pending_clarification_if_needed(session.session_id, claims)
        if request.session_id in self._in_flight:
            raise ApiError(ErrorCode.pipeline_in_flight, status_code=409)

        turn = TurnRecord(
            session_id=session.session_id,
            conversation_id=session.conversation_id,
            user_id=claims.user_id,
            tenant_id=claims.tenant_id,
            user_input=request.submitted_text,
            raw_transcript=request.raw_transcript,
            deepgram_confidence_raw=request.stt_confidence,
            input_modality=request.input_modality,
        )
        self.turns[turn.turn_id] = turn

        self._in_flight.add(request.session_id)
        self._schedule_pipeline_task(self._run_turn_background(session, turn, claims), session.session_id)
        return turn

    async def resolve_clarification(
        self,
        *,
        session_id: UUID,
        turn_id: UUID,
        selection: str | None,
        resolution_type: ClarificationResolutionType,
        claims: AuthClaims,
    ) -> TurnRecord | None:
        session = self.sessions.get_for_claims(claims, session_id)
        if session is None:
            raise ApiError(ErrorCode.session_not_found, status_code=404)
        state = session.clarification_state
        if state is None or state.turn_id != turn_id:
            raise ApiError(ErrorCode.clarification_not_found, status_code=404)

        if resolution_type == ClarificationResolutionType.escaped:
            self.sessions.clear_pending_clarification(session)
            self.turns.pop(turn_id, None)
            return None

        if turn_id not in self.turns:
            raise ApiError(ErrorCode.clarification_not_found, status_code=404)

        if selection not in state.options:
            raise ApiError(ErrorCode.clarification_not_found, status_code=404)

        self.sessions.add_resolved_entity(
            session,
            "revenue",
            selection.lower().replace(" ", "_"),
            selection,
        )
        self.sessions.clear_pending_clarification(session)
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
            self._complete_turn_background(
                session,
                turn,
                claims,
                resolved_metric=selection,
                clarification_triggered=True,
                clarification=clarification
            ),
            session.session_id,
        )
        return turn

    async def force_timeout(self, session_id: UUID, claims: AuthClaims) -> TurnRecord:
        session = self.sessions.get_for_claims(claims, session_id)
        if session is None or session.clarification_state is None:
            raise ApiError(ErrorCode.clarification_not_found, status_code=404)
        return await self._complete_pending_timeout(session, claims)

    async def expire_pending_clarification_if_needed(
        self, session_id: UUID, claims: AuthClaims
    ) -> TurnRecord | None:
        session = self.sessions.get_for_claims(claims, session_id)
        if session is None or session.clarification_state is None:
            return None
        elapsed = datetime.now(UTC) - session.clarification_state.issued_at
        if elapsed.total_seconds() < self.settings.clarification_timeout_seconds:
            return None
        return await self._complete_pending_timeout(session, claims)

    async def _complete_pending_timeout(self, session, claims: AuthClaims) -> TurnRecord:
        state = session.clarification_state
        if state.turn_id not in self.turns:
            self.sessions.clear_pending_clarification(session)
            raise ApiError(ErrorCode.clarification_not_found, status_code=404)
        self.sessions.clear_pending_clarification(session)
        turn = self.turns[state.turn_id]
        
        clarification = AuditClarification(
            turn_id=state.turn_id,
            prompt_sent=state.question,
            user_choice=None,
            resolution_type="timeout"
        )
        await self._complete_turn(session, turn, claims, None, clarification_triggered=True, clarification=clarification)
        return turn

    def get_turn_for_user(self, turn_id: UUID, claims: AuthClaims) -> TurnRecord:
        turn = self.turns.get(turn_id)
        if turn is None:
            raise ApiError(ErrorCode.turn_not_found, status_code=404)
        if turn.user_id != claims.user_id or turn.tenant_id != claims.tenant_id:
            raise ApiError(ErrorCode.turn_forbidden, status_code=403)
        return turn

    def _schedule_pipeline_task(self, coroutine, session_id: UUID) -> None:
        asyncio.create_task(coroutine, name=f"pipeline-{session_id}")

    async def _run_turn_background(self, session, turn: TurnRecord, claims: AuthClaims) -> None:
        await asyncio.sleep(0.05)
        with tracer.start_trace(turn) as trace:
            try:
                await self._run_until_confidence_or_result(session, turn, claims, trace)
            except Exception as exc:
                await self.events.publish(
                    session.session_id,
                    PipelineErrorEvent(
                        turn_id=turn.turn_id,
                        code=ErrorCode.internal_error.value,
                        message=ERROR_MESSAGES[ErrorCode.internal_error],
                    ),
                )
                raise exc
            finally:
                self._in_flight.discard(session.session_id)

    async def _complete_turn_background(
        self,
        session,
        turn: TurnRecord,
        claims: AuthClaims,
        *,
        resolved_metric: str | None = None,
        clarification_triggered: bool,
        clarification: AuditClarification | None = None
    ) -> None:
        await asyncio.sleep(0.05)
        with tracer.start_trace(turn) as trace:  # Create a trace if it didn't exist or re-use turn_id
            try:
                await self._complete_turn(
                    session,
                    turn,
                    claims,
                    trace,
                    resolved_metric=resolved_metric,
                    clarification_triggered=clarification_triggered,
                    clarification=clarification
                )
            except Exception as exc:
                await self.events.publish(
                    session.session_id,
                    PipelineErrorEvent(
                        turn_id=turn.turn_id,
                        code=ErrorCode.internal_error.value,
                        message=ERROR_MESSAGES[ErrorCode.internal_error],
                    ),
                )
                raise exc
            finally:
                self._in_flight.discard(session.session_id)

    async def _run_until_confidence_or_result(self, session, turn: TurnRecord, claims: AuthClaims, trace: Any = None) -> None:
        tracer.span_stt_capture(trace, turn.raw_transcript, turn.user_input, turn.deepgram_confidence_raw)

        started = perf_counter()
        await self._publish_stage(session.session_id, turn.turn_id, PipelineStage.rag_retrieval, started)
        schema_chunks, rag_score = await self.schema.retrieve(turn.user_input, tenant_id=claims.tenant_id)
        
        # We stub memory retrieval values for now, but use session info if available
        tracer.span_memory_retrieval(trace, truncated=False, turns_dropped=0, token_count=100)
        
        await self._publish_stage(session.session_id, turn.turn_id, PipelineStage.sql_generation, started)
        generation = await self.llm.generate_sql(turn.user_input)
        
        tracer.span_history_injection(trace, total_prompt_tokens=150)
        
        await self._publish_stage(session.session_id, turn.turn_id, PipelineStage.sql_validation, started)
        ambiguity = detect_ambiguity(
            turn.user_input,
            schema_chunks,
            resolved_entities=session.resolved_entities,
            history=session.history,
        )
        tracer.span_ambiguity_detection(trace, ambiguity.signals_detected, ambiguity.signals_suppressed, ambiguity.dominant_signal)

        confidence = compute_confidence(
            rag_score,
            generation.validation_passed,
            generation.llm_self_confidence,
            ambiguity.signals_detected,
            threshold=self.settings.confidence_threshold_primary,
            settings=self.settings,
        )
        tracer.span_confidence_computation(
            trace, 
            confidence.composite_score, 
            confidence.confidence_tier, 
            confidence.clarification_triggered, 
            confidence.formula_weights
        )

        turn.generated_sql = generation.sql
        turn.confidence_tier = confidence.confidence_tier
        turn.composite_score = confidence.composite_score
        turn.latency_ms = int((perf_counter() - started) * 1000)

        if confidence.clarification_triggered and ambiguity.dominant_signal is not None:
            question, options = await self.llm.generate_clarification(ambiguity.dominant_signal)
            if len(options) >= 2:
                turn.clarification_triggered = True
                self.sessions.set_pending_clarification(
                    session,
                    ClarificationState(
                        pending=True,
                        issued_at=datetime.now(UTC),
                        turn_id=turn.turn_id,
                        original_query=turn.user_input,
                        question=question,
                        options=options,
                        raw_transcript=turn.raw_transcript,
                        stt_confidence=turn.deepgram_confidence_raw,
                        input_modality=turn.input_modality,
                    ),
                )
                await self.events.publish(
                    session.session_id,
                    ClarificationRequestEvent(
                        turn_id=turn.turn_id,
                        question=question,
                        options=options,
                        timeout_seconds=self.settings.clarification_timeout_seconds,
                    ),
                )
                self._schedule_pipeline_task(
                    self._run_clarification_timer(session, turn.turn_id, claims),
                    session.session_id,
                )
                return

        await self._complete_turn(session, turn, claims, trace, clarification_triggered=False)

    async def _complete_turn(
        self,
        session,
        turn: TurnRecord,
        claims: AuthClaims,
        trace: Any = None,
        *,
        resolved_metric: str | None = None,
        clarification_triggered: bool,
        clarification: AuditClarification | None = None
    ) -> None:
        started = perf_counter()
        await self._publish_stage(session.session_id, turn.turn_id, PipelineStage.snowflake_executing, started)
        generation = await self.llm.generate_sql(turn.user_input, resolved_metric=resolved_metric)
        result, shape = await self.warehouse.execute_readonly(generation.sql, snowflake_role=claims.snowflake_role)
        chart_type, rationale = self.chart.select(result)
        shape.chart_type = chart_type
        summary = await self.story.summarize(shape, turn.user_input)

        confidence = compute_confidence(
            0.88,
            generation.validation_passed,
            generation.llm_self_confidence,
            [],
            threshold=(
                self.settings.confidence_threshold_post_clarification
                if clarification_triggered
                else self.settings.confidence_threshold_primary
            ),
            settings=self.settings,
        )
        await self._publish_stage(session.session_id, turn.turn_id, PipelineStage.rendering, started)

        turn.generated_sql = generation.sql
        turn.result_json = shape
        turn.chart_type = chart_type
        turn.chart_rationale = rationale
        turn.confidence_tier = confidence.confidence_tier
        turn.composite_score = confidence.composite_score
        turn.full_result = result
        turn.tts_text = summary
        turn.completed = True
        turn.latency_ms += int((perf_counter() - started) * 1000)
        turn.clarification_triggered = clarification_triggered or turn.clarification_triggered

        identity = AuditIdentity(
            tenant_id=claims.tenant_id,
            tenant_name="Default Tenant",
            user_id=claims.user_id,
            email=claims.email,
            role=claims.role,
            snowflake_role=claims.snowflake_role,
            conversation_id=session.conversation_id,
            conversation_title="Voice Session"
        )
        self.audit.enqueue_turn(turn, identity, clarification)

        self.sessions.append_turn(
            session,
            turn_id=turn.turn_id,
            user_query=turn.user_input,
            generated_sql=turn.generated_sql,
            result_shape=shape,
            confidence_tier=turn.confidence_tier,
            clarification_triggered=turn.clarification_triggered,
            input_modality=turn.input_modality,
        )
        await self.events.publish(
            session.session_id,
            ResultReadyEvent(
                turn_id=turn.turn_id,
                confidence_tier=turn.confidence_tier,
                chart_type=chart_type,
                chart_rationale=rationale,
                result_json={
                    "columns": shape.columns,
                    "row_count": shape.row_count,
                    "aggregate_summary": shape.aggregate_summary,
                },
                proactive_questions=[
                    "Show that by quarter",
                    "Compare this with last month",
                    "Break it down by customer segment",
                ],
                from_cache=False,
            ),
        )
        tracer.flush()

    async def _run_clarification_timer(self, session, turn_id: UUID, claims: AuthClaims) -> None:
        timeout_seconds = self.settings.clarification_timeout_seconds
        warning_delay = max(0, timeout_seconds - 10)
        await asyncio.sleep(warning_delay)
        state = session.clarification_state
        if state is None or state.turn_id != turn_id:
            return
        await self.events.publish(
            session.session_id,
            ClarificationTimeoutWarningEvent(turn_id=turn_id, seconds_remaining=10),
        )
        await asyncio.sleep(min(10, timeout_seconds))
        state = session.clarification_state
        if state is None or state.turn_id != turn_id:
            return
        await self._complete_pending_timeout(session, claims)

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
