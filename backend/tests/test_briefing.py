"""
Tests for Morning Executive Briefing API and Service (PRD V2.1 Feature 1).
"""

import pytest
from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app
from app.config import get_settings
from app.services.briefing import generate_morning_briefing

client = TestClient(app)


@pytest.mark.asyncio
async def test_generate_morning_briefing_service():
    settings = get_settings()
    tenant_id = str(uuid4())
    briefing = await generate_morning_briefing(tenant_id, settings, user_name="Executive Test")
    
    assert briefing.date is not None
    assert "Executive Briefing" in briefing.greeting
    assert len(briefing.kpis) >= 3
    assert len(briefing.anomalies) >= 1
    assert len(briefing.proactive_insights) >= 2
    assert briefing.is_live is False
    assert briefing.data_source == "fallback"


@pytest.mark.asyncio
async def test_generate_morning_briefing_live_with_nulls():
    from unittest.mock import AsyncMock, MagicMock
    from app.models.contracts import ResultPayload

    settings = get_settings()
    tenant_id = str(uuid4())
    mock_warehouse = MagicMock()
    
    # Mock query 1 returning row with NULL for tot_rev and aov
    payload1 = ResultPayload(columns=["tot_rev", "aov", "orders", "customers"], rows=[[None, None, 50, 10]], row_count=1)
    payload2 = ResultPayload(columns=["week", "rev"], rows=[], row_count=0)
    mock_warehouse.execute_readonly = AsyncMock(side_effect=[(payload1, 10), (payload2, 10)])

    briefing = await generate_morning_briefing(tenant_id, settings, user_name="Live Exec", warehouse=mock_warehouse)

    assert briefing.is_live is True
    assert briefing.data_source == "live"
    # NULL revenue & aov should render as "No data" and not silently fall back to 246.7M or 184.20
    assert briefing.kpis[0].value == "No data"
    assert briefing.kpis[2].value == "No data"
    # Live KPIs should omit change_pct/trend arrows to avoid fake deltas
    assert briefing.kpis[0].change_pct is None
    assert briefing.kpis[0].trend is None


def test_briefing_api_endpoint():
    response = client.get(
        "/api/briefing",
        headers={
            "X-Fake-User-Id": "00000000-0000-0000-0000-000000000001",
            "X-Fake-Tenant-Id": "00000000-0000-0000-0000-000000000101",
            "X-Fake-Role": "admin",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "greeting" in data
    assert "kpis" in data
    assert "anomalies" in data
    assert "summary_narrative" in data
    assert "is_live" in data
    assert "data_source" in data

