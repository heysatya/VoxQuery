import pytest
from httpx import ASGITransport, AsyncClient
from uuid import uuid4

from app.main import app
from app.models.contracts import AuthClaims
from app.middleware.auth import get_current_user

class FakePipeline:
    def __init__(self):
        self.commands = []
        self._counts = {}
        self._ttls = {}
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc, tb):
        pass
        
    def incr(self, key):
        self.commands.append(("incr", key))
        
    def ttl(self, key):
        self.commands.append(("ttl", key))
        
    async def execute(self):
        results = []
        for cmd, key in self.commands:
            if cmd == "incr":
                self._counts[key] = self._counts.get(key, 0) + 1
                results.append(self._counts[key])
            elif cmd == "ttl":
                results.append(self._ttls.get(key, -1))
        self.commands = []
        return results

class FakeRedis:
    def __init__(self):
        self.pipe = FakePipeline()
        
    def pipeline(self):
        return self.pipe
        
    async def expire(self, key, seconds):
        self.pipe._ttls[key] = seconds
        
"""
### PROD-1: Rate Limiting
**Behavior spec:**
Given a user has made N requests to `/api/query` within a rolling window, 
when they exceed the configured limit (20 per minute), 
then subsequent requests are rejected with a 429 and a `retry_after` hint, until the window resets.
"""

@pytest.mark.asyncio
async def test_rate_limit_enforcement():
    dummy_user = str(uuid4())
    dummy_tenant = str(uuid4())
    
    async def mock_get_current_user():
        return AuthClaims(user_id=dummy_user, tenant_id=dummy_tenant, snowflake_role="viewer")
    
    # We apply the dependency override on the app
    app.dependency_overrides[get_current_user] = mock_get_current_user
    
    original_client = app.state.rate_limiter.client
    app.state.rate_limiter.client = FakeRedis()
    
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # We first need a session id
            session_resp = await client.post(
                "/api/session",
                json={"tenant_id": str(dummy_tenant)}
            )
            assert session_resp.status_code == 201
            session_id = session_resp.json()["session_id"]
            
            limit = app.state.rate_limiter.max_requests_per_window
            for i in range(limit):
                resp = await client.post(
                    "/api/query",
                    json={"session_id": session_id, "submitted_text": f"test query {i}"},
                )
                assert resp.status_code != 429
                
            # The next request should be rate-limited
            resp = await client.post(
                "/api/query",
                json={"session_id": session_id, "submitted_text": "test query overflow"},
            )
            assert resp.status_code == 429
            data = resp.json()
            assert "error" in data
            assert data["error"]["code"] == "rate_limit_exceeded"
            assert "Retry after" in data["error"]["detail"]
    finally:
        app.dependency_overrides.clear()
        app.state.rate_limiter.client = original_client
