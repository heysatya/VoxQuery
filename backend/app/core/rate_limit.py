from dataclasses import dataclass
from typing import Optional

from app.config import Settings
import redis.asyncio as redis


@dataclass
class RateLimitResult:
    ok: bool
    retry_after_seconds: Optional[float] = None


class RateLimiter:
    """
    Redis-backed rate limiter for VoxQuery.
    Applies limits per user across all instances.
    """
    def __init__(self, settings: Settings, client: redis.Redis | None = None):
        self.window_seconds = 60
        self.max_requests_per_window = 5
        self.settings = settings
        if client:
            self.client = client
        elif settings.app_env == "test":
            class _StubPipeline:
                async def __aenter__(self): return self
                async def __aexit__(self, exc_type, exc, tb): pass
                def incr(self, key): pass
                def ttl(self, key): pass
                async def execute(self): return 1, 60
            class _StubRedis:
                def pipeline(self): return _StubPipeline()
                async def expire(self, key, seconds): pass
            self.client = _StubRedis()
        else:
            if not settings.upstash_redis_url:
                raise RuntimeError("UPSTASH_REDIS_URL is required for RateLimiter.")
            self.client = redis.Redis.from_url(
                settings.upstash_redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )

    def _key(self, user_id: str) -> str:
        return f"ratelimit:{user_id}"

    async def check_rate_limit(self, user_id: str) -> RateLimitResult:
        key = self._key(user_id)
        
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
                
            if count > self.max_requests_per_window:
                # Limit exceeded
                return RateLimitResult(ok=False, retry_after_seconds=float(ttl if ttl > 0 else self.window_seconds))
                
            return RateLimitResult(ok=True)
        except Exception:
            # Fail open if Redis is down
            return RateLimitResult(ok=True)
