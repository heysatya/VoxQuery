import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from svix.webhooks import Webhook

from app.main import app

client = TestClient(app)

@pytest.fixture
def mock_svix():
    with patch("svix.webhooks.Webhook.verify") as mock_verify:
        with patch.dict("os.environ", {"CLERK_WEBHOOK_SECRET": "test_secret", "CLERK_SECRET_KEY": "test_key"}):
            yield mock_verify

@pytest.fixture(autouse=True)
def mock_db_pool():
    # Mock the Depends(get_db_pool) using FastAPI dependency_overrides
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
    yield mock_pool
    app.dependency_overrides.clear()

@pytest.fixture
def mock_httpx_patch():
    with patch("httpx.AsyncClient.patch") as mock_patch:
        yield mock_patch


def test_webhook_missing_signature():
    response = client.post("/api/webhooks/clerk", json={})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_organization_created_webhook(mock_svix, mock_httpx_patch):
    # Simulate a successful Svix verification
    mock_svix.return_value = {
        "type": "organization.created",
        "data": {
            "id": "org_123",
            "name": "Test Org"
        }
    }
    
    headers = {
        "svix-id": "msg_123",
        "svix-timestamp": "1234567890",
        "svix-signature": "v1,signature"
    }
    
    response = client.post("/api/webhooks/clerk", json={"data": {}}, headers=headers)
    
    # Assert successful processing
    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    
    # Assert httpx patch was called
    mock_httpx_patch.assert_called()


@pytest.mark.asyncio
async def test_user_created_webhook(mock_svix, mock_httpx_patch):
    # Simulate a successful Svix verification
    mock_svix.return_value = {
        "type": "user.created",
        "data": {
            "id": "user_456",
            "email_addresses": [{"email_address": "test@example.com"}],
            "primary_email_address_id": "em_123"
        }
    }
    
    headers = {
        "svix-id": "msg_123",
        "svix-timestamp": "1234567890",
        "svix-signature": "v1,signature"
    }
    
    response = client.post("/api/webhooks/clerk", json={"data": {}}, headers=headers)
    
    assert response.status_code == 200
    assert response.json() == {"status": "success"}
