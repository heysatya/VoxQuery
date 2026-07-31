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
    tenant_id = uuid4()
    briefing = await generate_morning_briefing(tenant_id, settings, user_name="Executive Test")
    
    assert briefing.date is not None
    assert "Executive Briefing" in briefing.greeting
    assert len(briefing.kpis) >= 3
    assert len(briefing.anomalies) >= 1
    assert len(briefing.proactive_insights) >= 2
    assert "$246.7M" in briefing.summary_narrative


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
