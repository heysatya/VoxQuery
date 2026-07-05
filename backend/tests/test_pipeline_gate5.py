from unittest.mock import MagicMock, AsyncMock
from app.services.pipeline import PipelineOrchestrator
from app.core.session import InMemorySessionStore
from app.services.events import PipelineEventBus
from app.audit.store import AuditStore

def test_pipeline_injects_audit_store():
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)
    
    pipeline = PipelineOrchestrator(sessions, events, audit)
    assert pipeline.audit == audit

import uuid
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.models.contracts import AuthClaims, TurnRecord, QueryRequest, SchemaChunk, ResultPayload, ResultShape, ChartType
import asyncio

@pytest.mark.asyncio
async def test_pipeline_enqueues_turn_with_identity():
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)
    
    pipeline = PipelineOrchestrator(sessions, events, audit)
    claims = AuthClaims(user_id=uuid.uuid4(), tenant_id=uuid.uuid4())
    session, _ = sessions.create(claims)
    req = QueryRequest(session_id=session.session_id, submitted_text="hello", input_modality="text")
    
    chunk = SchemaChunk(content="chunk", source_ref="ref", score=0.9, table_name="t")
    
    from app.llm.adapter import SqlGenerationResult
    
    # Mock RAG/Confidence/Snowflake so it completes
    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=([chunk], 0.9))
    pipeline.warehouse = MagicMock()
    result = ResultPayload(columns=[], rows=[], row_count=0)
    shape = ResultShape(columns=[], chart_type=ChartType.stat, row_count=0, aggregate_summary="")
    pipeline.warehouse.execute_readonly = AsyncMock(return_value=(result, shape))
    pipeline.llm = MagicMock()
    generation = SqlGenerationResult(sql="SELECT 1", llm_self_confidence=0.9, validation_passed=True)
    pipeline.llm.generate_sql = AsyncMock(return_value=generation)
    
    turn = await pipeline.submit_query(req, claims)
    await asyncio.sleep(0.1) # let background task finish
    
    assert turn.completed is True
    audit.enqueue_turn.assert_called_once()
    args = audit.enqueue_turn.call_args[0]
    assert args[0] == turn
    assert args[1].email == "local-user@voxquery.test"
    assert args[2] is None # no clarification

@pytest.mark.asyncio
async def test_pipeline_timeout_enqueues_clarification():
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)
    
    pipeline = PipelineOrchestrator(sessions, events, audit)
    claims = AuthClaims(user_id=uuid.uuid4(), tenant_id=uuid.uuid4())
    session, _ = sessions.create(claims)
    req = QueryRequest(session_id=session.session_id, submitted_text="hello", input_modality="text")
    
    chunk = SchemaChunk(content="chunk", source_ref="ref", score=0.5, table_name="t")
    
    from app.llm.adapter import SqlGenerationResult
    
    # Mock to force clarification
    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=([chunk], 0.5))
    pipeline.llm = MagicMock()
    generation = SqlGenerationResult(sql="SELECT 1", llm_self_confidence=0.5, validation_passed=True)
    pipeline.llm.generate_sql = AsyncMock(return_value=generation)
    
    with patch("app.services.pipeline.detect_ambiguity") as mock_detect, \
         patch("app.services.pipeline.compute_confidence") as mock_conf:
         
        mock_detect.return_value = MagicMock(dominant_signal="test", signals_detected=True)
        mock_conf.return_value = MagicMock(clarification_triggered=True, confidence_tier="low", composite_score=0.4)
        
        turn = await pipeline.submit_query(req, claims)
        await asyncio.sleep(0.1)
    
        assert turn.completed is False
        assert turn.clarification_triggered is True
    
    # Force timeout
    await pipeline.force_timeout(req.session_id, claims)
    
    # enqueue_turn should now be called with clarification
    audit.enqueue_turn.assert_called_once()
    args = audit.enqueue_turn.call_args[0]
    assert args[0] == turn
    assert args[2].resolution_type == "timeout"
