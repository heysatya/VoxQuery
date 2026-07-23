import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import uuid
from app.services.pipeline import PipelineOrchestrator
from app.core.session import InMemorySessionStore
from app.services.providers import FakeSqlGenerator
from app.services.events import PipelineEventBus
from app.audit.store import AuditStore
from app.models.contracts import (
    AuthClaims,
    QueryRequest,
    SchemaChunk,
    ResultPayload,
    ResultShape,
    ChartType,
    ApiError,
    ErrorCode,
    TurnRecord,
    QualityFlag,
    SessionHistoryTurn,
    ConfidenceTier,
    ResolvedEntity,
)
from app.llm.adapter import SqlGenerationResult

@pytest.fixture
def claims():
    return AuthClaims(user_id=str(uuid.uuid4()), tenant_id=str(uuid.uuid4()))

@pytest.fixture
def req(claims):
    return QueryRequest(session_id=uuid.uuid4(), submitted_text="test query")

@pytest.mark.asyncio
async def test_exactly_one_correction_retry(claims, req):
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)
    
    pipeline = PipelineOrchestrator(sessions, events, audit)
    session, _ = await sessions.create(claims)
    req.session_id = session.session_id
    
    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=([SchemaChunk(content="c", source_ref="r", similarity=1.0)], 1.0))
    
    pipeline.llm = MagicMock()
    
    # First attempt fails, second succeeds
    fail_gen = SqlGenerationResult(sql="BAD", llm_self_confidence=0.5, validation_passed=False, validation_error="Syntax error")
    succ_gen = SqlGenerationResult(sql="SELECT good", llm_self_confidence=0.9, validation_passed=True)
    
    pipeline.llm.generate_sql = AsyncMock(side_effect=[fail_gen, succ_gen])
    
    pipeline.warehouse = MagicMock()
    pipeline.warehouse.execute_readonly = AsyncMock(return_value=(
        ResultPayload(columns=["a"], rows=[[1]], row_count=1),
        ResultShape(columns=["a"], chart_type=ChartType.stat, row_count=1, aggregate_summary="1")
    ))
    
    turn = await pipeline.submit_query(req, claims)
    import asyncio
    for _ in range(20):
        if turn.completed:
            break
        await asyncio.sleep(0.1)
    
    assert pipeline.llm.generate_sql.call_count == 2
    assert turn.generated_sql == "SELECT good LIMIT 10000"
    assert turn.completed is True

@pytest.mark.asyncio
async def test_fails_after_two_failed_attempts(claims, req):
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)
    
    pipeline = PipelineOrchestrator(sessions, events, audit)
    session, _ = await sessions.create(claims)
    req.session_id = session.session_id
    
    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=([SchemaChunk(content="c", source_ref="r", similarity=1.0)], 1.0))
    
    pipeline.llm = MagicMock()
    
    fail_gen = SqlGenerationResult(sql="BAD", llm_self_confidence=0.5, validation_passed=False, validation_error="Syntax error")
    pipeline.llm.generate_sql = AsyncMock(side_effect=[fail_gen, fail_gen])
    
    pipeline.warehouse = MagicMock()
    
    # Construct a TurnRecord properly
    turn = TurnRecord(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        user_input=req.submitted_text,
        raw_transcript=req.raw_transcript,
        deepgram_confidence_raw=req.stt_confidence,
        input_modality=req.input_modality,
    )
    
    with pytest.raises(ApiError) as exc_info:
        await pipeline._run_until_confidence_or_result(session, turn, claims)
    assert exc_info.value.code == ErrorCode.sql_generation_failed
    
    # Let's verify by checking the error event during background run
    events.publish = AsyncMock()
    # Replace orchestrator's events with mock
    pipeline.events = events
    pipeline.llm.generate_sql = AsyncMock(side_effect=[fail_gen, fail_gen])
    
    # Submit query to run background flow
    turn = await pipeline.submit_query(req, claims)
    import asyncio
    await asyncio.sleep(0.5)
    
    assert pipeline.llm.generate_sql.call_count == 2
    
    # Assert Error emitted
    events.publish.assert_called()
    published_events = events.publish.call_args_list
    assert any(
        args[0][1].type == "pipeline_error" and args[0][1].code == ErrorCode.sql_generation_failed.value
        for args in published_events
    )
    assert turn.completed is False


@pytest.mark.asyncio
async def test_schema_retrieval_failure_is_structured(claims, req):
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)

    pipeline = PipelineOrchestrator(sessions, events, audit)
    session, _ = await sessions.create(claims)
    req.session_id = session.session_id

    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(side_effect=RuntimeError("embedding service down"))

    turn = TurnRecord(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        user_input=req.submitted_text,
        input_modality=req.input_modality,
    )

    with pytest.raises(ApiError) as exc_info:
        await pipeline._run_until_confidence_or_result(session, turn, claims)

    assert exc_info.value.code == ErrorCode.rag_unavailable

@pytest.mark.asyncio
async def test_approved_sql_is_executed_sql(claims, req):
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)
    
    pipeline = PipelineOrchestrator(sessions, events, audit)
    session, _ = await sessions.create(claims)
    req.session_id = session.session_id
    
    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=([SchemaChunk(content="c", source_ref="r", similarity=1.0)], 1.0))
    
    pipeline.llm = MagicMock()
    succ_gen = SqlGenerationResult(sql="SELECT * FROM test", llm_self_confidence=0.9, validation_passed=True)
    pipeline.llm.generate_sql = AsyncMock(return_value=succ_gen)
    
    pipeline.warehouse = MagicMock()
    pipeline.warehouse.execute_readonly = AsyncMock(return_value=(
        ResultPayload(columns=["a"], rows=[[1]], row_count=1),
        ResultShape(columns=["a"], chart_type=ChartType.stat, row_count=1, aggregate_summary="1")
    ))
    
    turn = await pipeline.submit_query(req, claims)
    import asyncio
    await asyncio.sleep(0.5)
    
    pipeline.warehouse.execute_readonly.assert_called_once_with("SELECT * FROM test LIMIT 10000", snowflake_role=claims.snowflake_role, tenant_id=claims.tenant_id)
    assert turn.generated_sql == "SELECT * FROM test LIMIT 10000"


@pytest.mark.asyncio
async def test_rag_and_memory_context_propagation(claims, req):
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)
    
    pipeline = PipelineOrchestrator(sessions, events, audit)
    session, _ = await sessions.create(claims)
    req.session_id = session.session_id
    
    # Setup schema chunks
    distinctive_marker = "SCHEMA_MARKER_CUSTOMER_SEGMENT_JOIN"
    raw_row_marker = "RAW_ROW_SHOULD_NOT_REACH_GENERATION"
    test_chunks = [
        SchemaChunk(
            content=f"table users column name {distinctive_marker}",
            source_ref="users.name",
            similarity=0.95,
        )
    ]
    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=(test_chunks, 0.95))
    
    # Setup history with an OK turn
    past_turn = SessionHistoryTurn(
        turn_index=0,
        turn_id=uuid.uuid4(),
        user_query="previous net revenue query",
        generated_sql="SELECT * FROM prev",
        result_shape=ResultShape(columns=["a"], chart_type=ChartType.table, row_count=1, aggregate_summary=""),
        confidence_tier=ConfidenceTier.high,
        quality_flag=QualityFlag.ok,
        input_modality="text"
    )
    session.history.append(past_turn)
    
    pipeline.llm = MagicMock()
    succ_gen = SqlGenerationResult(sql="SELECT name FROM users", llm_self_confidence=0.9, validation_passed=True)
    pipeline.llm.generate_sql = AsyncMock(return_value=succ_gen)
    
    pipeline.warehouse = MagicMock()
    pipeline.warehouse.execute_readonly = AsyncMock(return_value=(
        ResultPayload(columns=["name"], rows=[[raw_row_marker]], row_count=1),
        ResultShape(columns=["name"], chart_type=ChartType.table, row_count=1, aggregate_summary="")
    ))
    
    turn = TurnRecord(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        user_input=req.submitted_text,
        input_modality=req.input_modality,
    )
    
    await pipeline._run_until_confidence_or_result(session, turn, claims)
    
    pipeline.llm.generate_sql.assert_called_once_with(
        req.submitted_text,
        test_chunks,
        [past_turn],
        resolved_entities=session.resolved_entities,
        feedback=None,
        previous_sql=None
    )
    call_args = pipeline.llm.generate_sql.call_args
    serialized_generation_input = repr(call_args.args) + repr(call_args.kwargs)
    assert distinctive_marker in serialized_generation_input
    assert raw_row_marker not in serialized_generation_input


@pytest.mark.asyncio
async def test_followup_generation_receives_parent_context_without_concatenating_text(claims):
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)

    pipeline = PipelineOrchestrator(sessions, events, audit)
    session, _ = await sessions.create(claims)

    parent_turn = TurnRecord(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        user_input="Show net revenue in Germany.",
        generated_sql="SELECT net_revenue FROM orders WHERE country = 'Germany'",
        result_json=ResultShape(
            columns=["country", "net_revenue"],
            chart_type=ChartType.bar,
            row_count=1,
            aggregate_summary="Germany net revenue",
        ),
        chart_type=ChartType.bar,
        confidence_tier=ConfidenceTier.high,
        input_modality="text",
        completed=True,
    )
    pipeline.turns[parent_turn.turn_id] = parent_turn
    await sessions.append_turn(
        session,
        turn_id=parent_turn.turn_id,
        user_query=parent_turn.user_input,
        generated_sql=parent_turn.generated_sql,
        result_shape=parent_turn.result_json,
        confidence_tier=parent_turn.confidence_tier,
        clarification_triggered=False,
        input_modality=parent_turn.input_modality,
    )

    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=([], 0.8))
    pipeline.llm = MagicMock()
    pipeline.llm.generate_sql = AsyncMock(
        return_value=SqlGenerationResult(
            sql="SELECT customer_segment, SUM(net_revenue) FROM orders WHERE country = 'Germany' GROUP BY customer_segment",
            validation_passed=True,
        )
    )
    pipeline.warehouse = MagicMock()
    pipeline.warehouse.execute_readonly = AsyncMock(return_value=(
        ResultPayload(columns=["customer_segment", "net_revenue"], rows=[["Enterprise", 1]], row_count=1),
        ResultShape(
            columns=["customer_segment", "net_revenue"],
            chart_type=ChartType.bar,
            row_count=1,
            aggregate_summary="Enterprise in Germany",
        )
    ))

    request = QueryRequest(
        session_id=session.session_id,
        parent_turn_id=parent_turn.turn_id,
        submitted_text="Just enterprise customers.",
        input_modality="text",
    )
    followup_turn = TurnRecord(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
        parent_turn_id=request.parent_turn_id,
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        user_input=request.submitted_text,
        input_modality=request.input_modality,
    )

    await pipeline._run_until_confidence_or_result(session, followup_turn, claims)

    args = pipeline.llm.generate_sql.call_args.args
    assert args[0] == "Just enterprise customers."
    assert "->" not in args[0]
    assert "→" not in args[0]
    history = args[2]
    assert len(history) == 1
    assert history[0].turn_id == parent_turn.turn_id
    assert history[0].user_query == "Show net revenue in Germany."
    assert "net_revenue" in history[0].generated_sql
    assert "Germany" in history[0].generated_sql


@pytest.mark.asyncio
async def test_pipeline_history_filtering_by_quality_flag(claims, req):
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)
    
    pipeline = PipelineOrchestrator(sessions, events, audit)
    session, _ = await sessions.create(claims)
    req.session_id = session.session_id
    
    # Setup schema chunks
    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=([], 0.0))
    
    # Setup history with both OK and bad quality flags
    turn_ok = SessionHistoryTurn(
        turn_index=0,
        turn_id=uuid.uuid4(),
        user_query="good query",
        generated_sql="SELECT * FROM ok",
        result_shape=ResultShape(columns=["a"], chart_type=ChartType.table, row_count=1, aggregate_summary=""),
        confidence_tier=ConfidenceTier.high,
        quality_flag=QualityFlag.ok,
        input_modality="text"
    )
    turn_bad = SessionHistoryTurn(
        turn_index=1,
        turn_id=uuid.uuid4(),
        user_query="bad query",
        generated_sql="SELECT * FROM bad",
        result_shape=ResultShape(columns=["a"], chart_type=ChartType.table, row_count=1, aggregate_summary=""),
        confidence_tier=ConfidenceTier.high,
        quality_flag=QualityFlag.low,
        input_modality="text"
    )
    session.history.extend([turn_ok, turn_bad])
    
    pipeline.llm = MagicMock()
    succ_gen = SqlGenerationResult(sql="SELECT 1", llm_self_confidence=0.9, validation_passed=True)
    pipeline.llm.generate_sql = AsyncMock(return_value=succ_gen)
    
    pipeline.warehouse = MagicMock()
    pipeline.warehouse.execute_readonly = AsyncMock(return_value=(
        ResultPayload(columns=["a"], rows=[[1]], row_count=1),
        ResultShape(columns=["a"], chart_type=ChartType.stat, row_count=1, aggregate_summary="1")
    ))
    
    turn = TurnRecord(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        user_input=req.submitted_text,
        input_modality=req.input_modality,
    )
    
    await pipeline._run_until_confidence_or_result(session, turn, claims)
    
    # Assert that only the OK turn was passed as history
    pipeline.llm.generate_sql.assert_called_once()
    called_args = pipeline.llm.generate_sql.call_args[0]
    passed_history = called_args[2]
    assert len(passed_history) == 1
    assert passed_history[0] == turn_ok


@pytest.mark.asyncio
async def test_resolved_entity_trigger_metric():
    generator = FakeSqlGenerator()
    resolved = {
        "revenue": ResolvedEntity(
            resolution="gross_revenue",
            resolved_at_turn=1,
            option_selected="Gross revenue"
        )
    }
    result = await generator.generate_sql(
        submitted_text="show revenue by region",
        schema_chunks=[],
        conversation_history=[],
        resolved_entities=resolved
    )
    # The resolved revenue entity should force gross_revenue metric SQL
    assert "total_gross_revenue" in result.sql
    assert "gross_revenue" in result.sql


@pytest.mark.asyncio
async def test_resolved_entity_counterexample_unrelated():
    generator = FakeSqlGenerator()
    resolved = {
        "unrelated_dimension": ResolvedEntity(
            resolution="geolocation_state",
            resolved_at_turn=1,
            option_selected="state"
        )
    }
    result = await generator.generate_sql(
        submitted_text="show revenue by region",
        schema_chunks=[],
        conversation_history=[],
        resolved_entities=resolved
    )
    # Unrelated entity resolved should not change the metric resolution (defaults to net_revenue)
    assert "total_net_revenue" in result.sql
    assert "net_revenue" in result.sql
