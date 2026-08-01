"""
Tests for Cross-Session Memory API and Repository (Wave 3.1).
"""

import pytest
from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app
from app.models.contracts import AuthClaims
from app.repositories.turn_repository import TurnRepository

client = TestClient(app)


def test_prior_session_summary_api_endpoint():
    response = client.get(
        "/api/memory/prior-session-summary",
        headers={
            "X-Fake-User-Id": "00000000-0000-0000-0000-000000000001",
            "X-Fake-Tenant-Id": "00000000-0000-0000-0000-000000000101",
            "X-Fake-Role": "admin",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "questions" in data
    assert isinstance(data["questions"], list)
