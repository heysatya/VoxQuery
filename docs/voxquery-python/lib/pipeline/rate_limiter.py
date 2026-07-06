import time
from dataclasses import dataclass

# NOTE: in-memory state doesn't survive across multiple process instances
# (e.g. multiple Vercel serverless function containers running in parallel).
# For real production use, swap this for Redis (Upstash has a generous free
# tier) — the function signature below is designed so that swap doesn't
# touch any calling code.

_buckets: dict[str, tuple[int, float]] = {}  # user_id -> (count, window_start)

WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 20  # per user, covers query + TTS calls combined


@dataclass
class RateLimitResult:
    ok: bool
    retry_after_seconds: float | None = None


def check_rate_limit(user_id: str) -> RateLimitResult:
    now = time.time()
    count, window_start = _buckets.get(user_id, (0, now))

    if now - window_start > WINDOW_SECONDS:
        _buckets[user_id] = (1, now)
        return RateLimitResult(ok=True)

    if count >= MAX_REQUESTS_PER_WINDOW:
        return RateLimitResult(ok=False, retry_after_seconds=WINDOW_SECONDS - (now - window_start))

    _buckets[user_id] = (count + 1, window_start)
    return RateLimitResult(ok=True)
