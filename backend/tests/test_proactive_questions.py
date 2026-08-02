import asyncio
import pytest
from unittest.mock import AsyncMock

from app.services.result_contracts import derive_proactive_questions
from app.models.contracts import TurnRecord, ResultPayload


@pytest.mark.asyncio
async def test_feat_1_proactive_questions_generation():
    """FEAT-1: Generate proactive questions for a given result shape."""

    # We will test the deterministic rule-based generator from result_contracts.py

    turn = TurnRecord(
        session_id="00000000-0000-0000-0000-000000000000",
        conversation_id="00000000-0000-0000-0000-000000000000",
        user_id="00000000-0000-0000-0000-000000000000",
        tenant_id="00000000-0000-0000-0000-000000000000",
        user_input="Show me revenue by segment",
        input_modality="text",
    )

    result = ResultPayload(
        columns=["customer_segment", "total_revenue"],
        rows=[["Enterprise", 500000], ["SMB", 100000]],
        row_count=2,
        chart_type="bar",
    )

    questions = derive_proactive_questions(turn, result)

    assert len(questions) > 0
    assert len(questions) <= 3

    # Ensure they are valid strings
    for q in questions:
        assert isinstance(q, str)
        assert len(q) > 10
        # Should not duplicate the original query exactly
        assert q.lower() != turn.user_input.lower()
