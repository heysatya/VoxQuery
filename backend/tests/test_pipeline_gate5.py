from unittest.mock import MagicMock, AsyncMock
from app.services.pipeline import PipelineOrchestrator
from app.core.session import InMemorySessionStore
from app.services.events import PipelineEventBus
from app.audit.store import AuditStore
import uuid
import pytest
from unittest.mock import patch
from app.models.contracts import AuthClaims, QueryRequest, SchemaChunk, ResultPayload, ResultShape, ChartType
import asyncio
def test_pipeline_injects_audit_store():
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)
    
    pipeline = PipelineOrchestrator(sessions, events, audit)
    assert pipeline.audit == audit

@pytest.mark.asyncio
async def test_pipeline_enqueues_turn_with_identity():
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)
    
    pipeline = PipelineOrchestrator(sessions, events, audit)
    claims = AuthClaims(user_id=uuid.uuid4(), tenant_id=uuid.uuid4())
    session, _ = sessions.create(claims)
    req = QueryRequest(session_id=session.session_id, submitted_text="hello", input_modality="text")
    
    chunk = SchemaChunk(content="chunk", source_ref="ref", similarity=0.9)
    
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
    
    with patch("app.services.graph.detect_ambiguity") as mock_detect, \
         patch("app.services.graph.compute_confidence") as mock_conf:
         
        mock_detect.return_value = MagicMock(dominant_signal=None, signals_detected=[], ambiguous_terms=[])
        mock_conf.return_value = MagicMock(clarification_triggered=False, confidence_tier="High", composite_score=0.9)
        
        turn = await pipeline.submit_query(req, claims)
        
        # Poll instead of static sleep to avoid flaky test
        for _ in range(10):
            if turn.completed:
                break
            await asyncio.sleep(0.1)
    
    assert turn.completed is True
    audit.enqueue_turn.assert_called_once()
    args = audit.enqueue_turn.call_args[0]
    assert args[0] == turn
    assert args[1].email == "local-user@voxquery.test"
    assert args[2] is None # no clarification


@pytest.mark.asyncio
async def test_pipeline_resolves_ambiguity_with_actual_term():
    sessions = InMemorySessionStore()
    events = PipelineEventBus()
    audit = MagicMock(spec=AuditStore)
    
    pipeline = PipelineOrchestrator(sessions, events, audit)
    claims = AuthClaims(user_id=uuid.uuid4(), tenant_id=uuid.uuid4())
    session, _ = sessions.create(claims)
    req = QueryRequest(session_id=session.session_id, submitted_text="hello", input_modality="text")
    
    chunk = SchemaChunk(content="chunk", source_ref="ref", similarity=0.5)
    
    from app.llm.adapter import SqlGenerationResult
    from app.models.contracts import ClarificationResolutionType, ResultPayload, ResultShape, ChartType
    
    pipeline.schema = MagicMock()
    pipeline.schema.retrieve = AsyncMock(return_value=([chunk], 0.5))
    pipeline.warehouse = MagicMock()
    result = ResultPayload(columns=[], rows=[], row_count=0)
    shape = ResultShape(columns=[], chart_type=ChartType.stat, row_count=0, aggregate_summary="")
    pipeline.warehouse.execute_readonly = AsyncMock(return_value=(result, shape))
    
    pipeline.llm = MagicMock()
    generation = SqlGenerationResult(sql="SELECT 1", llm_self_confidence=0.5, validation_passed=True)
    pipeline.llm.generate_sql = AsyncMock(return_value=generation)
    pipeline.llm.generate_clarification = AsyncMock(return_value=("Could you clarify?", ["A", "B"]))
    
    with patch("app.services.graph.detect_ambiguity") as mock_detect, \
         patch("app.services.graph.compute_confidence") as mock_conf:
         
        mock_detect.return_value = MagicMock(dominant_signal="entity_ambiguity", signals_detected=["entity_ambiguity"], ambiguous_terms=["customer_segment"])
        mock_conf.return_value = MagicMock(clarification_triggered=True, confidence_tier="Low", composite_score=0.4)
        
        turn = await pipeline.submit_query(req, claims)
        
        for _ in range(10):
            if turn.clarification_triggered:
                break
            await asyncio.sleep(0.1)
    
        assert turn.clarification_triggered is True
        
    await pipeline.resolve_clarification(
        session_id=session.session_id,
        turn_id=turn.turn_id,
        selection="A",
        resolution_type=ClarificationResolutionType.option_selected,
        claims=claims
    )
    
    for _ in range(10):
        if "customer_segment" in session.resolved_entities and turn.completed:
            break
        await asyncio.sleep(0.1)
    
    assert "customer_segment" in session.resolved_entities
    assert session.resolved_entities["customer_segment"].option_selected == "A"
    assert "revenue" not in session.resolved_entities
    assert turn.completed is True
    audit.enqueue_turn.assert_called_once()
    clarification = audit.enqueue_turn.call_args[0][2]
    assert clarification.prompt_sent == "Could you clarify?"
    assert clarification.user_choice == "A"
    assert clarification.resolution_type == ClarificationResolutionType.option_selected
