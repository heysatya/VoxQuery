import os
import pytest
from uuid import uuid4
import asyncpg

from app.models.contracts import AuthClaims, TurnRecord, InputModality, ResultPayload
from app.repositories.turn_repository import TurnRepository
from app.repositories.workspace_repository import WorkspaceRepository

from unittest.mock import MagicMock

@pytest.mark.asyncio
async def test_workspace_widgets_crud(db_pool: asyncpg.Pool):
    if isinstance(db_pool, MagicMock):
        pytest.skip("Integration test requires live database connection")
    turn_repo = TurnRepository(db_pool)
    ws_repo = WorkspaceRepository(db_pool)

    tenant_id = str(uuid4())
    user_id = str(uuid4())
    session_id = uuid4()
    turn_id = uuid4()

    claims = AuthClaims(user_id=user_id, tenant_id=tenant_id, email="ws@test.com", role="admin", snowflake_role="ANALYST")

    turn = TurnRecord(
        turn_id=turn_id, session_id=session_id, conversation_id=uuid4(), user_id=user_id, tenant_id=tenant_id,
        user_input="Revenue Widget Turn", input_modality=InputModality.text, completed=True,
        full_result=ResultPayload(columns=["quarter", "rev"], rows=[["Q1", 500]], row_count=1),
    )
    await turn_repo.save(turn, source_tables=["orders"])

    # Create / Pin widget
    widget = await ws_repo.create_widget(claims, turn_id=turn_id, title="Q1 Revenue Widget", layout_x=0, layout_y=0, layout_w=4, layout_h=3)
    widget_id = widget["id"]
    assert widget["title"] == "Q1 Revenue Widget"

    # Get widgets
    widgets = await ws_repo.get_user_widgets(claims)
    assert len(widgets) == 1
    assert widgets[0]["id"] == widget_id
    assert widgets[0]["chart_type"] == "table"

    # Update layout
    updated = await ws_repo.update_widget_layout(widget_id, claims, layout_x=4, layout_y=0, layout_w=6, layout_h=4)
    assert updated is True

    # Delete widget
    deleted = await ws_repo.delete_widget(widget_id, claims)
    assert deleted is True

    # Confirm empty
    remaining = await ws_repo.get_user_widgets(claims)
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_workspace_tenant_isolation(db_pool: asyncpg.Pool):
    if isinstance(db_pool, MagicMock):
        pytest.skip("Integration test requires live database connection")
    turn_repo = TurnRepository(db_pool)
    ws_repo = WorkspaceRepository(db_pool)

    tenant_a = str(uuid4())
    tenant_b = str(uuid4())
    user_a = str(uuid4())
    user_b = str(uuid4())
    turn_a = uuid4()

    claims_a = AuthClaims(user_id=user_a, tenant_id=tenant_a, email="a@w.com", role="admin", snowflake_role="ANALYST")
    claims_b = AuthClaims(user_id=user_b, tenant_id=tenant_b, email="b@w.com", role="admin", snowflake_role="ANALYST")

    turn = TurnRecord(
        turn_id=turn_a, session_id=uuid4(), conversation_id=uuid4(), user_id=user_a, tenant_id=tenant_a,
        user_input="Secret Tenant A Turn", input_modality=InputModality.text, completed=True,
    )
    await turn_repo.save(turn)

    widget = await ws_repo.create_widget(claims_a, turn_id=turn_a, title="Tenant A Widget")
    widget_id = widget["id"]

    # Tenant B tries to delete Tenant A's widget -> returns False
    deleted_by_b = await ws_repo.delete_widget(widget_id, claims_b)
    assert deleted_by_b is False

    # Tenant B lists widgets -> gets 0 widgets
    widgets_b = await ws_repo.get_user_widgets(claims_b)
    assert len(widgets_b) == 0
