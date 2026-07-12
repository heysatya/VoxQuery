
"""
test_schema_extractor.py
─────────────────────────
Tests for DuckDB connection manager and schema extractor.

Uses an in-memory DuckDB database with a simple sales schema
to avoid file system dependencies in CI.
"""

from __future__ import annotations

import pytest
import duckdb

from app.duckdb_connector.connection import DuckDBConnectionManager
from app.duckdb_connector.schema_extractor import DuckDBSchemaExtractor
from app.duckdb_connector.sampler import DuckDBSampler


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def in_memory_conn_mgr() -> DuckDBConnectionManager:
    """
    Create a DuckDB connection manager using an in-memory database.
    Populated with a minimal sales schema for testing.
    """
    mgr = DuckDBConnectionManager(db_path=":memory:", read_only=False)

    with mgr.get_connection() as conn:
        # Create orders table
        conn.execute("""
            CREATE TABLE orders (
                order_id    INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                order_date  DATE NOT NULL,
                region      VARCHAR(50),
                order_total DECIMAL(10,2) NOT NULL,
                discount_amount DECIMAL(10,2) DEFAULT 0,
                status      VARCHAR(20) DEFAULT 'completed'
            )
        """)

        # Create customers table
        conn.execute("""
            CREATE TABLE customers (
                customer_id   INTEGER PRIMARY KEY,
                customer_name VARCHAR(150) NOT NULL,
                customer_email VARCHAR(200),
                region        VARCHAR(50),
                created_at    DATE
            )
        """)

        # Create products table
        conn.execute("""
            CREATE TABLE products (
                product_id       INTEGER PRIMARY KEY,
                product_name     VARCHAR(200) NOT NULL,
                product_category VARCHAR(100),
                unit_price       DECIMAL(10,2)
            )
        """)

        # Insert sample orders
        conn.execute("""
            INSERT INTO orders VALUES
                (1, 101, '2024-07-15', 'Northeast', 1250.00, 50.00, 'completed'),
                (2, 102, '2024-07-20', 'West',      850.50,  0.00,  'completed'),
                (3, 103, '2024-08-01', 'Northeast', 2100.00, 100.00,'completed'),
                (4, 104, '2024-08-15', 'South',     650.00,  25.00, 'completed'),
                (5, 105, '2024-09-01', 'West',      1800.00, 0.00,  'completed')
        """)

        # Insert sample customers
        conn.execute("""
            INSERT INTO customers VALUES
                (101, 'Alice Johnson',  'alice@example.com', 'Northeast', '2022-01-01'),
                (102, 'Bob Smith',      'bob@example.com',   'West',      '2022-03-15'),
                (103, 'Carol Davis',    'carol@example.com', 'Northeast', '2021-11-01'),
                (104, 'David Wilson',   'david@example.com', 'South',     '2023-02-20'),
                (105, 'Emma Martinez',  'emma@example.com',  'West',      '2023-06-01')
        """)

        # Insert sample products
        conn.execute("""
            INSERT INTO products VALUES
                (1, 'Widget Pro',    'Electronics', 299.99),
                (2, 'Data Suite',   'Software',    499.99),
                (3, 'Cloud Pack',   'Software',    199.99),
                (4, 'Hardware Kit', 'Hardware',    149.99)
        """)

    return mgr


@pytest.fixture(scope="module")
def extractor(
    in_memory_conn_mgr: DuckDBConnectionManager,
) -> DuckDBSchemaExtractor:
    """Create a schema extractor for the in-memory database."""
    return DuckDBSchemaExtractor(
        conn_mgr=in_memory_conn_mgr,
        sample_row_limit=3,
    )


@pytest.fixture(scope="module")
def sampler(
    in_memory_conn_mgr: DuckDBConnectionManager,
) -> DuckDBSampler:
    """Create a sampler for the in-memory database."""
    return DuckDBSampler(conn_mgr=in_memory_conn_mgr, sample_size=3)


# ──────────────────────────────────────────────────────────────────────
# Connection Manager Tests
# ──────────────────────────────────────────────────────────────────────


class TestDuckDBConnectionManager:

    def test_connection_works(
        self, in_memory_conn_mgr: DuckDBConnectionManager
    ):
        """Basic connection should succeed."""
        assert in_memory_conn_mgr.test_connection() is True

    def test_execute_returns_rows(
        self, in_memory_conn_mgr: DuckDBConnectionManager
    ):
        """Execute should return list of tuples."""
        rows = in_memory_conn_mgr.execute("SELECT 1 AS val, 'hello' AS str")
        assert len(rows) == 1
        assert rows[0][0] == 1
        assert rows[0][1] == "hello"

    def test_execute_one(
        self, in_memory_conn_mgr: DuckDBConnectionManager
    ):
        """execute_one should return single row or None."""
        row = in_memory_conn_mgr.execute_one("SELECT COUNT(*) FROM orders")
        assert row is not None
        assert row[0] == 5

    def test_query_df_returns_dataframe(
        self, in_memory_conn_mgr: DuckDBConnectionManager
    ):
        """query_df should return a pandas DataFrame."""
        import pandas as pd
        df = in_memory_conn_mgr.query_df("SELECT * FROM orders LIMIT 2")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert "order_id" in df.columns

    def test_parameterized_query(
        self, in_memory_conn_mgr: DuckDBConnectionManager
    ):
        """Parameterized queries should work correctly."""
        rows = in_memory_conn_mgr.execute(
            "SELECT order_id FROM orders WHERE region = ?",
            ["Northeast"],
        )
        assert len(rows) == 2
        order_ids = {row[0] for row in rows}
        assert order_ids == {1, 3}

    def test_context_manager(
        self, in_memory_conn_mgr: DuckDBConnectionManager
    ):
        """Context manager should provide working connection."""
        with in_memory_conn_mgr.get_connection() as conn:
            result = conn.execute("SELECT 42").fetchone()
            assert result[0] == 42


# ──────────────────────────────────────────────────────────────────────
# Schema Extractor Tests
# ──────────────────────────────────────────────────────────────────────


class TestDuckDBSchemaExtractor:

    def test_list_tables_finds_all_tables(
        self, extractor: DuckDBSchemaExtractor
    ):
        """Should find all user-created tables."""
        tables = extractor.list_tables()
        table_names = {t["table_name"] for t in tables}

        assert "orders" in table_names
        assert "customers" in table_names
        assert "products" in table_names

        # Should NOT include system tables
        assert "information_schema" not in table_names

    def test_list_tables_has_correct_structure(
        self, extractor: DuckDBSchemaExtractor
    ):
        """Each table entry should have required keys."""
        tables = extractor.list_tables()
        assert len(tables) > 0

        for table in tables:
            assert "schema_name" in table
            assert "table_name" in table
            assert "table_type" in table

    def test_extract_columns_orders(
        self, extractor: DuckDBSchemaExtractor
    ):
        """Should extract correct columns for orders table."""
        columns = extractor.extract_columns("main", "orders")
        col_names = {col.column_name for col in columns}

        assert "order_id" in col_names
        assert "order_date" in col_names
        assert "region" in col_names
        assert "order_total" in col_names
        assert "status" in col_names

    def test_extract_columns_have_data_types(
        self, extractor: DuckDBSchemaExtractor
    ):
        """Columns should have non-empty data types."""
        columns = extractor.extract_columns("main", "orders")
        for col in columns:
            assert col.data_type, f"Column {col.column_name} has empty data type"
            assert col.column_name, "Column has empty name"

    def test_extract_columns_ordered_by_position(
        self, extractor: DuckDBSchemaExtractor
    ):
        """Columns should be ordered by ordinal_position."""
        columns = extractor.extract_columns("main", "orders")
        positions = [col.ordinal_position for col in columns]
        assert positions == sorted(positions)

    def test_get_row_count_orders(
        self, extractor: DuckDBSchemaExtractor
    ):
        """Row count should match inserted data."""
        count = extractor.get_row_count("main", "orders")
        assert count == 5

    def test_get_row_count_customers(
        self, extractor: DuckDBSchemaExtractor
    ):
        """Row count for customers should be correct."""
        count = extractor.get_row_count("main", "customers")
        assert count == 5

    def test_get_sample_rows_returns_dicts(
        self, extractor: DuckDBSchemaExtractor
    ):
        """Sample rows should be list of dicts."""
        rows = extractor.get_sample_rows("main", "orders", limit=3)
        assert len(rows) <= 3
        assert all(isinstance(row, dict) for row in rows)
        assert all("order_id" in row for row in rows)

    def test_extract_table_complete(
        self, extractor: DuckDBSchemaExtractor
    ):
        """extract_table should return fully populated RawTableInfo."""
        table_info = extractor.extract_table("main", "orders")

        assert table_info.schema_name == "main"
        assert table_info.table_name == "orders"
        assert table_info.full_name == "main.orders"
        assert table_info.row_count == 5
        assert len(table_info.columns) > 0
        assert len(table_info.sample_rows) > 0

    def test_extract_all_tables(
        self, extractor: DuckDBSchemaExtractor
    ):
        """extract_all_tables should return all user tables."""
        tables = extractor.extract_all_tables()
        table_names = {t.full_name for t in tables}

        assert "main.orders" in table_names
        assert "main.customers" in table_names
        assert "main.products" in table_names
        assert len(tables) == 3

    def test_get_schema_summary(
        self, extractor: DuckDBSchemaExtractor
    ):
        """Schema summary should have correct counts."""
        summary = extractor.get_schema_summary()

        assert summary["total_tables"] == 3
        assert summary["total_columns"] > 0
        assert "main.orders" in summary["tables"]


# ──────────────────────────────────────────────────────────────────────
# Sampler Tests
# ──────────────────────────────────────────────────────────────────────


class TestDuckDBSampler:

    def test_profile_table_basic(
        self, sampler: DuckDBSampler
    ):
        """profile_table should return complete TableSample."""
        profile = sampler.profile_table("main", "orders")

        assert profile.schema_name == "main"
        assert profile.table_name == "orders"
        assert profile.row_count == 5
        assert len(profile.column_samples) > 0

    def test_profile_detects_metric_columns(
        self, sampler: DuckDBSampler
    ):
        """Columns like order_total should be flagged as metrics."""
        profile = sampler.profile_table("main", "orders")

        col_map = {col.column_name: col for col in profile.column_samples}

        # order_total contains 'total' keyword
        assert "order_total" in col_map
        assert col_map["order_total"].is_likely_metric is True

    def test_profile_detects_date_columns(
        self, sampler: DuckDBSampler
    ):
        """Date columns should be flagged correctly."""
        profile = sampler.profile_table("main", "orders")
        col_map = {col.column_name: col for col in profile.column_samples}

        assert "order_date" in col_map
        assert col_map["order_date"].is_likely_date is True

    def test_distinct_values_for_low_cardinality(
        self, sampler: DuckDBSampler
    ):
        """Should return distinct values for categorical columns."""
        values = sampler.get_distinct_values(
            "main", "orders", "region", limit=20
        )
        assert len(values) > 0
        assert "Northeast" in values
