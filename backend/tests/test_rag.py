import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.rag.pgvector import PgVectorSchemaRetriever
from app.rag.query_rewriter import RewrittenQuery


@pytest.fixture
def mock_openai():
    mock_client = AsyncMock()

    # Mock the embedding response structure
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]
    mock_client.embeddings.create.return_value = mock_response

    return mock_client


@pytest.fixture
def mock_db_pool():
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    # Setup async context manager for pool.acquire()
    mock_acquire_ctx = AsyncMock()
    mock_acquire_ctx.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value = mock_acquire_ctx

    # Mock fetch to return dummy chunk rows
    mock_conn.fetch.return_value = [
        {
            "source_ref": "snowflake://ORDERS.AMOUNT",
            "content": "Table: ORDERS, Column: AMOUNT (Type: NUMBER)",
            "entity_type": "column",
            "table_name": "ORDERS",
            "column_name": "AMOUNT",
            "similarity": 0.95,
        },
        {
            "source_ref": "snowflake://ORDERS",
            "content": "Table: ORDERS",
            "entity_type": "table",
            "table_name": "ORDERS",
            "column_name": None,
            "similarity": 0.85,
        },
    ]

    return mock_pool


@pytest.mark.asyncio
async def test_pgvector_retriever_success(mock_openai, mock_db_pool):
    """
    BEHAVIOR: The retriever should embed the user input and fetch the top matching schema chunks from the database.
    SPEC: PgVectorSchemaRetriever.retrieve(rewritten_query, tenant_id) -> tuple[list[SchemaChunk], float]
    """
    retriever = PgVectorSchemaRetriever(openai_client=mock_openai, db_pool=mock_db_pool)
    tenant_id = uuid4()
    rewritten = RewrittenQuery(
        original="Show me total revenue",
        rewritten="Show me total revenue",
    )

    chunks, score = await retriever.retrieve(rewritten, tenant_id)

    # Assert OpenAI was called to generate the embedding
    mock_openai.embeddings.create.assert_called_once_with(
        input="Show me total revenue", model="text-embedding-3-small"
    )

    # Assert we returned the correct chunks
    assert len(chunks) == 2
    assert chunks[0].table == "ORDERS"
    assert chunks[0].column == "AMOUNT"
    assert chunks[0].similarity == 0.95

    # Assert the RAG score is derived from the RRF calculation
    assert score == 1.0


@pytest.mark.asyncio
async def test_pgvector_retriever_empty(mock_openai, mock_db_pool):
    """
    BEHAVIOR: The retriever should handle gracefully when no chunks are found (e.g., empty db).
    """
    # Override the mock connection to return no rows
    mock_conn = mock_db_pool.acquire.return_value.__aenter__.return_value
    mock_conn.fetch.return_value = []

    retriever = PgVectorSchemaRetriever(openai_client=mock_openai, db_pool=mock_db_pool)
    rewritten = RewrittenQuery(original="random words", rewritten="random words")

    chunks, score = await retriever.retrieve(rewritten, uuid4())

    assert len(chunks) == 0
    assert score == 0.0
