from dataclasses import dataclass
import logging
from time import monotonic
from typing import Optional

from app.config import Settings
import redis.asyncio as redis

logger = logging.getLogger(__name__)


@dataclass
class RateLimitResult:
    ok: bool
    retry_after_seconds: Optional[float] = None
    available: bool = True


class RateLimiter:
    """
    Redis-backed rate limiter for VoxQuery.
    Applies limits per tenant/user across all instances when Redis is enabled.
    """

    def __init__(self, settings: Settings, client: redis.Redis | None = None):
        self.window_seconds = 60
        self.max_requests_per_window = getattr(settings, "rate_limit_per_minute", 60)
        self.settings = settings
        self._local_hits: dict[str, tuple[int, float]] = {}
        if client:
            self.client = client
        elif settings.app_env == "test":

            class _StubPipeline:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, tb):
                    pass

                def incr(self, key):
                    pass

                def ttl(self, key):
                    pass

                async def execute(self):
                    return 1, 60

            class _StubRedis:
                def pipeline(self):
                    return _StubPipeline()

                async def expire(self, key, seconds):
                    pass

            self.client = _StubRedis()
        else:
            if not settings.upstash_redis_url:
                if settings.app_env in {"staging", "production"}:
                    raise RuntimeError("UPSTASH_REDIS_URL is required for RateLimiter.")
                logger.warning(
                    "rate_limit.redis_unconfigured environment=%s using process-local development limiter",
                    settings.app_env,
                )
                self.client = None
                return
            import certifi
            import ssl

            ssl_kwargs = {}
            if settings.upstash_redis_url.startswith("rediss://"):
                ssl_kwargs = {
                    "ssl_ca_certs": certifi.where(),
                    "ssl_cert_reqs": ssl.CERT_REQUIRED,
                }

            self.client = redis.Redis.from_url(
                settings.upstash_redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                **ssl_kwargs,
            )

    def _key(self, user_id: str, tenant_id: str | None = None, action: str = "default") -> str:
        scope = tenant_id or "global"
        return f"ratelimit:{action}:{scope}:{user_id}"

    async def check_rate_limit(
        self,
        user_id: str,
        tenant_id: str | None = None,
        action: str = "default",
        max_requests: int | None = None,
    ) -> RateLimitResult:
        key = self._key(user_id, tenant_id, action=action)
        effective_limit = max_requests if max_requests is not None else self.max_requests_per_window

        if self.client is None:
            now = monotonic()
            count, reset_at = self._local_hits.get(key, (0, now + self.window_seconds))
            if reset_at <= now:
                count, reset_at = 0, now + self.window_seconds
            count += 1
            self._local_hits[key] = (count, reset_at)
            if count > effective_limit:
                return RateLimitResult(ok=False, retry_after_seconds=max(1.0, reset_at - now))
            return RateLimitResult(ok=True)

        # We use a simple counter with TTL
        # To make it atomic and correct, we can use a pipeline
        try:
            async with self.client.pipeline() as pipe:
                pipe.incr(key)
                pipe.ttl(key)
                count, ttl = await pipe.execute()

            if count == 1 or ttl == -1:
                # First request or TTL lost
                await self.client.expire(key, self.window_seconds)
                return RateLimitResult(ok=True)

            if count > effective_limit:
                # Limit exceeded
                return RateLimitResult(
                    ok=False, retry_after_seconds=float(ttl if ttl > 0 else self.window_seconds)
                )

            return RateLimitResult(ok=True)
        except Exception as exc:
            # Never fail open for protected analytical operations. Returning a
            # distinct unavailable result lets callers return 503 rather than
            # pretending the request was safely admitted.
            logger.warning("rate_limit.redis_unavailable error=%s", type(exc).__name__)
            return RateLimitResult(ok=False, available=False)

    async def close(self) -> None:
        close = getattr(self.client, "aclose", None)
        if close is not None:
            await close()
