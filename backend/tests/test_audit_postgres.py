import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.audit.store import AuditIdentity
from app.audit.postgres import PostgresAuditStore
from app.models.contracts import ResultPayload, TurnRecord

@pytest.mark.asyncio
async def test_postgres_store_health_ok():
    store = PostgresAuditStore("fake-dsn")
    with patch("asyncpg.connect", new_callable=AsyncMock) as mock_connect:
        mock_conn = AsyncMock()
        mock_connect.return_value = mock_conn
        
        status = await store.check_health()
        assert status == "ok"
        mock_conn.close.assert_called_once()

@pytest.mark.asyncio
async def test_postgres_store_health_degraded():
    store = PostgresAuditStore("fake-dsn")
    with patch("asyncpg.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = Exception("db down")
        
        status = await store.check_health()
        assert status == "degraded"

@pytest.mark.asyncio
async def test_postgres_store_strips_full_result_and_enforces_safety():
    store = PostgresAuditStore("fake-dsn")
    store._loop = asyncio.get_running_loop()
    store._queue = asyncio.Queue()
    
    turn = TurnRecord(
        session_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        user_input="hello",
        input_modality="text",
        full_result=ResultPayload(columns=["a"], rows=[[1]], row_count=1)
    )
    
    identity = AuditIdentity(
        tenant_id=uuid.uuid4(),
        tenant_name="T",
        user_id=uuid.uuid4(),
        email="a@b",
        role="viewer",
        snowflake_role="x",
        conversation_id=uuid.uuid4(),
        conversation_title="C"
    )
    # Using enqueue_turn should NOT throw if full_result is present because it strips it.
    store.enqueue_turn(turn, identity)
    await asyncio.sleep(0.01)
    item = store._queue.get_nowait()
    assert item[0] == "turn"
    assert "full_result" not in item[1]["turn"]
    
    # But if result_json contains "rows", it MUST emit telemetry and NOT throw
    turn.result_json = {"columns": ["a"], "row_count": 1, "aggregate_summary": "1", "rows": [[1]]} # type: ignore
    with patch("app.audit.postgres.emit") as mock_emit:
        store.enqueue_turn(turn, identity)
        mock_emit.assert_called_once_with("audit.turn.security_violation", tier=1, turn_id=str(turn.turn_id))

@pytest.mark.asyncio
async def test_postgres_store_transactional_insert():
    store = PostgresAuditStore("fake-dsn")
    
    mock_conn = AsyncMock()
    mock_tx = AsyncMock()
    
    class MockAcquireContext:
        async def __aenter__(self): return mock_conn
        async def __aexit__(self, exc_type, exc, tb): pass
        
    class MockTransactionContext:
        async def __aenter__(self): return mock_tx
        async def __aexit__(self, exc_type, exc, tb): pass

    mock_conn.transaction = MagicMock(return_value=MockTransactionContext())
    
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=MockAcquireContext())
    store._pool = mock_pool

    turn = TurnRecord(
        session_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        user_input="hello",
        input_modality="text",
    )
    
    identity = AuditIdentity(
        tenant_id=uuid.uuid4(),
        tenant_name="T",
        user_id=uuid.uuid4(),
        email="a@b",
        role="viewer",
        snowflake_role="x",
        conversation_id=uuid.uuid4(),
        conversation_title="C"
    )
    
    payload = {
        "turn": turn.model_dump(exclude={"full_result"}, mode="json"),
        "identity": identity.__dict__,
        "clarification": None
    }
    
    await store._insert_turn(payload)
    
    # Assert 5 executions (tenant, user, user_role, conversation, turn)
    assert mock_conn.execute.call_count == 5
    args = mock_conn.execute.call_args_list[-1][0]
    assert "INSERT INTO turns" in args[0]
    assert args[1] == str(turn.turn_id)
    
    # Verify user_snowflake_roles insertion has correct number of args (query + 3 parameters)
    roles_args = mock_conn.execute.call_args_list[2][0]
    assert "INSERT INTO user_snowflake_roles (user_id, tenant_id, snowflake_role)" in roles_args[0]
    assert len(roles_args) == 4
    
    # Test clarification schema insertion
    payload["clarification"] = {
        "id": str(uuid.uuid4()),
        "turn_id": str(turn.turn_id),
        "prompt_sent": "ambiguous",
        "user_choice": None,
        "resolution_type": "escaped",
        "created_at": "2026-07-05T00:00:00Z"
    }
    
    mock_conn.execute.reset_mock()
    await store._insert_turn(payload)
    assert mock_conn.execute.call_count == 6
    clarification_args = mock_conn.execute.call_args_list[-1][0]
    assert "INSERT INTO clarifications" in clarification_args[0]
    assert "id, turn_id, prompt_sent, user_choice, resolution_type, created_at" in clarification_args[0]
    # Expect 5 elements: query + turn_id, prompt_sent, user_choice, resolution_type
    assert len(clarification_args) == 5
    
@pytest.mark.asyncio
async def test_worker_emits_telemetry_on_queue_failure():
    store = PostgresAuditStore("fake-dsn")
    store._queue = asyncio.Queue()
    store._queue.get = AsyncMock(side_effect=[Exception("queue dead"), asyncio.CancelledError()])
    
    with patch("app.audit.postgres.emit") as mock_emit, \
         patch("asyncpg.create_pool", new_callable=AsyncMock):
        # Run worker briefly
        task = asyncio.create_task(store._async_worker_loop())
        await asyncio.sleep(0.01)
        task.cancel()
        
        mock_emit.assert_called_with("audit.worker.queue_read_error", tier=1, error="queue dead")
