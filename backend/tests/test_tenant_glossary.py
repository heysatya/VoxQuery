import asyncio
import json
from uuid import uuid4
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.graph import rewrite_query_node
from app.models.contracts import TurnRecord

@pytest.fixture
def mock_db_pool():
    return MagicMock()

@pytest.mark.asyncio
async def test_arch_1_tenant_glossary_override(mock_db_pool):
    """ARCH-1: Make the business glossary tenant-configurable."""
    
    tenant_id = uuid4()
    turn = TurnRecord(
        session_id=uuid4(),
        conversation_id=uuid4(),
        user_id=uuid4(),
        tenant_id=tenant_id,
        user_input="Show me ARR by GEO",
        input_modality="text",
    )
    
    # State with DB pool injected
    state = {
        "turn": turn,
        "db_pool": mock_db_pool
    }
    
    mock_conn = AsyncMock()
    # Mock row returning custom synonyms for this tenant: canonical -> [synonyms]
    mock_conn.fetchrow.return_value = {
        "metric_synonyms": json.dumps({"annual_recurring_revenue": ["arr"]}),
        "table_synonyms": json.dumps({"geography": ["geo"]})
    }
    
    class MockAcquireContext:
        async def __aenter__(self): return mock_conn
        async def __aexit__(self, exc_type, exc, tb): pass
        
    mock_db_pool.acquire.return_value = MockAcquireContext()
    
    # Run the node
    result = await rewrite_query_node(state)
    
    mock_conn.fetchrow.assert_called_once_with(
        "SELECT metric_synonyms, table_synonyms FROM tenant_glossary WHERE tenant_id = $1::uuid",
        tenant_id
    )
    
    # Assert query rewriter picked up the synonyms
    assert "annual_recurring_revenue" in result["rewritten_query"].detected_metrics
    assert "geography" in result["rewritten_query"].detected_tables

@pytest.mark.asyncio
async def test_arch_1_tenant_glossary_fallback(mock_db_pool):
    """ARCH-1: Assert an unconfigured tenant still gets the current hardcoded defaults."""
    tenant_id = uuid4()
    turn = TurnRecord(
        session_id=uuid4(),
        conversation_id=uuid4(),
        user_id=uuid4(),
        tenant_id=tenant_id,
        user_input="revenue", # A term that exists in the default/fallback glossary
        input_modality="text",
    )
    
    state = {
        "turn": turn,
        "db_pool": mock_db_pool
    }
    
    mock_conn = AsyncMock()
    # Tenant not found in tenant_glossary
    mock_conn.fetchrow.return_value = None
    
    class MockAcquireContext:
        async def __aenter__(self): return mock_conn
        async def __aexit__(self, exc_type, exc, tb): pass
        
    mock_db_pool.acquire.return_value = MockAcquireContext()
    
    # Run the node
    with patch("app.rag.query_rewriter.QueryRewriter") as MockRewriter:
        mock_rewriter_instance = MockRewriter.return_value
        mock_rewriter_instance.rewrite.return_value = "gross_revenue"
        
        result = await rewrite_query_node(state)
        
        # Ensure it was instantiated with None/empty (which triggers default fallback in the class)
        MockRewriter.assert_called_once_with(metric_synonyms=None, table_synonyms=None)
        assert result["rewritten_query"] == "gross_revenue"
