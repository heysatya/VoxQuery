"""User Preferences Service backed by Postgres."""

from __future__ import annotations
from typing import Any
import asyncpg

from app.models.contracts import UserPreferences


async def get_user_preferences(user_id: Any, db_pool: asyncpg.Pool) -> UserPreferences:
    user_id_str = str(user_id)
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT email_briefing_enabled, email, delivery_time, timezone FROM user_preferences WHERE user_id = $1",
            user_id_str,
        )
        if not row:
            return UserPreferences(user_id=user_id_str)
        return UserPreferences(
            user_id=user_id_str,
            email_briefing_enabled=bool(row["email_briefing_enabled"]),
            email=row["email"],
            delivery_time=row["delivery_time"] or "09:00",
            timezone=row["timezone"] or "UTC",
        )


async def update_user_preferences(
    user_id: Any,
    db_pool: asyncpg.Pool,
    email_briefing_enabled: bool = False,
    email: str | None = None,
    delivery_time: str = "09:00",
    timezone: str = "UTC",
) -> UserPreferences:
    user_id_str = str(user_id)
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_preferences (user_id, email_briefing_enabled, email, delivery_time, timezone, updated_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                email_briefing_enabled = EXCLUDED.email_briefing_enabled,
                email = EXCLUDED.email,
                delivery_time = EXCLUDED.delivery_time,
                timezone = EXCLUDED.timezone,
                updated_at = NOW()
            """,
            user_id_str,
            email_briefing_enabled,
            email,
            delivery_time,
            timezone,
        )
    return UserPreferences(
        user_id=user_id_str,
        email_briefing_enabled=email_briefing_enabled,
        email=email,
        delivery_time=delivery_time,
        timezone=timezone,
    )
