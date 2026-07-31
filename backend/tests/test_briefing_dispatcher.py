from unittest.mock import AsyncMock, MagicMock
import pytest
from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app
from app.api.rest import get_db_pool
from app.config import get_settings
from app.models.contracts import ExecutiveBriefingResponse, BriefingKpi, UserPreferences
from app.services.briefing_dispatcher import dispatch_briefing_email

client = TestClient(app)


@pytest.mark.asyncio
async def test_dispatch_briefing_email_service():
    settings = get_settings()
    user_id = str(uuid4())
    briefing = ExecutiveBriefingResponse(
        date="2026-07-22",
        greeting="Good morning, Test Executive",
        kpis=[
            BriefingKpi(
                label="Revenue",
                value="$1.2M",
                change_pct=4.2,
                trend="up",
                insight="Steady performance",
            )
        ],
        summary_narrative="The business is doing well.",
        anomalies=[],
        proactive_insights=["Check store sales"],
    )

    success = await dispatch_briefing_email(
        user_id, "exec@test.com", briefing, settings
    )
    assert success is True


def test_user_preferences_api_endpoints():
    mock_pool = MagicMock()
    app.dependency_overrides[get_db_pool] = lambda: mock_pool
    try:
        from unittest.mock import patch
        with patch("app.services.preferences.get_user_preferences", new_callable=AsyncMock) as mock_get, \
             patch("app.services.preferences.update_user_preferences", new_callable=AsyncMock) as mock_update:
            mock_get.return_value = UserPreferences(
                user_id="00000000-0000-0000-0000-000000000001",
                email_briefing_enabled=False,
                email=None,
                delivery_time="09:00",
                timezone="UTC",
            )
            mock_update.return_value = UserPreferences(
                user_id="00000000-0000-0000-0000-000000000001",
                email_briefing_enabled=True,
                email="executive@company.com",
                delivery_time="07:30",
                timezone="UTC",
            )

            # GET preferences
            response = client.get(
                "/api/preferences",
                headers={
                    "X-Fake-User-Id": "00000000-0000-0000-0000-000000000001",
                    "X-Fake-Tenant-Id": "00000000-0000-0000-0000-000000000101",
                    "X-Fake-Role": "admin",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["email_briefing_enabled"] is False

            # PATCH preferences
            response = client.patch(
                "/api/preferences",
                json={
                    "email_briefing_enabled": True,
                    "email": "executive@company.com",
                    "delivery_time": "07:30",
                },
                headers={
                    "X-Fake-User-Id": "00000000-0000-0000-0000-000000000001",
                    "X-Fake-Tenant-Id": "00000000-0000-0000-0000-000000000101",
                    "X-Fake-Role": "admin",
                },
            )
            assert response.status_code == 200
            updated_data = response.json()
            assert updated_data["email_briefing_enabled"] is True
            assert updated_data["email"] == "executive@company.com"
            assert updated_data["delivery_time"] == "07:30"
    finally:
        app.dependency_overrides.pop(get_db_pool, None)
