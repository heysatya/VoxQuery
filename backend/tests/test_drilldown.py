"""
Tests for Row-Level Metric Drilldown Service and API (PRD Feature 4).
"""

import pytest
from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app
from app.config import get_settings
from app.services.drilldown import get_row_drilldown

client = TestClient(app)


@pytest.mark.asyncio
async def test_get_row_drilldown_service():
    settings = get_settings()
    turn_id = uuid4()
    rows = await get_row_drilldown(turn_id, settings)
    
    assert len(rows) > 0
    assert "order_id" in rows[0]
    assert "amount" in rows[0]


def test_drilldown_api_endpoint():
    turn_id = uuid4()
    response = client.get(
        f"/api/drilldown/{turn_id}",
        headers={
            "X-Fake-User-Id": "00000000-0000-0000-0000-000000000001",
            "X-Fake-Tenant-Id": "00000000-0000-0000-0000-000000000101",
            "X-Fake-Role": "admin",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert data[0]["order_id"].startswith("ORD-2026-")
