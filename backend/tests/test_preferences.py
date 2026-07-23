import os
import pytest
from uuid import uuid4
import asyncpg
from app.services.preferences import get_user_preferences, update_user_preferences

from unittest.mock import MagicMock

@pytest.mark.asyncio
async def test_user_preferences_db_persistence(db_pool: asyncpg.Pool):
    if isinstance(db_pool, MagicMock):
        pytest.skip("Integration test requires live database connection")
    tenant_id = uuid4()
    user_id = uuid4()
    email = f"pref-{uuid4()}@test.com"

    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO tenants (id, name) VALUES ($1, 'Pref Tenant') ON CONFLICT DO NOTHING", str(tenant_id))
        await conn.execute("INSERT INTO users (id, email) VALUES ($1, $2) ON CONFLICT DO NOTHING", str(user_id), email)

    # Initial get returns defaults
    defaults = await get_user_preferences(user_id, db_pool)
    assert defaults.email_briefing_enabled is False
    assert defaults.timezone == "UTC"

    # Update preferences
    updated = await update_user_preferences(
        user_id,
        db_pool,
        email_briefing_enabled=True,
        email=email,
        delivery_time="09:30",
        timezone="America/New_York",
    )
    assert updated.email_briefing_enabled is True
    assert updated.delivery_time == "09:30"
    assert updated.timezone == "America/New_York"

    # Verify retrieval from fresh pool query
    fetched = await get_user_preferences(user_id, db_pool)
    assert fetched.email_briefing_enabled is True
    assert fetched.email == email
    assert fetched.delivery_time == "09:30"
    assert fetched.timezone == "America/New_York"
