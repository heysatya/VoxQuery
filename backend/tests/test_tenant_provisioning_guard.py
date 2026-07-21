"""
Tests for the tenant-provisioning guard on POST /api/session.

Verifies:
  1. A tenant with no is_provisioned() method on the warehouse (e.g. tests'
     FakeWarehouseConnector, or dev-mode SnowflakeWarehouseConnector) is
     unaffected — the guard is a true no-op, session creation proceeds as before.
  2. A tenant whose warehouse reports is_provisioned() == True can create a session.
  3. A tenant whose warehouse reports is_provisioned() == False is rejected with
     ErrorCode.tenant_not_provisioned before a session is ever created.
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
TENANT_ID = "00000000-0000-0000-0000-000000000101"


class _AlwaysProvisioned:
    async def is_provisioned(self, tenant_id):
        return True


class _NeverProvisioned:
    async def is_provisioned(self, tenant_id):
        return False


@pytest.fixture(autouse=True)
def _restore_warehouse():
    """Every test in this file swaps app.state.pipeline.warehouse — restore it
    afterwards so other test modules aren't affected by test ordering."""
    original = app.state.pipeline.warehouse
    yield
    app.state.pipeline.warehouse = original


def test_guard_is_noop_when_warehouse_lacks_is_provisioned():
    """FakeWarehouseConnector (the default test double) has no is_provisioned
    method — the guard must not block or error in this case."""
    assert not hasattr(app.state.pipeline.warehouse, "is_provisioned")
    response = client.post("/api/session", json={"tenant_id": TENANT_ID})
    assert response.status_code == 201


def test_guard_allows_session_when_tenant_provisioned():
    app.state.pipeline.warehouse = _AlwaysProvisioned()
    response = client.post("/api/session", json={"tenant_id": TENANT_ID})
    assert response.status_code == 201
    body = response.json()
    assert "session_id" in body


def test_guard_blocks_session_when_tenant_not_provisioned():
    app.state.pipeline.warehouse = _NeverProvisioned()
    response = client.post("/api/session", json={"tenant_id": TENANT_ID})
    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "tenant_not_provisioned"
