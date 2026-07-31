"""APScheduler-based Morning Briefing Scheduler Service.

Periodically checks user preferences and dispatches due executive briefing emails.
Enforces idempotency via briefing_send_log table and Redis job store.
"""
from __future__ import annotations
from datetime import datetime
import logging
from zoneinfo import ZoneInfo
from uuid import UUID
import asyncpg
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.redis import RedisJobStore

from app.config import Settings
from app.services.briefing import generate_morning_briefing
from app.services.briefing_dispatcher import dispatch_briefing_email

logger = logging.getLogger("voxquery.services.briefing_scheduler")

_scheduler: AsyncIOScheduler | None = None


def get_scheduler(settings: Settings | None = None) -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        jobstores = {}
        if settings and settings.upstash_redis_url:
            try:
                jobstores["default"] = RedisJobStore(jobs_key="voxquery:briefing_jobs", host=settings.upstash_redis_url)
            except Exception as exc:
                logger.warning("Redis jobstore initialization failed, falling back to memory: %s", exc)

        _scheduler = AsyncIOScheduler(jobstores=jobstores if jobstores else None)
    return _scheduler


def start_briefing_scheduler(pool: asyncpg.Pool, settings: Settings) -> None:
    scheduler = get_scheduler(settings)
    if not scheduler.running:
        scheduler.add_job(
            check_and_dispatch_due_briefings,
            "interval",
            minutes=1,
            args=[pool, settings],
            id="briefing_minute_check",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("Morning briefing scheduler started.")


async def check_and_dispatch_due_briefings(pool: asyncpg.Pool, settings: Settings) -> int:
    """Checks for users whose configured delivery_time matches current local time in their timezone."""
    async with pool.acquire() as conn:
        due_users = await conn.fetch(
            """
            SELECT up.user_id, up.email, up.delivery_time, up.timezone, u.tenant_id
            FROM user_preferences up
            JOIN users u ON u.id = up.user_id
            WHERE up.email_briefing_enabled = true
              AND up.email IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM briefing_send_log bsl
                  WHERE bsl.user_id = up.user_id AND bsl.send_date = CURRENT_DATE
              )
            """
        )

    dispatched_count = 0
    for row in due_users:
        user_id = str(row["user_id"])
        email: str = row["email"]
        tenant_id = str(row["tenant_id"])
        tz_name: str = row["timezone"] or "UTC"
        delivery_time: str = row["delivery_time"] or "08:00"

        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")

        local_now = datetime.now(tz)
        try:
            target_hour, target_minute = map(int, delivery_time.split(":"))
        except ValueError:
            target_hour, target_minute = 8, 0

        if local_now.hour == target_hour and local_now.minute == target_minute:
            try:
                briefing = await generate_morning_briefing(tenant_id, settings, user_name="Executive")
                await dispatch_briefing_email(user_id, email, briefing, settings, pool=pool, tenant_id=tenant_id)
                dispatched_count += 1
            except Exception as exc:
                logger.error("Failed to dispatch scheduled briefing for user %s: %s", user_id, exc)

    return dispatched_count
