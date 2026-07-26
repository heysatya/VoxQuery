import os
import pytest
from uuid import uuid4
import asyncpg

from app.models.contracts import (
    TurnRecord, AuthClaims, InputModality, ChartType, ConfidenceTier, ResultPayload, ResultShape
)
from app.repositories.turn_repository import TurnRepository

from unittest.mock import MagicMock

@pytest.mark.asyncio
async def test_turn_repository_save_and_retrieve(db_pool: asyncpg.Pool):
    if isinstance(db_pool, MagicMock):
        pytest.skip("Integration test requires live database connection")
    repo = TurnRepository(db_pool)
    tenant_id = str(uuid4())
    user_id = str(uuid4())
    session_id = uuid4()
    conversation_id = uuid4()
    test_email = f"exec-{uuid4()}@tenant-a.com"

    claims = AuthClaims(
        user_id=user_id,
        tenant_id=tenant_id,
        email=test_email,
        role="admin",
        snowflake_role="ANALYST",
    )

    # Seed required foreign key records in database
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO tenants (id, name) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
            tenant_id, "Tenant A"
        )
        await conn.execute(
            """
            INSERT INTO users (id, email) VALUES ($1, $2)
            ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email
            """,
            user_id, claims.email
        )

    turn = TurnRecord(
        turn_id=uuid4(),
        session_id=session_id,
        conversation_id=conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
        user_input="Show total revenue for CA in 2026",
        generated_sql="SELECT sum(amount) FROM orders WHERE state = 'CA'",
        chart_type=ChartType.bar,
        chart_rationale="Bar chart for revenue breakdown",
        confidence_tier=ConfidenceTier.high,
        composite_score=0.95,
        input_modality=InputModality.text,
        completed=True,
        full_result=ResultPayload(
            columns=["state", "amount"],
            rows=[["CA", 50000.0]],
            row_count=1,
        ),
        result_json=ResultShape(
            columns=["state", "amount"],
            chart_type=ChartType.bar,
            row_count=1,
            aggregate_summary="Total revenue for CA is $50,000",
        ),
    )

    source_tables = ["orders"]
    filter_predicates = [{"column": "state", "operator": "eq", "value": "CA"}]

    await repo.save(turn, source_tables=source_tables, filter_predicates=filter_predicates)

    # Fetch single turn
    fetched = await repo.get_turn(turn.turn_id, claims)
    assert fetched is not None
    assert fetched["turn_id"] == turn.turn_id
    assert fetched["tenant_id"] == tenant_id
    assert fetched["source_tables"] == ["orders"]
    assert fetched["filter_predicates"] == filter_predicates
    assert fetched["user_input"] == turn.user_input

    # Fetch session turns
    session_turns = await repo.get_session_turns(session_id, claims)
    assert len(session_turns) == 1
    assert session_turns[0]["turn_id"] == turn.turn_id


@pytest.mark.asyncio
async def test_turn_repository_cross_tenant_isolation(db_pool: asyncpg.Pool):
    if isinstance(db_pool, MagicMock):
        pytest.skip("Integration test requires live database connection")
    repo = TurnRepository(db_pool)
    tenant_a = str(uuid4())
    tenant_b = str(uuid4())
    user_a = str(uuid4())
    user_b = str(uuid4())
    session_a = uuid4()
    session_b = uuid4()

    email_a = f"a-{uuid4()}@t.com"
    email_b = f"b-{uuid4()}@t.com"

    claims_a = AuthClaims(user_id=user_a, tenant_id=tenant_a, email=email_a, role="admin", snowflake_role="ANALYST")
    claims_b = AuthClaims(user_id=user_b, tenant_id=tenant_b, email=email_b, role="admin", snowflake_role="ANALYST")

    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO tenants (id, name) VALUES ($1, 'TA'), ($2, 'TB') ON CONFLICT DO NOTHING", tenant_a, tenant_b)
        await conn.execute("INSERT INTO users (id, email) VALUES ($1, $2) ON CONFLICT DO NOTHING", user_a, email_a)
        await conn.execute("INSERT INTO users (id, email) VALUES ($1, $2) ON CONFLICT DO NOTHING", user_b, email_b)

    turn_a = TurnRecord(
        turn_id=uuid4(), session_id=session_a, conversation_id=uuid4(), user_id=user_a, tenant_id=tenant_a,
        user_input="Tenant A Query", input_modality=InputModality.text, completed=True,
    )
    turn_b = TurnRecord(
        turn_id=uuid4(), session_id=session_b, conversation_id=uuid4(), user_id=user_b, tenant_id=tenant_b,
        user_input="Tenant B Query", input_modality=InputModality.text, completed=True,
    )

    await repo.save(turn_a, source_tables=["table_a"], filter_predicates=[])
    await repo.save(turn_b, source_tables=["table_b"], filter_predicates=[])

    # Tenant B tries to fetch Tenant A's single turn -> returns None
    stolen_turn = await repo.get_turn(turn_a.turn_id, claims_b)
    assert stolen_turn is None

    # Tenant B tries to fetch Tenant A's session -> returns 0 rows
    stolen_session = await repo.get_session_turns(session_a, claims_b)
    assert len(stolen_session) == 0


@pytest.mark.asyncio
async def test_turn_repository_process_restart_survival(db_pool: asyncpg.Pool):
    if isinstance(db_pool, MagicMock):
        pytest.skip("Integration test requires live database connection")
    tenant_id = str(uuid4())
    user_id = str(uuid4())
    session_id = uuid4()
    turn_id = uuid4()
    email = f"restart-{uuid4()}@test.com"

    claims = AuthClaims(user_id=user_id, tenant_id=tenant_id, email=email, role="admin", snowflake_role="ANALYST")

    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO tenants (id, name) VALUES ($1, 'Restart Tenant') ON CONFLICT DO NOTHING", tenant_id)
        await conn.execute("INSERT INTO users (id, email) VALUES ($1, $2) ON CONFLICT DO NOTHING", user_id, claims.email)

    # Initial process saves turn
    repo_1 = TurnRepository(db_pool)
    turn = TurnRecord(
        turn_id=turn_id, session_id=session_id, conversation_id=uuid4(), user_id=user_id, tenant_id=tenant_id,
        user_input="Persisted across restart", input_modality=InputModality.text, completed=True,
    )
    await repo_1.save(turn, source_tables=["orders"], filter_predicates=[])

    # Simulate process restart by dropping repo_1 and instantiating a fresh TurnRepository
    del repo_1
    repo_2 = TurnRepository(db_pool)

    fetched = await repo_2.get_turn(turn_id, claims)
    assert fetched is not None
    assert fetched["turn_id"] == turn_id
    assert fetched["user_input"] == "Persisted across restart"
