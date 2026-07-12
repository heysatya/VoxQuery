import pytest
from unittest.mock import MagicMock, AsyncMock
import uuid
from app.config import Settings
from app.services.pipeline import PipelineOrchestrator
from app.core.session import InMemorySessionStore, RedisSessionStore
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
)
from app.llm.adapter import SqlGenerationResult
from tests.test_session import FakeRedis


@pytest.fixture
def claims():
    return AuthClaims(user_id=uuid.uuid4(), tenant_id=uuid.uuid4())


@pytest.fixture
def req():
    return QueryRequest(session_id=uuid.uuid4(), submitted_text="test query")


@pytest.mark.asyncio
async def test_valid_first_attempt(claims, req):
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)
    
    pipeline = PipelineOrchestrator(sessions, events, audit)
    session, _ = sessions.create(claims)
    req.session_id = session.session_id
    
    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=([SchemaChunk(content="c", source_ref="r", score=1.0)], 1.0))
    
    pipeline.llm = MagicMock()
    succ_gen = SqlGenerationResult(sql="SELECT * FROM table", validation_passed=True)
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
    
    # Assertions
    assert pipeline.llm.generate_sql.call_count == 1
    assert len(turn.attempts) == 1
    assert pipeline.warehouse.execute_readonly.call_count == 1
    
    # Check attempt structure
    attempt = turn.attempts[0]
    assert attempt.attempt_number == 1
    assert attempt.generated_sql == "SELECT * FROM table LIMIT 10000"
    assert attempt.validation_passed is True
    assert attempt.validation_error is None
    assert attempt.executed_sql_hash == attempt.sql_hash
    assert attempt.confidence_evidence is not None
    assert attempt.confidence_inputs is not None
    assert attempt.confidence_inputs.llm_self_confidence is None
    assert attempt.confidence_evidence.retrieval_score == 1.0
    assert attempt.confidence_evidence.retry_count == 0
    assert "llm_self_confidence" in attempt.confidence_evidence.inputs_absent
    assert attempt.confidence_evidence.sql_hash == attempt.executed_sql_hash
    pipeline.warehouse.execute_readonly.assert_called_once_with("SELECT * FROM table LIMIT 10000", snowflake_role=claims.snowflake_role)
    assert turn.generated_sql == "SELECT * FROM table LIMIT 10000"


@pytest.mark.asyncio
async def test_successful_correction_retry(claims, req):
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)
    
    pipeline = PipelineOrchestrator(sessions, events, audit)
    session, _ = sessions.create(claims)
    req.session_id = session.session_id
    
    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=([SchemaChunk(content="c", source_ref="r", score=1.0)], 1.0))
    
    pipeline.llm = MagicMock()
    fail_gen = SqlGenerationResult(sql="SELECT bad", validation_passed=False, validation_error="Syntax error")
    succ_gen = SqlGenerationResult(sql="SELECT good", validation_passed=True)
    pipeline.llm.generate_sql = AsyncMock(side_effect=[fail_gen, succ_gen])
    
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
    
    # Assertions
    assert pipeline.llm.generate_sql.call_count == 2
    assert len(turn.attempts) == 2
    assert pipeline.warehouse.execute_readonly.call_count == 1
    
    # Assert second call receives exact invalid SQL and validation error
    calls = pipeline.llm.generate_sql.call_args_list
    first_call_args, first_call_kwargs = calls[0]
    second_call_args, second_call_kwargs = calls[1]
    
    assert first_call_kwargs.get("feedback") is None
    assert first_call_kwargs.get("previous_sql") is None
    
    assert second_call_kwargs.get("feedback") == "Syntax error"
    assert second_call_kwargs.get("previous_sql") == "SELECT bad"
    
    # Verify execution was called with attempt 2 SQL
    pipeline.warehouse.execute_readonly.assert_called_once_with("SELECT good LIMIT 10000", snowflake_role=claims.snowflake_role)
    
    # Check attempt structures
    attempt1 = turn.attempts[0]
    assert attempt1.attempt_number == 1
    assert attempt1.generated_sql == "SELECT bad"
    assert attempt1.validation_passed is False
    assert attempt1.validation_error == "Syntax error"
    assert attempt1.executed_sql_hash is None
    
    attempt2 = turn.attempts[1]
    assert attempt2.attempt_number == 2
    assert attempt2.generated_sql == "SELECT good LIMIT 10000"
    assert attempt2.validation_passed is True
    assert attempt2.executed_sql_hash == attempt2.sql_hash
    assert attempt2.confidence_evidence.sql_hash == attempt2.executed_sql_hash
    assert attempt2.confidence_evidence.retry_count == 1


@pytest.mark.asyncio
async def test_cartesian_join_validation_feeds_correction_retry(claims, req):
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)

    pipeline = PipelineOrchestrator(sessions, events, audit)
    session, _ = sessions.create(claims)
    req.session_id = session.session_id

    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=([SchemaChunk(content="c", source_ref="r", score=1.0)], 1.0))

    pipeline.llm = MagicMock()
    pipeline.llm.generate_sql = AsyncMock(
        side_effect=[
            SqlGenerationResult(sql="SELECT * FROM orders CROSS JOIN customers", validation_passed=True),
            SqlGenerationResult(
                sql="SELECT * FROM orders JOIN customers ON orders.customer_id = customers.customer_id",
                validation_passed=True,
            ),
        ]
    )

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

    assert pipeline.llm.generate_sql.call_count == 2
    assert "CROSS JOIN" in pipeline.llm.generate_sql.call_args_list[1].kwargs["feedback"]
    pipeline.warehouse.execute_readonly.assert_called_once_with(
        "SELECT * FROM orders JOIN customers ON orders.customer_id = customers.customer_id LIMIT 10000",
        snowflake_role=claims.snowflake_role,
    )


@pytest.mark.asyncio
async def test_exhaustion_both_attempts_fail(claims, req):
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)
    
    pipeline = PipelineOrchestrator(sessions, events, audit)
    session, _ = sessions.create(claims)
    req.session_id = session.session_id
    
    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=([SchemaChunk(content="c", source_ref="r", score=1.0)], 1.0))
    
    pipeline.llm = MagicMock()
    fail_gen1 = SqlGenerationResult(sql="SELECT bad1", validation_passed=False, validation_error="Syntax error 1")
    fail_gen2 = SqlGenerationResult(sql="SELECT bad2", validation_passed=False, validation_error="Syntax error 2")
    pipeline.llm.generate_sql = AsyncMock(side_effect=[fail_gen1, fail_gen2])
    
    pipeline.warehouse = MagicMock()
    pipeline.warehouse.execute_readonly = AsyncMock()
    
    turn = TurnRecord(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        user_input=req.submitted_text,
        input_modality=req.input_modality,
    )
    
    # Assert that ApiError with code sql_generation_failed is raised
    with pytest.raises(ApiError) as exc_info:
        await pipeline._run_until_confidence_or_result(session, turn, claims)
        
    assert exc_info.value.code == ErrorCode.sql_generation_failed
    
    # Assertions
    assert pipeline.llm.generate_sql.call_count == 2
    assert len(turn.attempts) == 2
    assert pipeline.warehouse.execute_readonly.call_count == 0
    
    # Check attempt structures
    attempt1 = turn.attempts[0]
    assert attempt1.attempt_number == 1
    assert attempt1.generated_sql == "SELECT bad1"
    assert attempt1.validation_passed is False
    assert attempt1.validation_error == "Syntax error 1"
    
    attempt2 = turn.attempts[1]
    assert attempt2.attempt_number == 2
    assert attempt2.generated_sql == "SELECT bad2"
    assert attempt2.validation_passed is False
    assert attempt2.validation_error == "Syntax error 2"


@pytest.mark.asyncio
async def test_redis_query_cache_bypasses_second_warehouse_execution(claims, req):
    redis = FakeRedis()
    sessions = RedisSessionStore(
        Settings(APP_ENV="test", AUTH_MODE="fake", RESULT_CACHE_TTL_SECONDS=120),
        client=redis,
    )
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)

    pipeline = PipelineOrchestrator(sessions, events, audit, settings=sessions.settings)
    session, _ = sessions.create(claims)
    req.session_id = session.session_id

    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=([SchemaChunk(content="c", source_ref="r", score=1.0)], 1.0))
    pipeline.llm = MagicMock()
    pipeline.llm.generate_sql = AsyncMock(
        return_value=SqlGenerationResult(sql="SELECT * FROM orders", validation_passed=True)
    )
    pipeline.warehouse = MagicMock()
    pipeline.warehouse.execute_readonly = AsyncMock(return_value=(
        ResultPayload(columns=["a"], rows=[[1]], row_count=1),
        ResultShape(columns=["a"], chart_type=ChartType.stat, row_count=1, aggregate_summary="1")
    ))

    first_turn = TurnRecord(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        user_input=req.submitted_text,
        input_modality=req.input_modality,
    )
    await pipeline._run_until_confidence_or_result(session, first_turn, claims)

    second_turn = TurnRecord(
        session_id=session.session_id,
        conversation_id=session.conversation_id,
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        user_input=req.submitted_text,
        input_modality=req.input_modality,
    )
    await pipeline._run_until_confidence_or_result(session, second_turn, claims)

    assert pipeline.warehouse.execute_readonly.call_count == 1
    assert first_turn.from_cache is False
    assert second_turn.from_cache is True
    cache_keys = [key for key in redis.values if key.startswith(f"query_cache:{claims.tenant_id}:")]
    assert len(cache_keys) == 1
    assert redis.ttls[cache_keys[0]] == 120


@pytest.mark.asyncio
async def test_duplication_risk_warns_without_rerunning_distinct(claims, req):
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)

    pipeline = PipelineOrchestrator(sessions, events, audit)
    session, _ = sessions.create(claims)
    req.session_id = session.session_id

    original_sql = "SELECT customers.customer_segment FROM order_items JOIN customers ON order_items.customer_id = customers.customer_id"
    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=([], 0.8))
    pipeline.llm = MagicMock()
    pipeline.llm.generate_sql = AsyncMock(return_value=SqlGenerationResult(sql=original_sql, validation_passed=True))
    pipeline.warehouse = MagicMock()
    pipeline.warehouse.execute_readonly = AsyncMock(return_value=(
        ResultPayload(columns=["customer_segment"], rows=[["Enterprise"]], row_count=100),
        ResultShape(columns=["customer_segment"], chart_type=ChartType.table, row_count=100, aggregate_summary="many rows")
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

    expected_sql = f"{original_sql} LIMIT 10000"
    pipeline.warehouse.execute_readonly.assert_called_once_with(expected_sql, snowflake_role=claims.snowflake_role)
    assert turn.generated_sql == expected_sql
    assert turn.attempts[-1].executed_sql_hash == turn.attempts[-1].sql_hash
    assert len(turn.result_warnings) == 1
    warning = turn.result_warnings[0]
    assert warning.code == "possible_duplication"
    assert warning.suggested_sql == (
        "SELECT DISTINCT customers.customer_segment FROM order_items "
        "JOIN customers ON order_items.customer_id = customers.customer_id LIMIT 10000"
    )


@pytest.mark.asyncio
async def test_duplication_risk_does_not_warn_for_small_result(claims, req):
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)

    pipeline = PipelineOrchestrator(sessions, events, audit)
    session, _ = sessions.create(claims)
    req.session_id = session.session_id

    sql = "SELECT customers.customer_segment FROM order_items JOIN customers ON order_items.customer_id = customers.customer_id"
    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=([], 0.8))
    pipeline.llm = MagicMock()
    pipeline.llm.generate_sql = AsyncMock(return_value=SqlGenerationResult(sql=sql, validation_passed=True))
    pipeline.warehouse = MagicMock()
    pipeline.warehouse.execute_readonly = AsyncMock(return_value=(
        ResultPayload(columns=["customer_segment"], rows=[["Enterprise"]], row_count=1),
        ResultShape(columns=["customer_segment"], chart_type=ChartType.table, row_count=1, aggregate_summary="one row")
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

    pipeline.warehouse.execute_readonly.assert_called_once_with(f"{sql} LIMIT 10000", snowflake_role=claims.snowflake_role)
    assert turn.result_warnings == []


@pytest.mark.asyncio
async def test_valid_sql_limit_policy_is_applied_before_confidence_and_execution(claims, req):
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)

    pipeline = PipelineOrchestrator(sessions, events, audit)
    session, _ = sessions.create(claims)
    req.session_id = session.session_id

    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=([SchemaChunk(content="c", source_ref="r", score=1.0)], 1.0))
    pipeline.llm = MagicMock()
    pipeline.llm.generate_sql = AsyncMock(
        side_effect=[
            SqlGenerationResult(sql="SELECT * FROM orders", validation_passed=True),
            SqlGenerationResult(sql="SELECT * FROM orders LIMIT 50000", validation_passed=True),
            SqlGenerationResult(sql="SELECT * FROM orders LIMIT 100", validation_passed=True),
        ]
    )
    pipeline.warehouse = MagicMock()
    pipeline.warehouse.execute_readonly = AsyncMock(return_value=(
        ResultPayload(columns=["a"], rows=[[1]], row_count=1),
        ResultShape(columns=["a"], chart_type=ChartType.stat, row_count=1, aggregate_summary="1")
    ))

    expected_sql = [
        "SELECT * FROM orders LIMIT 10000",
        "SELECT * FROM orders LIMIT 10000",
        "SELECT * FROM orders LIMIT 100",
    ]

    for sql in expected_sql:
        turn = TurnRecord(
            session_id=session.session_id,
            conversation_id=session.conversation_id,
            user_id=claims.user_id,
            tenant_id=claims.tenant_id,
            user_input=req.submitted_text,
            input_modality=req.input_modality,
        )

        await pipeline._run_until_confidence_or_result(session, turn, claims)

        attempt = turn.attempts[-1]
        assert attempt.generated_sql == sql
        assert turn.generated_sql == sql
        assert attempt.confidence_evidence.sql_hash == attempt.sql_hash
        assert attempt.executed_sql_hash == attempt.sql_hash

    called_sql = [call.args[0] for call in pipeline.warehouse.execute_readonly.call_args_list]
    assert called_sql == expected_sql
