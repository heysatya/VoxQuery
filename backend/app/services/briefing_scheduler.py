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

from app.config import Settings, get_settings
from app.services.briefing import generate_morning_briefing
from app.services.briefing_dispatcher import dispatch_briefing_email
from app.warehouse.connector import WarehouseConnector

logger = logging.getLogger("voxquery.services.briefing_scheduler")

_scheduler: AsyncIOScheduler | None = None
_db_pool: asyncpg.Pool | None = None
_warehouse: WarehouseConnector | None = None


def get_scheduler(settings: Settings | None = None) -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        jobstores = {}
        if settings and settings.upstash_redis_url:
            try:
                import ssl
                from urllib.parse import urlparse
                import certifi

                parsed = urlparse(settings.upstash_redis_url)
                if parsed.hostname:
                    is_ssl = parsed.scheme == "rediss"
                    redis_kwargs = {
                        "jobs_key": "voxquery:briefing_jobs",
                        "host": parsed.hostname,
                        "port": parsed.port or 6379,
                        "password": parsed.password,
                        "ssl": is_ssl,
                    }
                    if is_ssl:
                        redis_kwargs["ssl_ca_certs"] = certifi.where()
                        redis_kwargs["ssl_cert_reqs"] = ssl.CERT_REQUIRED

                    jobstores["default"] = RedisJobStore(**redis_kwargs)
            except Exception as exc:
                logger.warning(
                    "Redis jobstore initialization failed, falling back to memory: %s", exc
                )

        _scheduler = AsyncIOScheduler(jobstores=jobstores if jobstores else None)
    return _scheduler


def start_briefing_scheduler(
    pool: asyncpg.Pool,
    settings: Settings,
    warehouse: WarehouseConnector | None = None,
) -> None:
    global _db_pool, _warehouse
    _db_pool = pool
    _warehouse = warehouse
    scheduler = get_scheduler(settings)
    if not scheduler.running:
        scheduler.add_job(
            check_and_dispatch_due_briefings,
            "interval",
            minutes=1,
            id="briefing_minute_check",
            misfire_grace_time=30,
            replace_existing=True,
        )
        scheduler.start()
        logger.info("Morning briefing scheduler started.")


async def check_and_dispatch_due_briefings(
    pool: asyncpg.Pool | None = None, settings: Settings | None = None
) -> int:
    """Checks for users whose configured delivery_time matches current local time in their timezone."""
    target_pool = pool or _db_pool
    target_settings = settings or get_settings()
    if not target_pool:
        logger.warning("No DB pool available for check_and_dispatch_due_briefings")
        return 0

    async with target_pool.acquire() as conn:
        due_users = await conn.fetch(
            """
            SELECT up.user_id, up.email, up.delivery_time, up.timezone,
                   tm.tenant_id, usr.snowflake_role
            FROM user_preferences up
            JOIN tenant_memberships tm
              ON tm.user_id = up.user_id AND tm.deleted_at IS NULL
            JOIN users u
              ON u.id = up.user_id AND u.deleted_at IS NULL
            LEFT JOIN user_snowflake_roles usr
              ON usr.user_id = tm.user_id AND usr.tenant_id = tm.tenant_id
            WHERE up.email_briefing_enabled = true
              AND up.email IS NOT NULL
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
                user_name = email.split("@", 1)[0].replace(".", " ").replace("_", " ").title()
                briefing = await generate_morning_briefing(
                    tenant_id,
                    target_settings,
                    user_name=user_name or "Executive",
                    warehouse=_warehouse,
                    snowflake_role=str(row["snowflake_role"] or "ANALYST_READONLY"),
                )
                sent = await dispatch_briefing_email(
                    user_id,
                    email,
                    briefing,
                    target_settings,
                    pool=target_pool,
                    tenant_id=tenant_id,
                    delivery_date=local_now.date(),
                )
                if sent:
                    dispatched_count += 1
            except Exception as exc:
                logger.error("Failed to dispatch scheduled briefing for user %s: %s", user_id, exc)

    return dispatched_count
