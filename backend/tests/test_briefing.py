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
    payload1 = ResultPayload(
        columns=["tot_rev", "aov", "orders", "customers"], rows=[[None, None, 50, 10]], row_count=1
    )
    payload2 = ResultPayload(columns=["week", "rev"], rows=[], row_count=0)
    mock_warehouse.execute_readonly = AsyncMock(side_effect=[(payload1, 10), (payload2, 10)])

    briefing = await generate_morning_briefing(
        tenant_id, settings, user_name="Live Exec", warehouse=mock_warehouse
    )

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
async def test_generate_morning_briefing_anomaly_cap_and_ranked_titles():
    from unittest.mock import AsyncMock, MagicMock
    from datetime import date
    from app.models.contracts import ResultPayload

    settings = get_settings()
    tenant_id = str(uuid4())
    mock_warehouse = MagicMock()

    payload1 = ResultPayload(
        columns=["tot_rev", "aov", "orders", "customers"],
        rows=[[50000.0, 100.0, 500, 200]],
        row_count=1,
    )

    # 15 weeks with 5 huge spikes (kept off 2024/2025 — those years are
    # deliberately excluded from anomaly flags; see test below for that).
    rows2 = [
        [date(2023, 1, 1), 100.0],
        [date(2023, 1, 8), 102.0],
        [date(2023, 1, 15), 98.0],
        [date(2023, 1, 22), 101.0],
        [date(2023, 1, 29), 1000.0],  # Outlier 1
        [date(2023, 2, 5), 99.0],
        [date(2023, 2, 12), 101.0],
        [date(2023, 2, 19), 1500.0],  # Outlier 2
        [date(2023, 2, 26), 100.0],
        [date(2023, 3, 5), 2000.0],  # Outlier 3
        [date(2023, 3, 12), 2500.0],  # Outlier 4
        [date(2023, 3, 19), 3000.0],  # Outlier 5
    ]
    payload2 = ResultPayload(
        columns=["order_week", "weekly_revenue"], rows=rows2, row_count=len(rows2)
    )
    mock_warehouse.execute_readonly = AsyncMock(side_effect=[(payload1, 10), (payload2, 10)])

    briefing = await generate_morning_briefing(
        tenant_id, settings, user_name="Exec Test", warehouse=mock_warehouse
    )

    # (b) Cap to top 3 most significant anomalies
    assert len(briefing.anomalies) == 3
    # Titles must rank by magnitude ("Biggest", "Second-biggest", ...) and
    # must NEVER surface a calendar date/year — a "week of Oct 2023" flag
    # next to a header dated today reads as stale data, not a live pulse.
    # Ranking is by absolute dollar deviation from baseline (not percent —
    # a $8.5M swing outranks a smaller-dollar move even if its % happens to
    # be lower against a different trailing baseline), so magnitude_pct is
    # not expected to be monotonic across ranks; only the ordinal labels
    # and the absence of any date are asserted here.
    expected_ordinals = ["Biggest", "Second-biggest", "Third-biggest"]
    for anomaly, ordinal in zip(briefing.anomalies, expected_ordinals):
        assert anomaly.title == f"{ordinal} revenue spike"
        assert "2023" not in anomaly.title
        assert "2023" not in anomaly.description
        assert "%" in anomaly.description
        assert anomaly.severity in ("warning", "critical")
        assert anomaly.direction == "up"
        assert anomaly.magnitude_pct is not None and anomaly.magnitude_pct > 0
        # follow_up_query is the ONE place the real date is allowed to
        # appear: it's a hidden prompt sent to the pipeline when the user
        # clicks the flag (never rendered in the UI), and it needs a
        # concrete week to anchor a real, aggregated query instead of the
        # vague-prompt join fan-out a bare "Biggest revenue spike" causes.
        assert anomaly.follow_up_query is not None
        assert "2023" in anomaly.follow_up_query
        assert "%" in anomaly.follow_up_query
        assert anomaly.follow_up_query != anomaly.title


@pytest.mark.asyncio
async def test_generate_morning_briefing_excludes_2024_2025_anomalies():
    """Anomaly candidates dated 2024/2025 are stale/synthetic artifacts of the
    source data and must never surface as flags in Business Pulse, even if
    they'd otherwise be the most statistically significant outliers."""
    from unittest.mock import AsyncMock, MagicMock
    from datetime import date
    from app.models.contracts import ResultPayload

    settings = get_settings()
    tenant_id = str(uuid4())
    mock_warehouse = MagicMock()

    payload1 = ResultPayload(
        columns=["tot_rev", "aov", "orders", "customers"],
        rows=[[50000.0, 100.0, 500, 200]],
        row_count=1,
    )

    # Stable baseline weeks in 2023, then a huge spike in 2024 and another in
    # 2025. Neither spike should ever appear in briefing.anomalies.
    rows2 = [
        [date(2023, 1, 1), 100.0],
        [date(2023, 1, 8), 102.0],
        [date(2023, 1, 15), 98.0],
        [date(2023, 1, 22), 101.0],
        [date(2023, 1, 29), 99.0],
        [date(2024, 1, 7), 5000.0],  # Excluded spike — 2024
        [date(2025, 1, 5), 6000.0],  # Excluded spike — 2025
    ]
    payload2 = ResultPayload(
        columns=["order_week", "weekly_revenue", "weekly_orders", "weekly_customers"],
        rows=rows2,
        row_count=len(rows2),
    )
    mock_warehouse.execute_readonly = AsyncMock(side_effect=[(payload1, 10), (payload2, 10)])

    briefing = await generate_morning_briefing(
        tenant_id, settings, user_name="Exec Test", warehouse=mock_warehouse
    )

    assert briefing.anomalies == []
    for anomaly in briefing.anomalies:
        assert "2024" not in anomaly.title
        assert "2025" not in anomaly.title


@pytest.mark.asyncio
async def test_generate_morning_briefing_week_over_week_kpi_deltas():
    """KPI cards should carry a real week-over-week % change and direction,
    computed from the two most recent weeks in the trend series — not the
    None placeholders the endpoint used to return."""
    from unittest.mock import AsyncMock, MagicMock
    from datetime import date
    from app.models.contracts import ResultPayload

    settings = get_settings()
    tenant_id = str(uuid4())
    mock_warehouse = MagicMock()

    payload1 = ResultPayload(
        columns=["tot_rev", "aov", "orders", "customers"],
        rows=[[50000.0, 100.0, 500, 200]],
        row_count=1,
    )

    # Prior week: $10,000 revenue / 100 orders / 80 customers.
    # Latest week: $15,000 revenue / 120 orders / 90 customers -> all up WoW.
    rows2 = [
        [date(2023, 1, 1), 9800.0, 98, 79],
        [date(2023, 1, 8), 9900.0, 99, 80],
        [date(2023, 1, 15), 10000.0, 100, 80],
        [date(2023, 1, 22), 15000.0, 120, 90],
    ]
    payload2 = ResultPayload(
        columns=["order_week", "weekly_revenue", "weekly_orders", "weekly_customers"],
        rows=rows2,
        row_count=len(rows2),
    )
    mock_warehouse.execute_readonly = AsyncMock(side_effect=[(payload1, 10), (payload2, 10)])

    briefing = await generate_morning_briefing(
        tenant_id, settings, user_name="Exec Test", warehouse=mock_warehouse
    )

    revenue_kpi = briefing.kpis[0]
    orders_kpi = briefing.kpis[3]
    assert revenue_kpi.change_pct == 50.0
    assert revenue_kpi.trend == "up"
    assert "vs. the prior week" in revenue_kpi.insight
    assert orders_kpi.change_pct == 20.0
    assert orders_kpi.trend == "up"
