import pytest
from unittest.mock import AsyncMock, MagicMock
from app.llm.claude import ClaudeAdapter

@pytest.fixture
def mock_anthropic_client():
    client = MagicMock()
    # Ensure messages.create is an async mock that returns a mock response
    create_mock = AsyncMock()
    response_mock = MagicMock()
    # The text should be valid JSON
    response_mock.content = [MagicMock(text='{"question": "Which revenue?", "options": ["Gross", "Net"]}')]
    create_mock.return_value = response_mock
    client.messages.create = create_mock
    return client

@pytest.mark.asyncio
async def test_generate_clarification_parses_json(mock_anthropic_client):
    adapter = ClaudeAdapter(mock_anthropic_client)
    question, options = await adapter.generate_clarification("revenue")
    
    # Assert JSON was parsed correctly
    assert question == "Which revenue?"
    assert options == ["Gross", "Net"]
    
    # Assert the anthropic client was called with correct structure
    mock_anthropic_client.messages.create.assert_awaited_once()
    call_args = mock_anthropic_client.messages.create.call_args[1]
    assert call_args["model"] == adapter.model_name
    assert "revenue" in call_args["messages"][0]["content"]

@pytest.mark.asyncio
async def test_generate_clarification_fallback_on_bad_json(mock_anthropic_client):
    # Setup bad JSON response
    mock_anthropic_client.messages.create.return_value.content[0].text = "Here are your options: 1. Gross, 2. Net"
    
    adapter = ClaudeAdapter(mock_anthropic_client)
    question, options = await adapter.generate_clarification("revenue")
    
    # It should fallback to a safe default
    assert question == "Could you clarify regarding revenue?"
    assert options == ["Option A", "Option B", "Skip"]
