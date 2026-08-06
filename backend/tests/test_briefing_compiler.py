"""
Unit tests for Async Background Schema Compiler Service.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from app.models.contracts import ResultPayload
from app.services.briefing_compiler import get_or_compile_tenant_briefing_sql, _compiled_briefing_cache


@pytest.mark.asyncio
async def test_get_or_compile_tenant_briefing_sql_defaults():
    tenant_id = "test-tenant-123"
    _compiled_briefing_cache.pop(tenant_id, None)

    queries = await get_or_compile_tenant_briefing_sql(tenant_id, warehouse=None)
    assert "kpi_sql" in queries
    assert "trend_sql" in queries
    assert "cat_sql" in queries
    assert "order_items" in queries["kpi_sql"]

    # Verify cache hit
    cached_queries = await get_or_compile_tenant_briefing_sql(tenant_id, warehouse=None)
    assert cached_queries is queries


@pytest.mark.asyncio
async def test_get_or_compile_tenant_briefing_sql_with_warehouse():
    tenant_id = "test-tenant-456"
    _compiled_briefing_cache.pop(tenant_id, None)

    mock_warehouse = MagicMock()
    check_payload = ResultPayload(columns=["count"], rows=[[2]], row_count=1)
    mock_warehouse.execute_readonly = AsyncMock(return_value=(check_payload, 10))

    queries = await get_or_compile_tenant_briefing_sql(tenant_id, warehouse=mock_warehouse)
    assert "kpi_sql" in queries
    assert "order_items" in queries["kpi_sql"]
