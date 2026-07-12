"""
test_index_pipeline.py
───────────────────────
Integration tests for Phase 2 indexing pipeline.
Uses in-memory DuckDB + real chunking + mocked embeddings.
"""

from __future__ import annotations

import pytest
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.duckdb_connector.connection import DuckDBConnectionManager
from app.indexing.embedder import LocalBGEEmbedder, CachedEmbedder
from app.indexing.vector_store import FAISSVectorStore
from app.indexing.keyword_index import BM25Index
from app.indexing.index_pipeline import IndexPipeline, IndexingResult
from app.metadata.models import RagChunk, ChunkType


# ─────────────────────────────────────────────────────────────────────
# Mock Embedder (No API key needed)
# ─────────────────────────────────────────────────────────────────────


class MockEmbedder:
    """Fast mock embedder that returns random normalized vectors."""

    def __init__(self, dim: int = 64):
        self._dimension = dim

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def provider_name(self) -> str:
        return "mock"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return deterministic vectors based on text hash."""
        results = []
        for text in texts:
            rng = np.random.RandomState(hash(text) % (2**31))
            vec = rng.randn(self._dimension).astype(np.float32)
            vec = vec / np.linalg.norm(vec)
            results.append(vec.tolist())
        return results

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def sales_db(tmp_path_factory):
    """
    In-memory DuckDB with full sales schema from DBSchema_Sqls.docx.
    Uses a session-scoped temporary directory.
    """
    db_path = str(tmp_path_factory.mktemp("db") / "test.duckdb")
    mgr = DuckDBConnectionManager(db_path=db_path)

    with mgr.get_connection() as conn:
        conn.execute("""
            CREATE TABLE GEOLOCATION (
                zip_code_prefix  VARCHAR(20) PRIMARY KEY,
                geolocation_lat  DECIMAL(10,6),
                geolocation_lng  DECIMAL(10,6),
                geolocation_city VARCHAR(100),
                geolocation_state VARCHAR(50)
            )
        """)
        conn.execute("""
            CREATE TABLE CUSTOMERS (
                customer_id         INTEGER PRIMARY KEY,
                customer_unique_id  VARCHAR(100),
                customer_name       VARCHAR(150),
                customer_gender     VARCHAR(20),
                customer_age        INTEGER,
                customer_zip_code_prefix VARCHAR(20),
                customer_city       VARCHAR(100),
                customer_state      VARCHAR(50),
                customer_segment    VARCHAR(50)
            )
        """)
        conn.execute("""
            CREATE TABLE PRODUCTS (
                product_id            INTEGER PRIMARY KEY,
                product_category_name VARCHAR(100),
                product_name          VARCHAR(200),
                product_brand         VARCHAR(100),
                product_weight_g      INTEGER,
                product_length_cm     DECIMAL(10,2),
                product_height_cm     DECIMAL(10,2),
                product_width_cm      DECIMAL(10,2),
                cost                  DECIMAL(10,2),
                price                 DECIMAL(10,2)
            )
        """)
        conn.execute("""
            CREATE TABLE SELLERS (
                seller_id             INTEGER PRIMARY KEY,
                seller_company_name   VARCHAR(150),
                seller_contact_name   VARCHAR(150),
                seller_contact_gender VARCHAR(20),
                seller_contact_age    INTEGER,
                seller_zip_code_prefix VARCHAR(20),
                seller_city           VARCHAR(100),
                seller_state          VARCHAR(50)
            )
        """)
        conn.execute("""
            CREATE TABLE ORDERS (
                order_id                  INTEGER PRIMARY KEY,
                customer_id               INTEGER,
                order_status              VARCHAR(50),
                order_purchase_timestamp  TIMESTAMP,
                order_approved_at         TIMESTAMP,
                order_delivered_carrier_date TIMESTAMP,
                order_delivered_customer_date TIMESTAMP,
                order_estimated_delivery_date TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE ORDER_ITEMS (
                order_id          INTEGER,
                order_item_id     INTEGER,
                product_id        INTEGER,
                seller_id         INTEGER,
                shipping_limit_date TIMESTAMP,
                price             DECIMAL(10,2),
                freight_value     DECIMAL(10,2),
                discount_rate     DECIMAL(5,2),
                PRIMARY KEY (order_id, order_item_id)
            )
        """)
        conn.execute("""
            CREATE TABLE ORDER_PAYMENTS (
                order_id             INTEGER,
                payment_sequential   INTEGER,
                payment_type         VARCHAR(50),
                payment_installments INTEGER,
                payment_value        DECIMAL(10,2),
                PRIMARY KEY (order_id, payment_sequential)
            )
        """)
        conn.execute("""
            CREATE TABLE ORDER_REVIEWS (
                review_id             INTEGER PRIMARY KEY,
                order_id              INTEGER,
                review_score          INTEGER,
                review_comment_title  VARCHAR(255),
                review_comment_message TEXT,
                review_creation_date  TIMESTAMP,
                review_answer_timestamp TIMESTAMP
            )
        """)

        # Seed data
        conn.execute(
            "INSERT INTO GEOLOCATION VALUES ('10001', 40.748817, -73.985428, 'New York', 'NY')")
        conn.execute(
            "INSERT INTO CUSTOMERS VALUES (1, 'C001', 'Alice', 'Female', 34, '10001', 'New York', 'NY', 'Premium')")
        conn.execute(
            "INSERT INTO PRODUCTS VALUES (1, 'Electronics', 'Widget Pro', 'TechBrand', 500, 20.0, 10.0, 15.0, 150.00, 299.99)")
        conn.execute(
            "INSERT INTO SELLERS VALUES (1, 'TechBrand Inc', 'John Tech', 'Male', 45, '10001', 'New York', 'NY')")
        conn.execute(
            "INSERT INTO ORDERS VALUES (1001, 1, 'delivered', '2024-07-01', '2024-07-01', '2024-07-03', '2024-07-05', '2024-07-06')")
        conn.execute(
            "INSERT INTO ORDER_ITEMS VALUES (1001, 1, 1, 1, '2024-07-08', 299.99, 15.00, 0.05)")
        conn.execute(
            "INSERT INTO ORDER_PAYMENTS VALUES (1001, 1, 'credit_card', 3, 284.99)")
        conn.execute(
            "INSERT INTO ORDER_REVIEWS VALUES (1, 1001, 5, 'Great!', 'Fast delivery', '2024-07-06', '2024-07-07')")

    return db_path


@pytest.fixture
def mock_embedder():
    return MockEmbedder(dim=64)


@pytest.fixture
def tmp_indexes(tmp_path):
    """Temporary directory for index files."""
    return tmp_path


# ─────────────────────────────────────────────────────────────────────
# Vector Store Tests
# ─────────────────────────────────────────────────────────────────────


class TestFAISSVectorStore:

    def make_chunks(self, n: int = 5) -> list[RagChunk]:
        return [
            RagChunk(
                chunk_type=ChunkType.TABLE_CARD,
                text=f"Table: orders_{i}\nColumns: order_id, amount",
            )
            for i in range(n)
        ]

    def make_embeddings(self, n: int = 5, dim: int = 64) -> list[list[float]]:
        embedder = MockEmbedder(dim=dim)
        return embedder.embed_texts([f"text {i}" for i in range(n)])

    def test_add_and_search(self, tmp_indexes):
        store = FAISSVectorStore(
            dim=64,
            index_path=str(tmp_indexes / "faiss.index"),
            chunks_path=str(tmp_indexes / "chunks.jsonl"),
        )
        chunks = self.make_chunks(10)
        embeddings = self.make_embeddings(10, dim=64)

        store.add_chunks(chunks, embeddings)
        assert store.num_chunks == 10

        query = embeddings[0]
        results = store.search(query, top_k=5)

        assert len(results) > 0
        assert len(results) <= 5
        assert results[0].score >= results[-1].score  # Sorted by score

    def test_save_and_load(self, tmp_indexes):
        store = FAISSVectorStore(
            dim=64,
            index_path=str(tmp_indexes / "faiss2.index"),
            chunks_path=str(tmp_indexes / "chunks2.jsonl"),
        )
        chunks = self.make_chunks(5)
        embeddings = self.make_embeddings(5, dim=64)

        store.add_chunks(chunks, embeddings)
        store.save()

        # Load in new instance
        store2 = FAISSVectorStore(
            dim=64,
            index_path=str(tmp_indexes / "faiss2.index"),
            chunks_path=str(tmp_indexes / "chunks2.jsonl"),
        )
        store2.load()

        assert store2.num_chunks == 5
        assert store2.num_chunks == store.num_chunks

    def test_search_empty_returns_empty(self, tmp_indexes):
        store = FAISSVectorStore(
            dim=64,
            index_path=str(tmp_indexes / "empty.index"),
            chunks_path=str(tmp_indexes / "empty.jsonl"),
        )
        results = store.search([0.0] * 64, top_k=5)
        assert results == []

    def test_cosine_similarity_ordering(self, tmp_indexes):
        """Most similar vector should rank first."""
        store = FAISSVectorStore(
            dim=4,
            index_path=str(tmp_indexes / "cos.index"),
            chunks_path=str(tmp_indexes / "cos.jsonl"),
        )

        # Create known vectors
        v1 = [1.0, 0.0, 0.0, 0.0]   # Unit vector along x
        v2 = [0.0, 1.0, 0.0, 0.0]   # Orthogonal
        v3 = [0.9, 0.1, 0.0, 0.0]   # Close to v1

        chunks = [
            RagChunk(chunk_type=ChunkType.TABLE_CARD, text=f"chunk {i}")
            for i in range(3)
        ]
        store.add_chunks(chunks, [v1, v2, v3])

        # Query similar to v1
        results = store.search(v1, top_k=3)
        assert len(results) == 3
        # First result should be most similar to query (v1 itself = 1.0)
        assert results[0].score >= results[1].score


# ─────────────────────────────────────────────────────────────────────
# BM25 Index Tests
# ─────────────────────────────────────────────────────────────────────


class TestBM25Index:

    def make_chunks(self) -> list[RagChunk]:
        return [
            RagChunk(
                chunk_type=ChunkType.TABLE_CARD,
                text="Table: orders\nColumns: order_id, customer_id, order_total, region",
            ),
            RagChunk(
                chunk_type=ChunkType.METRIC_CARD,
                text="Metric: Revenue [CERTIFIED]\nFormula: SUM(order_total)\nSynonyms: sales, net sales, topline",
            ),
            RagChunk(
                chunk_type=ChunkType.TABLE_CARD,
                text="Table: customers\nColumns: customer_id, customer_name, region, segment",
            ),
            RagChunk(
                chunk_type=ChunkType.QUERY_EXAMPLE,
                text="Q: What was revenue by region?\nSQL: SELECT region, SUM(order_total) FROM orders GROUP BY region",
            ),
        ]

    def test_build_and_search_exact(self, tmp_indexes):
        index = BM25Index(index_path=str(tmp_indexes / "bm25.pkl"))
        index.build(self.make_chunks())

        results = index.search("revenue", top_k=5)
        assert len(results) > 0
        #
