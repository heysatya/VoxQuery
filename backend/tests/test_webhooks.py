from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

@pytest.fixture
def mock_svix():
    with patch("svix.webhooks.Webhook.verify") as mock_verify:
        with patch.dict("os.environ", {"CLERK_WEBHOOK_SECRET": "test_secret", "CLERK_SECRET_KEY": "test_key"}):
            yield mock_verify

@pytest.fixture(autouse=True)
def mock_db_pool():
    from unittest.mock import MagicMock
    from app.api.webhooks import get_db_pool
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    class AsyncContextManagerMock:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_pool.acquire.return_value = AsyncContextManagerMock()
    app.dependency_overrides[get_db_pool] = lambda: mock_pool
    yield mock_pool, mock_conn
    app.dependency_overrides.clear()


def test_webhook_missing_signature():
    response = client.post("/api/webhooks/clerk", json={})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_organization_created_webhook(mock_svix, mock_db_pool):
    _, mock_conn = mock_db_pool
    mock_svix.return_value = {
        "type": "organization.created",
        "data": {
            "id": "org_test123",
            "name": "Test Org"
        }
    }
    headers = {"svix-id": "msg_123", "svix-timestamp": "1234567890", "svix-signature": "v1,signature"}

    response = client.post("/api/webhooks/clerk", json={"data": {}}, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    assert mock_conn.execute.call_count >= 2


@pytest.mark.asyncio
async def test_organization_membership_created_webhook(mock_svix, mock_db_pool):
    _, mock_conn = mock_db_pool
    mock_svix.return_value = {
        "type": "organizationMembership.created",
        "data": {
            "organization": {"id": "org_test123"},
            "public_user_data": {
                "user_id": "user_test123",
                "identifier": "member@example.com"
            },
            "role": "org:admin",
            "permissions": ["org:admin:read"]
        }
    }
    headers = {"svix-id": "msg_124", "svix-timestamp": "1234567890", "svix-signature": "v1,signature"}

    response = client.post("/api/webhooks/clerk", json={"data": {}}, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    assert mock_conn.execute.call_count >= 2


@pytest.mark.asyncio
async def test_user_created_webhook_does_not_create_tenant(mock_svix, mock_db_pool):
    _, mock_conn = mock_db_pool
    mock_svix.return_value = {
        "type": "user.created",
        "data": {
            "id": "user_456",
            "email_addresses": [{"email_address": "test@example.com"}],
        }
    }
    headers = {"svix-id": "msg_125", "svix-timestamp": "1234567890", "svix-signature": "v1,signature"}

    response = client.post("/api/webhooks/clerk", json={"data": {}}, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"status": "success"}

    # Assert users table upsert was executed, but tenants table insert was NOT
    calls = [str(call) for call in mock_conn.execute.mock_calls]
    assert any("INSERT INTO users" in call for call in calls)
    assert not any("INSERT INTO tenants" in call for call in calls)


@pytest.mark.asyncio
async def test_user_deleted_webhook_deactivates_user_and_memberships(mock_svix, mock_db_pool):
    _, mock_conn = mock_db_pool
    mock_svix.return_value = {
        "type": "user.deleted",
        "data": {"id": "user_456"}
    }
    headers = {"svix-id": "msg_126", "svix-timestamp": "1234567890", "svix-signature": "v1,signature"}

    response = client.post("/api/webhooks/clerk", json={"data": {}}, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    assert mock_conn.execute.call_count >= 2
