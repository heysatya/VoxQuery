"""
Regression tests for the security/correctness fixes made after the UX/code audit:

  1. Result cache is scoped by (tenant_id, snowflake_role, sql) — not just
     (tenant_id, sql) — so two roles in the same tenant with different
     row-level-security visibility can never read each other's cached rows.
  2. `snowflake_role` is validated against an identifier allowlist before it
     is spliced into the `USE ROLE IDENTIFIER(...)` SQL string.
  3. The execution/confidence SQL-hash integrity check raises a structured
     ApiError instead of relying on a bare `assert` (which is stripped when
     Python runs with -O).
"""
import uuid

import pytest

from app.core.session import InMemorySessionStore
from app.services.events import PipelineEventBus
from app.services.pipeline import PipelineOrchestrator
from app.models.contracts import ApiError, ResultPayload, ResultShape, ChartType
from app.warehouse.snowflake import _validate_snowflake_role


class _FakeRedisClient:
    """Minimal in-memory stand-in for the redis client used by the cache."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str):
        self.store[key] = value


def _make_pipeline_with_cache():
    sessions = InMemorySessionStore()
    sessions.client = _FakeRedisClient()
    events = PipelineEventBus()
    pipeline = PipelineOrchestrator(sessions, events, audit=None)
    pipeline.settings.result_cache_ttl_seconds = 300
    return pipeline


@pytest.mark.asyncio
async def test_cache_is_scoped_by_snowflake_role():
    pipeline = _make_pipeline_with_cache()
    tenant_id = uuid.uuid4()
    sql = "SELECT * FROM revenue LIMIT 10"
    result = ResultPayload(columns=["a"], rows=[[1]], row_count=1)
    shape = ResultShape(columns=["a"], chart_type=ChartType.stat, row_count=1, aggregate_summary="")

    # A result cached under a permissive role...
    await pipeline._store_cached_result(tenant_id, sql, result, shape, "ANALYST_FULL")

    # ...must NOT be visible to a different role in the same tenant running
    # the exact same SQL text.
    cached_for_other_role = await pipeline._get_cached_result(tenant_id, sql, "ANALYST_RESTRICTED")
    assert cached_for_other_role is None

    # But it IS visible to the role that generated it.
    cached_for_same_role = await pipeline._get_cached_result(tenant_id, sql, "ANALYST_FULL")
    assert cached_for_same_role is not None


@pytest.mark.asyncio
async def test_cache_key_includes_role_component():
    pipeline = _make_pipeline_with_cache()
    tenant_id = uuid.uuid4()
    key_a = pipeline._cache_key(tenant_id, "SELECT 1", "ROLE_A")
    key_b = pipeline._cache_key(tenant_id, "SELECT 1", "ROLE_B")
    assert key_a != key_b


def test_validate_snowflake_role_accepts_normal_identifiers():
    assert _validate_snowflake_role("ANALYST_READONLY") == "ANALYST_READONLY"
    assert _validate_snowflake_role("role$1") == "role$1"


@pytest.mark.parametrize(
    "malicious_role",
    [
        "ANALYST') ; DROP TABLE users; --",
        "ANALYST' OR '1'='1",
        "PUBLIC'); USE ROLE ACCOUNTADMIN; --",
        "",
        "1STARTSWITHDIGIT",
    ],
)
def test_validate_snowflake_role_rejects_injection_attempts(malicious_role):
    with pytest.raises(ApiError):
        _validate_snowflake_role(malicious_role)
