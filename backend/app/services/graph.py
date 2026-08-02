"""
app/services/graph.py
─────────────────────
LangGraph orchestration for the VoxQuery analytical pipeline.

Design goals (Wave 2, Item 1.1):
  • Each checkpoint is an inspectable async node.
  • Retry logic (SQL policy failure → re-generate → re-validate) is an
    explicit conditional edge, not an if-statement buried in a long function.
  • Clarification branch is a conditional edge that exits early without
    reaching Snowflake execution.
  • All Langfuse span calls happen inside nodes at the same points as the
    previous asyncio implementation — observability is preserved.
  • Public API surface of PipelineOrchestrator is unchanged; this graph is
    an internal implementation detail of _run_until_confidence_or_result.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, TYPE_CHECKING

from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from app.core.ambiguity import detect_ambiguity
from app.core.confidence import compute_confidence
from app.core.input_resolver import resolve_input
from app.models.contracts import (
    AnalyticalAttempt,
    ApiError,
    AmbiguityDetectionResult,
    AuthClaims,
    ClarificationRequestEvent,
    ClarificationState,
    ConfidenceEvidence,
    ConfidenceInput,
    ConfidenceResult,
    ErrorCode,
    PipelineStage,
    PipelineProgressEvent,
    ResultPayload,
    ResultShape,
    TurnRecord,
    valid_visualizations_for_result,
)
from app.warehouse.sql_policy import SqlPolicyError, canonicalize_readonly_sql


if TYPE_CHECKING:
    from app.audit.store import AuditIdentity
    from app.llm.adapter import SqlGenerationResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------

class PipelineGraphState(TypedDict, total=False):
    """Typed state container threaded through all graph nodes."""

    # ── set before the graph runs ──────────────────────────────────────────
    session: Any                    # VoiceSession
    turn: Any                       # TurnRecord
    claims: AuthClaims
    settings: Any                   # Settings
    schema_retriever: Any           # SchemaRetriever
    llm: Any                        # LlmAdapter
    warehouse: Any                  # WarehouseConnector
    chart: Any                      # FakeChartSelector
    story: Any                      # Storyteller
    sessions: Any                   # InMemorySessionStore
    events: Any                     # PipelineEventBus
    audit: Any                      # AuditStore
    tracer: Any                     # LangfuseTracer
    clarification_triggered: bool   # was this turn resumed from clarification?
    clarification: Any              # AuditClarification | None
    started: float                  # perf_counter() reference for elapsed_ms
    graph_trace: Any                # Langfuse trace object (None in test mode)
    audit_identity: Any             # AuditIdentity (built in pipeline.py before graph runs)
    orchestrator_ref: Any           # PipelineOrchestrator backref for cache access
    db_pool: Any                    # Database connection pool

    # ── populated by nodes ─────────────────────────────────────────────────
    schema_chunks: list             # list[SchemaChunk]
    rag_score: float
    rewritten_query: Any            # RewrittenQuery
    history: list                   # list[SessionHistoryTurn]
    generation: Any                 # SqlGenerationResult
    attempt_idx: int                # 0-based; max 1 (two total attempts)
    feedback: str | None
    previous_sql: str | None
    ambiguity: Any                  # AmbiguityDetectionResult
    pre_sql_ambiguity: Any          # AmbiguityDetectionResult | None
    confidence: Any                 # ConfidenceResult
    cached_result: Any              # tuple[ResultPayload, ResultShape] | None
    result: Any                     # ResultPayload
    shape: Any                      # ResultShape
    clarification_issued: bool      # True when a clarification event was emitted
    error: Any                      # ApiError | None – set on irrecoverable failure


# ---------------------------------------------------------------------------
# Helper — publish a progress event from inside a node
# ---------------------------------------------------------------------------

async def _publish_stage(state: PipelineGraphState, stage: PipelineStage) -> None:
    elapsed = int((perf_counter() - state["started"]) * 1000)
    await state["events"].publish(
        state["session"].session_id,
        PipelineProgressEvent(
            stage=stage,
            turn_id=state["turn"].turn_id,
            elapsed_ms=elapsed,
        ),
    )


# ---------------------------------------------------------------------------
# Node: input_resolver
# ---------------------------------------------------------------------------

async def input_resolver_node(state: PipelineGraphState) -> dict:
    turn: TurnRecord = state["turn"]
    context = await state["sessions"].context_block(state["session"])
    history = context.history
    
    # Run with empty schema to detect text-only blocking signals (pronouns, scope)
    resolution = resolve_input(
        text=turn.user_input,
        schema_chunks=[],
        session_history=history,
        resolved_entities=state["session"].resolved_entities,
    )
    return {
        "pre_sql_ambiguity": resolution.pre_sql_ambiguity,
        "ambiguity": resolution.pre_sql_ambiguity if resolution.should_block else state.get("ambiguity"),
        "history": history,
    }

# ---------------------------------------------------------------------------
# Node: rewrite_query
# ---------------------------------------------------------------------------

async def rewrite_query_node(state: PipelineGraphState) -> dict:
    from app.rag.query_rewriter import QueryRewriter
    turn = state["turn"]
    
    metric_synonyms = None
    table_synonyms = None
    
    db_pool = state.get("db_pool")
    if db_pool:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT metric_synonyms, table_synonyms FROM tenant_glossary WHERE tenant_id = $1",
                turn.tenant_id
            )
            if row:
                metric_synonyms = json.loads(row["metric_synonyms"]) if isinstance(row["metric_synonyms"], str) else row["metric_synonyms"]
                table_synonyms = json.loads(row["table_synonyms"]) if isinstance(row["table_synonyms"], str) else row["table_synonyms"]
                
    rewriter = QueryRewriter(metric_synonyms=metric_synonyms, table_synonyms=table_synonyms)
    rewritten = rewriter.rewrite(turn.user_input)
    
    if db_pool and (metric_synonyms or table_synonyms) and rewritten.detected_metrics:
        async with db_pool.acquire() as conn:
            for metric in rewritten.detected_metrics:
                await conn.execute("""
                    UPDATE tenant_glossary 
                    SET synonym_hits = jsonb_set(
                        synonym_hits,
                        ARRAY[$1],
                        (COALESCE(synonym_hits->$1, '0')::int + 1)::text::jsonb
                    ),
                    total_hits = total_hits + 1
                    WHERE tenant_id = $2
                """, metric, turn.tenant_id)
                
    return {"rewritten_query": rewritten}


# ---------------------------------------------------------------------------
# Node: rag_retrieval
# ---------------------------------------------------------------------------

async def rag_retrieval_node(state: PipelineGraphState) -> dict:
    turn: TurnRecord = state["turn"]
    claims: AuthClaims = state["claims"]
    tracer = state["tracer"]
    trace = state.get("graph_trace")

    await _publish_stage(state, PipelineStage.rag_retrieval)

    try:
        schema_chunks, rag_score = await state["schema_retriever"].retrieve(
            state["rewritten_query"], tenant_id=claims.tenant_id
        )
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(ErrorCode.rag_unavailable, status_code=503, detail=str(exc)) from exc

    tracer.span_rag_retrieval(trace, rag_score, len(schema_chunks))

    context = await state["sessions"].context_block(state["session"])
    tracer.span_memory_retrieval(
        trace,
        truncated=context.truncated,
        turns_dropped=context.turns_dropped,
        token_count=context.token_count,
    )

    return {
        "schema_chunks": schema_chunks,
        "rag_score": rag_score,
        "history": context.history,
        "attempt_idx": 0,
        "feedback": None,
        "previous_sql": None,
    }


# ---------------------------------------------------------------------------
# Node: sql_generation
# ---------------------------------------------------------------------------

async def sql_generation_node(state: PipelineGraphState) -> dict:
    turn: TurnRecord = state["turn"]
    tracer = state["tracer"]
    trace = state.get("graph_trace")
    attempt_idx: int = state.get("attempt_idx", 0)

    if attempt_idx == 0:
        await _publish_stage(state, PipelineStage.sql_generation)

    generation: SqlGenerationResult = await state["llm"].generate_sql(
        turn.user_input,
        state["schema_chunks"],
        state["history"],
        resolved_entities=state["session"].resolved_entities,
        feedback=state.get("feedback"),
        previous_sql=state.get("previous_sql"),
    )

    # Apply SQL policy (Cartesian join, read-only enforcement) immediately
    if generation.validation_passed:
        try:
            canonical = canonicalize_readonly_sql(generation.sql)
            generation.sql = canonical.sql
        except SqlPolicyError as exc:
            generation.validation_passed = False
            generation.validation_error = str(exc)

    sql_hash = hashlib.sha256(generation.sql.encode()).hexdigest()
    attempt_evidence = AnalyticalAttempt(
        turn_id=turn.turn_id,
        attempt_number=attempt_idx + 1,
        generated_sql=generation.sql,
        validation_passed=generation.validation_passed,
        validation_error=generation.validation_error,
        sql_hash=sql_hash,
    )
    turn.attempts.append(attempt_evidence)
    tracer.span_history_injection(trace, total_prompt_tokens=150)

    return {
        "generation": generation,
        "attempt_idx": attempt_idx + 1,
        "feedback": generation.validation_error if not generation.validation_passed else None,
        "previous_sql": generation.sql if not generation.validation_passed else None,
    }


# ---------------------------------------------------------------------------
# Node: ambiguity_check
# ---------------------------------------------------------------------------

async def ambiguity_check_node(state: PipelineGraphState) -> dict:
    turn: TurnRecord = state["turn"]
    tracer = state["tracer"]
    trace = state.get("graph_trace")

    await _publish_stage(state, PipelineStage.sql_validation)

    generation = state["generation"]
    if not generation.validation_passed:
        # Both attempts exhausted — abort
        raise ApiError(ErrorCode.sql_generation_failed, status_code=400)

    ambiguity: AmbiguityDetectionResult = detect_ambiguity(
        turn.user_input,
        state["schema_chunks"],
        resolved_entities=state["session"].resolved_entities,
        history=state["session"].history,
    )
    tracer.span_ambiguity_detection(
        trace,
        ambiguity.signals_detected,
        ambiguity.signals_suppressed,
        ambiguity.dominant_signal,
    )

    rag_score: float = state["rag_score"]
    clarification_triggered: bool = state.get("clarification_triggered", False)

    confidence: ConfidenceResult = compute_confidence(
        rag_score,
        generation.validation_passed,
        generation.llm_self_confidence,
        ambiguity.signals_detected,
        threshold=(
            state["settings"].confidence_threshold_post_clarification
            if clarification_triggered
            else state["settings"].confidence_threshold_primary
        ),
        settings=state["settings"],
    )
    tracer.span_confidence_computation(
        trace,
        confidence.composite_score,
        confidence.confidence_tier,
        confidence.clarification_triggered,
        confidence.formula_weights,
    )

    # Populate confidence evidence on the last attempt record
    final_attempt = turn.attempts[-1]
    final_attempt.confidence_inputs = ConfidenceInput(
        rag_score=rag_score,
        validation_passed=generation.validation_passed,
        llm_self_confidence=generation.llm_self_confidence,
        ambiguity_signals=ambiguity.signals_detected,
        threshold=(
            state["settings"].confidence_threshold_post_clarification
            if clarification_triggered
            else state["settings"].confidence_threshold_primary
        ),
    )
    final_attempt.confidence_result = confidence
    inputs_present = ["rag_score", "validation_passed", "ambiguity_signals"]
    inputs_absent: list[str] = []
    if generation.llm_self_confidence is not None:
        inputs_present.append("llm_self_confidence")
    else:
        inputs_absent.append("llm_self_confidence")
    final_attempt.confidence_evidence = ConfidenceEvidence(
        attempt_id=final_attempt.attempt_id,
        sql_hash=final_attempt.sql_hash,
        retrieval_score=rag_score,
        validation_outcome=generation.validation_passed,
        ambiguity_signals=ambiguity.signals_detected,
        retry_count=len(turn.attempts) - 1,
        inputs_present=inputs_present,
        inputs_absent=inputs_absent,
        final_score=confidence.composite_score,
        final_tier=confidence.confidence_tier,
    )

    turn.generated_sql = generation.sql
    turn.confidence_tier = confidence.confidence_tier
    turn.composite_score = confidence.composite_score
    turn.latency_ms = int((perf_counter() - state["started"]) * 1000)

    return {"ambiguity": ambiguity, "confidence": confidence}


# ---------------------------------------------------------------------------
# Node: clarification
# ---------------------------------------------------------------------------

async def clarification_node(state: PipelineGraphState) -> dict:
    turn: TurnRecord = state["turn"]
    ambiguity: AmbiguityDetectionResult | None = state.get("ambiguity") or state.get("pre_sql_ambiguity")
    tracer = state["tracer"]
    trace = state.get("graph_trace")

    if not ambiguity:
        raise ValueError("Ambiguity is None in clarification_node! This should never happen.")

    question, options = await state["llm"].generate_clarification(
        ambiguity.dominant_signal, user_input=turn.user_input
    )

    if len(options) < 2:
        # LLM returned unusable options — fall through to execution
        return {"clarification_issued": False}

    turn.clarification_triggered = True
    tracer.span_clarification_issued(trace, question, options)

    await state["sessions"].set_pending_clarification(
        state["session"],
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
            ambiguous_term=(
                ambiguity.ambiguous_terms[0] if ambiguity.ambiguous_terms else None
            ),
        ),
    )
    await state["events"].publish(
        state["session"].session_id,
        ClarificationRequestEvent(
            turn_id=turn.turn_id,
            question=question,
            options=options,
        ),
    )
    tracer.span_turn_completed(trace, turn.latency_ms, success=True)
    return {"clarification_issued": True}


# ---------------------------------------------------------------------------
# Node: execution
# ---------------------------------------------------------------------------

async def execution_node(state: PipelineGraphState) -> dict:
    turn: TurnRecord = state["turn"]
    claims: AuthClaims = state["claims"]
    tracer = state["tracer"]
    trace = state.get("graph_trace")

    await _publish_stage(state, PipelineStage.snowflake_executing)
    started = perf_counter()

    sql_to_execute: str = turn.generated_sql
    execution_sql_hash = hashlib.sha256(sql_to_execute.encode()).hexdigest()
    final_attempt = turn.attempts[-1]

    if execution_sql_hash != final_attempt.sql_hash:
        # Deliberately not an `assert`: assertions are stripped when Python runs
        # with -O, which would silently disable this check in some production
        # deployments. This invariant (the SQL we execute against the warehouse
        # is exactly the SQL that was confidence-scored) is security-relevant
        # and must always be enforced.
        raise ApiError(
            ErrorCode.internal_error,
            status_code=500,
            detail="Execution SQL hash does not match confidence-assessed SQL hash.",
        )
    final_attempt.executed_sql_hash = execution_sql_hash

    # Cache read
    orchestrator = state.get("orchestrator_ref")
    cached = None
    if orchestrator is not None:
        cached = await orchestrator._get_cached_result(claims.tenant_id, sql_to_execute, claims.snowflake_role)

    if cached is not None:
        result, shape = cached
        turn.from_cache = True
    else:
        try:
            result, shape = await state["warehouse"].execute_readonly(
                sql_to_execute, snowflake_role=claims.snowflake_role, tenant_id=claims.tenant_id
            )
        except Exception as e:
            err_str = str(e).lower()
            tracer.span_snowflake_executing(
                trace,
                snowflake_role=claims.snowflake_role,
                success=False,
                error_type=type(e).__name__,
                error_detail=str(e),
            )
            if "time" in err_str and "out" in err_str:
                raise ApiError(ErrorCode.warehouse_timeout, status_code=504, detail=str(e))
            if "warehouse error" in err_str or "operationalerror" in err_str:
                raise ApiError(ErrorCode.warehouse_error, status_code=502, detail=str(e))
            raise ApiError(ErrorCode.warehouse_error, status_code=500, detail=str(e))

        tracer.span_snowflake_executing(
            trace,
            snowflake_role=claims.snowflake_role,
            success=True,
            row_count=shape.row_count,
        )

        if orchestrator is not None:
            await orchestrator._store_cached_result(
                claims.tenant_id, sql_to_execute, result, shape, claims.snowflake_role
            )

    turn.latency_ms += int((perf_counter() - started) * 1000)
    return {"result": result, "shape": shape}


# ---------------------------------------------------------------------------
# Node: render
# ---------------------------------------------------------------------------

async def render_node(state: PipelineGraphState) -> dict:
    from app.services.pipeline import detect_possible_duplication
    from app.models.contracts import ResultReadyEvent

    turn: TurnRecord = state["turn"]
    tracer = state["tracer"]
    trace = state.get("graph_trace")
    claims: AuthClaims = state["claims"]
    result: ResultPayload = state["result"]
    shape: ResultShape = state["shape"]

    await _publish_stage(state, PipelineStage.rendering)

    duplication_warning = detect_possible_duplication(turn.generated_sql, result)
    chart_type, rationale = state["chart"].select(result)
    shape.chart_type = chart_type
    summary, proactive_questions = await asyncio.gather(
        state["story"].summarize(shape, turn.user_input),
        state["story"].generate_proactive_questions(shape, turn.user_input)
    )

    turn.result_json = shape
    turn.chart_type = chart_type
    turn.chart_rationale = rationale
    turn.full_result = result
    turn.result_warnings = [duplication_warning] if duplication_warning else []
    turn.tts_text = summary
    turn.proactive_questions = proactive_questions
    turn.completed = True
    turn.clarification_triggered = (
        state.get("clarification_triggered", False) or turn.clarification_triggered
    )

    identity: AuditIdentity = state["audit_identity"]  # type: ignore[assignment]
    state["audit"].enqueue_turn(turn, identity, state.get("clarification"))

    # ── Durable executive memory: extract and upsert candidates ────────────
    # Runs only when a turn completes with a result. Extracts explainable
    # memory candidates (metrics, dimensions, time ranges) from turn metadata.
    # Never stores raw rows, SQL text, or user PII. Errors are silently skipped.
    if state.get("db_pool") and turn.completed:
        try:
            from app.repositories.memory_repository import MemoryRepository, extract_memory_candidates
            import re as _re
            _turn_meta: dict = {"source_tables": [], "filter_predicates": [], "metric_name": None}
            if turn.generated_sql:
                _tables = _re.findall(
                    r"(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_.]*)",
                    turn.generated_sql, flags=_re.IGNORECASE,
                )
                _turn_meta["source_tables"] = list(dict.fromkeys(t.lower() for t in _tables[:5]))
            if turn.full_result and turn.full_result.semantic_columns:
                for _col in turn.full_result.semantic_columns:
                    if _col.role == "metric" and _col.display_name:
                        _turn_meta["metric_name"] = _col.display_name
                        break
            _confidence = float(turn.composite_score or 0.8)
            _candidates = extract_memory_candidates(_turn_meta, turn.user_input, _confidence)
            if _candidates:
                _mem_repo = MemoryRepository(state["db_pool"])
                for _candidate in _candidates:
                    await _mem_repo.upsert_memory(
                        claims,
                        memory_type=_candidate["memory_type"],
                        subject=_candidate["subject"],
                        label=_candidate["label"],
                        source_turn_id=turn.turn_id,
                        source_session_id=turn.session_id,
                        confidence=_candidate["confidence"],
                    )
        except Exception as _mem_exc:
            logger.warning("render_node: memory upsert skipped: %s", _mem_exc)

    await state["sessions"].append_turn(
        state["session"],
        turn_id=turn.turn_id,
        user_query=turn.user_input,
        generated_sql=turn.generated_sql,
        result_shape=shape,
        confidence_tier=turn.confidence_tier,
        clarification_triggered=turn.clarification_triggered,
        input_modality=turn.input_modality,
    )

    await state["events"].publish(
        state["session"].session_id,
        ResultReadyEvent(
            turn_id=turn.turn_id,
            confidence_tier=turn.confidence_tier,
            chart_type=chart_type,
            chart_rationale=rationale,
            result_json={
                "columns": shape.columns,
                "row_count": shape.row_count,
                "aggregate_summary": shape.aggregate_summary,
                "semantic_columns": [
                    col.model_dump(mode="json") for col in result.semantic_columns
                ],
                "preview_row_count": result.preview_row_count,
                "is_truncated": result.is_truncated,
                "valid_visualizations": [
                    c.value for c in valid_visualizations_for_result(result)
                ],
                "warnings": [w.model_dump(mode="json") for w in turn.result_warnings],
            },
            proactive_questions=turn.proactive_questions,
            from_cache=turn.from_cache,
        ),
    )
    tracer.span_turn_completed(trace, turn.latency_ms, success=True)
    tracer.flush()
    return {}


# ---------------------------------------------------------------------------
# Routing edges
# ---------------------------------------------------------------------------

def _route_after_sql_generation(state: PipelineGraphState) -> str:
    """Retry once on validation failure; proceed to ambiguity after second attempt or pass."""
    generation = state.get("generation")
    attempt_idx: int = state.get("attempt_idx", 1)
    if generation is None or not generation.validation_passed:
        if attempt_idx < 2:
            return "sql_generation_node"
    return "ambiguity_check_node"


def _route_after_ambiguity(state: PipelineGraphState) -> str:
    """Branch to clarification if confidence demands it, otherwise execute."""
    confidence = state.get("confidence")
    clarification_triggered: bool = state.get("clarification_triggered", False)
    ambiguity = state.get("ambiguity")
    if (
        not clarification_triggered
        and confidence is not None
        and confidence.clarification_triggered
        and ambiguity is not None
        and ambiguity.dominant_signal is not None
    ):
        return "clarification_node"
    return "execution_node"


def _route_after_clarification(state: PipelineGraphState) -> str:
    """If clarification was successfully issued, end the turn. Otherwise fall through to execution."""
    if state.get("clarification_issued", False):
        return END
    return "execution_node"


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def build_pipeline_graph():
    """
    Compile the VoxQuery analytical pipeline as a LangGraph.

    Why LangGraph instead of the hand-written asyncio orchestrator:
      - Each checkpoint is an inspectable node — easier to unit-test and trace.
      - The retry-once rule is an explicit conditional edge (not a buried if-loop).
      - The clarification branch is another conditional edge, not a separate code path.
      - Langfuse can hook into per-node runs for fine-grained span coverage.
    """
    graph: StateGraph = StateGraph(PipelineGraphState)

    graph.add_node("input_resolver_node", input_resolver_node)
    graph.add_node("rewrite_query_node", rewrite_query_node)
    graph.add_node("rag_retrieval_node", rag_retrieval_node)
    graph.add_node("sql_generation_node", sql_generation_node)
    graph.add_node("ambiguity_check_node", ambiguity_check_node)
    graph.add_node("clarification_node", clarification_node)
    graph.add_node("execution_node", execution_node)
    graph.add_node("render_node", render_node)

    def _route_after_input_resolver(state: PipelineGraphState) -> str:
        # If we are resuming after a user answer, do not block again.
        if state.get("clarification_triggered"):
            return "rewrite_query_node"
            
        if state.get("pre_sql_ambiguity") is not None:
            return "clarification_node"
        return "rewrite_query_node"

    graph.set_entry_point("input_resolver_node")
    graph.add_conditional_edges(
        "input_resolver_node",
        _route_after_input_resolver,
        {
            "clarification_node": "clarification_node",
            "rewrite_query_node": "rewrite_query_node",
        },
    )

    graph.add_edge("rewrite_query_node", "rag_retrieval_node")
    graph.add_edge("rag_retrieval_node", "sql_generation_node")

    graph.add_conditional_edges(
        "sql_generation_node",
        _route_after_sql_generation,
        {
            "sql_generation_node": "sql_generation_node",
            "ambiguity_check_node": "ambiguity_check_node",
        },
    )

    graph.add_conditional_edges(
        "ambiguity_check_node",
        _route_after_ambiguity,
        {
            "clarification_node": "clarification_node",
            "execution_node": "execution_node",
        },
    )

    graph.add_conditional_edges(
        "clarification_node",
        _route_after_clarification,
        {
            END: END,
            "execution_node": "execution_node",
        },
    )

    graph.add_edge("execution_node", "render_node")
    graph.add_edge("render_node", END)

    return graph.compile()


# Singleton compiled graph — compiled once at import time
_compiled_pipeline: Any = None


def get_compiled_pipeline():
    global _compiled_pipeline
    if _compiled_pipeline is None:
        _compiled_pipeline = build_pipeline_graph()
    return _compiled_pipeline


async def run_pipeline_graph(
    *,
    session: Any,
    turn: TurnRecord,
    claims: AuthClaims,
    settings: Any,
    schema_retriever: Any,
    llm: Any,
    warehouse: Any,
    chart: Any,
    story: Any,
    sessions: Any,
    events: Any,
    audit: Any,
    tracer: Any,
    trace: Any,
    clarification_triggered: bool,
    clarification: Any,
    audit_identity: Any,
    orchestrator: Any,
    db_pool: Any,
    started: float,
) -> None:
    """
    Execute the pipeline graph for one turn and return when done.
    Raises ApiError on any failure — callers are responsible for handling
    and emitting PipelineErrorEvent (same contract as before).
    """
    pipeline = get_compiled_pipeline()
    initial_state: PipelineGraphState = {
        "session": session,
        "turn": turn,
        "claims": claims,
        "settings": settings,
        "schema_retriever": schema_retriever,
        "llm": llm,
        "warehouse": warehouse,
        "chart": chart,
        "story": story,
        "sessions": sessions,
        "events": events,
        "audit": audit,
        "tracer": tracer,
        "graph_trace": trace,
        "clarification_triggered": clarification_triggered,
        "clarification": clarification,
        "audit_identity": audit_identity,
        "orchestrator_ref": orchestrator,
        "db_pool": db_pool,
        "started": started,
        "clarification_issued": False,
    }
    await pipeline.ainvoke(initial_state)
