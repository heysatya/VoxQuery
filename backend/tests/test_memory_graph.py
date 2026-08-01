"""
Tests for Executive Memory Graph API and Service (PRD V2.2 Feature 2).
"""

import pytest
from uuid import uuid4
from fastapi.testclient import TestClient

from app.main import app
from app.config import get_settings
from app.services.memory_graph import generate_memory_graph

client = TestClient(app)


@pytest.mark.asyncio
async def test_generate_memory_graph_service():
    settings = get_settings()
    session_id = uuid4()
    sample_turns = [
        {
            "user_input": "Total Revenue 2025",
            "chart_type": "bar",
            "source_tables": ["orders"],
            "filter_predicates": ["state = 'CA'"],
        }
    ]
    graph = await generate_memory_graph(session_id, settings, turns=sample_turns)
    
    assert graph.session_id == session_id
    assert len(graph.nodes) >= 2
    assert len(graph.edges) >= 1
    types = {node.type for node in graph.nodes}
    assert "query" in types
    assert "metric" in types


def test_memory_graph_api_endpoint():
    session_id = uuid4()
    response = client.get(
        f"/api/memory-graph/{session_id}",
        headers={
            "X-Fake-User-Id": "00000000-0000-0000-0000-000000000001",
            "X-Fake-Tenant-Id": "00000000-0000-0000-0000-000000000101",
            "X-Fake-Role": "admin",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data
    assert isinstance(data["nodes"], list)
