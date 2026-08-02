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
    assert briefing.greeting == "Business pulse unavailable"
    assert briefing.kpis == []
    assert briefing.anomalies == []
    assert briefing.proactive_insights == []
    assert briefing.is_live is False
    assert briefing.data_source == "unavailable"


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


@pytest.mark.asyncio
async def test_generate_morning_briefing_anomaly_cap_and_date_formatting():
    from unittest.mock import AsyncMock, MagicMock
    from datetime import date
    from app.models.contracts import ResultPayload

    settings = get_settings()
    tenant_id = str(uuid4())
    mock_warehouse = MagicMock()

    payload1 = ResultPayload(columns=["tot_rev", "aov", "orders", "customers"], rows=[[50000.0, 100.0, 500, 200]], row_count=1)
    
    # 15 weeks with 5 huge spikes
    rows2 = [
        [date(2025, 1, 1), 100.0],
        [date(2025, 1, 8), 102.0],
        [date(2025, 1, 15), 98.0],
        [date(2025, 1, 22), 101.0],
        [date(2025, 1, 29), 1000.0],  # Outlier 1
        [date(2025, 2, 5), 99.0],
        [date(2025, 2, 12), 101.0],
        [date(2025, 2, 19), 1500.0],  # Outlier 2
        [date(2025, 2, 26), 100.0],
        [date(2025, 3, 5), 2000.0],  # Outlier 3
        [date(2025, 3, 12), 2500.0],  # Outlier 4
        [date(2025, 3, 19), 3000.0],  # Outlier 5
    ]
    payload2 = ResultPayload(columns=["order_week", "weekly_revenue"], rows=rows2, row_count=len(rows2))
    mock_warehouse.execute_readonly = AsyncMock(side_effect=[(payload1, 10), (payload2, 10)])

    briefing = await generate_morning_briefing(tenant_id, settings, user_name="Exec Test", warehouse=mock_warehouse)

    # (b) Cap to top 3 most significant anomalies
    assert len(briefing.anomalies) == 3
    # (d) Check that title uses actual formatted date instead of "Week N"
    for anomaly in briefing.anomalies:
        assert "Revenue Variance (" in anomaly.title
        assert "Week " not in anomaly.title
