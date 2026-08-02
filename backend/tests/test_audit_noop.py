import uuid
import pytest
from app.audit.store import AuditIdentity
from app.audit.noop import NoopAuditStore
from app.models.contracts import TurnRecord


@pytest.mark.asyncio
async def test_noop_health():
    store = NoopAuditStore()
    assert await store.check_health() == "not_configured"


@pytest.mark.asyncio
async def test_noop_methods_do_not_throw():
    store = NoopAuditStore()
    await store.start()

    turn = TurnRecord(
        session_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        user_id=str(uuid.uuid4()),
        tenant_id=str(uuid.uuid4()),
        user_input="hello",
        input_modality="text",
    )
    identity = AuditIdentity(
        tenant_id=str(uuid.uuid4()),
        tenant_name="T",
        user_id=str(uuid.uuid4()),
        email="a@b",
        role="viewer",
        snowflake_role="x",
        conversation_id=uuid.uuid4(),
        conversation_title="C",
    )
    store.enqueue_turn(turn, identity)
    store.enqueue_feedback(str(turn.turn_id), "low")

    await store.stop()
