"""
test_api.py
───────────
FastAPI endpoint tests using TestClient.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from app.metadata.models import (
    ChunkType, ChunkMetadata, ContextBundle, ContextSection, RagChunk, RetrievedChunk
)
from app.retrieval.hybrid_retriever import RetrievalResult
from app.retrieval.query_rewriter import RewrittenQuery


def make_mock_retrieval_result(query: str) -> RetrievalResult:
    """Build a mock RetrievalResult for testing."""
    chunk = RagChunk(
        chunk_type=ChunkType.METRIC_CARD,
        text="Metric: Revenue [CERTIFIED]\nFormula: SUM(order_total)\nSynonyms: sales",
        metadata=ChunkMetadata(metric="revenue", certified=True),
    )
    retrieved = RetrievedChunk(chunk=chunk, score=0.95, source="hybrid")

    return RetrievalResult(
        query=query,
        rewritten_query=RewrittenQuery(original=query, rewritten=query),
        chunks=[retrieved],
        vector_candidates=10,
        bm25_candidates=10,
        fused_candidates=10,
        returned_chunks=1,
        latency_ms=120.5,
    )


def make_mock_bundle() -> ContextBundle:
    """Build a mock ContextBundle."""
    return ContextBundle(
        context=ContextSection(
            metrics=[
                "⭐ Metric: Revenue [CERTIFIED]\nFormula: SUM(order_total)"],
            tables=["Table: main.ORDERS\nColumns: order_id, order_total"],
            examples=[],
            business_rules=["Always filter WHERE order_status = 'delivered'"],
        ),
        total_tokens=450,
        chunks_used=[
            {"id": "abc", "type": "metric_card", "score": 0.95, "metadata": {}}
        ],
    )


@pytest.fixture
def client():
    """
    TestClient with mocked retriever and context builder.
    This avoids needing real index files for API tests.
    """
    from app.main import app, app_state
    from app.retrieval.hybrid_retriever import HybridRetriever
    from app.retrieval.context_builder import ContextBuilder

    # Mock retriever
    mock_retriever = MagicMock(spec=HybridRetriever)
    mock_retriever._vector_store = MagicMock(is_empty=False, num_chunks=50)
    mock_retriever._bm25_index = MagicMock(is_empty=False, num_chunks=50)
    mock_retriever._embedder = MagicMock(provider_name="mock")
    mock_retriever.get_stats.return_value = {"loaded": True}

    def fake_retrieve(query, config=None, **kwargs):
        return make_mock_retrieval_result(query)

    mock_retriever.retrieve.side_effect = fake_retrieve

    # Mock context builder
    mock_builder = MagicMock(spec=ContextBuilder)
    mock_builder.build.return_value = make_mock_bundle()

    # Inject mocks into app state
    app_state.retriever = mock_retriever
    app_state.context_builder = mock_builder
    app_state.is_ready = True
    app_state.startup_error = None

    with TestClient(app) as c:
        yield c


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_shows_index_status(self, client):
        data = response = client.get("/health").json()
        assert "indexes" in data
        assert "status" in data


class TestRetrieveEndpoint:
    def test_basic_retrieve(self, client):
        response = client.post("/retrieve", json={
            "query": "What was revenue last quarter?",
            "top_k": 10,
            "token_budget": 2500,
        })
        assert response.status_code == 200
        data = response.json()
        assert "context" in data
        assert "total_tokens" in data
        assert "chunks_used" in data
        assert "retrieval_metadata" in data

    def test_retrieve_returns_query_echo(self, client):
        query = "Show me top 5 products by sales"
        response = client.post("/retrieve", json={"query": query})
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == query

    def test_retrieve_empty_query_returns_422(self, client):
        response = client.post("/retrieve", json={"query": ""})
        assert response.status_code == 422

    def test_retrieve_query_too_long_returns_422(self, client):
        response = client.post("/retrieve", json={"query": "x" * 1001})
        assert response.status_code == 422

    def test_retrieve_invalid_top_k_returns_422(self, client):
        response = client.post("/retrieve", json={
            "query": "revenue?",
            "top_k": 0,  # below minimum of 1
        })
        assert response.status_code == 422

    def test_retrieve_with_domain_filter(self, client):
        response = client.post("/retrieve", json={
            "query": "top products",
            "domain_filter": "products",
        })
        assert response.status_code == 200

    def test_retrieve_context_has_sections(self, client):
        response = client.post("/retrieve", json={
            "query": "revenue by region"
        })
        data = response.json()
        ctx = data["context"]
        assert "tables" in ctx
        assert "metrics" in ctx
        assert "examples" in ctx
        assert "business_rules" in ctx

    def test_retrieve_metadata_has_latency(self, client):
        response = client.post("/retrieve", json={"query": "total orders"})
        data = response.json()
        meta = data["retrieval_metadata"]
        assert "latency_ms" in meta
        assert meta["latency_ms"] >= 0

    def test_service_not_ready_returns_503(self):
        """Test 503 when service is not initialized."""
        from app.main import app, app_state
        app_state.is_ready = False

        with TestClient(app) as c:
            response = c.post("/retrieve", json={"query": "revenue?"})
            assert response.status_code == 503

        app_state.is_ready = True  # Reset


class TestRootEndpoint:
    def test_root_returns_info(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "docs" in data
