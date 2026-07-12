"""
test_snowflake_connector.py
────────────────────────────
Tests for Snowflake connector.
Uses mocks to avoid real Snowflake connections in CI.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from app.warehouse.base import WarehouseType
from app.warehouse.warehouse_factory import WarehouseFactory


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_snowflake_config():
    """Mock Snowflake configuration."""
    from app.config import SnowflakeConfig
    config = SnowflakeConfig()
    config.account = "test_account.us-east-1"
    config.user = "test_user"
    config.password = "test_password"
    config.warehouse = "TEST_WH"
    config.database = "TEST_DB"
    config.schema = "PUBLIC"
    config.role = "TEST_ROLE"
    return config


@pytest.fixture
def mock_connector(mock_snowflake_config):
    """Mock Snowflake connector with pre-configured responses."""
    with patch("app.warehouse.snowflake_connector.snowflake") as mock_sf:
        from app.warehouse.snowflake_connector import SnowflakeConnector
        connector = SnowflakeConnector(config=mock_snowflake_config)

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = None

        with patch.object(connector, "get_connection") as mock_get_conn:
            mock_get_conn.return_value.__enter__ = MagicMock(
                return_value=mock_conn)
            mock_get_conn.return_value.__exit__ = MagicMock(return_value=False)
            yield connector


# ─────────────────────────────────────────────────────────────────────
# Config Tests
# ─────────────────────────────────────────────────────────────────────


class TestSnowflakeConfig:

    def test_has_credentials_when_account_and_user_set(
        self, mock_snowflake_config
    ):
        assert mock_snowflake_config.has_credentials is True

    def test_has_no_credentials_when_account_missing(self):
        from app.config import SnowflakeConfig
        cfg = SnowflakeConfig()
        assert cfg.has_credentials is False

    def test_uses_password_auth_by_default(self, mock_snowflake_config):
        assert mock_snowflake_config.uses_key_pair_auth is False

    def test_uses_key_pair_when_key_path_set(self, mock_snowflake_config):
        mock_snowflake_config.private_key_path = "/path/to/key.p8"
        assert mock_snowflake_config.uses_key_pair_auth is True


# ─────────────────────────────────────────────────────────────────────
# Connector Validation Tests
# ─────────────────────────────────────────────────────────────────────


class TestSnowflakeConnectorValidation:

    def test_missing_account_raises(self, mock_snowflake_config):
        from app.warehouse.snowflake_connector import (
            SnowflakeConnector,
            SnowflakeConnectionError,
        )
        mock_snowflake_config.account = ""
        with pytest.raises(SnowflakeConnectionError, match="SNOWFLAKE_ACCOUNT"):
            SnowflakeConnector(config=mock_snowflake_config)

    def test_missing_user_raises(self, mock_snowflake_config):
        from app.warehouse.snowflake_connector import (
            SnowflakeConnector,
            SnowflakeConnectionError,
        )
        mock_snowflake_config.user = ""
        with pytest.raises(SnowflakeConnectionError, match="SNOWFLAKE_USER"):
            SnowflakeConnector(config=mock_snowflake_config)

    def test_missing_credentials_raises(self, mock_snowflake_config):
        from app.warehouse.snowflake_connector import (
            SnowflakeConnector,
            SnowflakeConnectionError,
        )
        mock_snowflake_config.password = ""
        mock_snowflake_config.private_key_path = ""
        with pytest.raises(SnowflakeConnectionError, match="password"):
            SnowflakeConnector(config=mock_snowflake_config)


# ─────────────────────────────────────────────────────────────────────
# Extractor Tests
# ─────────────────────────────────────────────────────────────────────


class TestSnowflakeSchemaExtractor:

    @pytest.fixture
    def extractor(self, mock_connector):
        from app.warehouse.snowflake_extractor import SnowflakeSchemaExtractor
        return SnowflakeSchemaExtractor(mock_connector)

    def test_infer_domain_from_table_name(self, extractor):
        assert extractor._infer_domain("PUBLIC", "FCT_ORDERS", {}) == "sales"
        assert extractor._infer_domain(
            "PUBLIC", "DIM_CUSTOMERS", {}) == "customers"
        assert extractor._infer_domain(
            "PUBLIC", "PRODUCT_CATALOG", {}) == "products"

    def test_infer_domain_from_tags(self, extractor):
        assert extractor._infer_domain(
            "PUBLIC", "SOME_TABLE", {"DOMAIN": "finance"}
        ) == "finance"

    def test_detect_pii_from_column_name(self, extractor):
        assert extractor._detect_pii("customer_email", "VARCHAR", {}) is True
        assert extractor._detect_pii("order_id", "INTEGER", {}) is False
        assert extractor._detect_pii("ssn_number", "VARCHAR", {}) is True

    def test_detect_pii_from_tags(self, extractor):
        assert extractor._detect_pii("user_data", "VARIANT", {
                                     "PII": "TRUE"}) is True

    def test_is_likely_metric(self, extractor):
        assert extractor._is_likely_metric("order_total", "NUMBER") is True
        assert extractor._is_likely_metric("revenue_amount", "DECIMAL") is True
        assert extractor._is_likely_metric("customer_name", "VARCHAR") is False

    def test_is_likely_date(self, extractor):
        assert extractor._is_likely_date("order_date", "DATE") is True
        assert extractor._is_likely_date("created_at", "TIMESTAMP_NTZ") is True
        assert extractor._is_likely_date("order_total", "NUMBER") is False

    def test_infer_synonyms_strips_prefix(self, extractor):
        syns = extractor._infer_synonyms("FCT_ORDERS")
        assert any("orders" in s for s in syns)

    def test_parse_cluster_key(self, extractor):
        result = extractor._parse_cluster_key("LINEAR(ORDER_DATE, REGION)")
        assert "ORDER_DATE" in result
        assert "REGION" in result
        assert "LINEAR" not in result

    def test_parse_empty_cluster_key(self, extractor):
        assert extractor._parse_cluster_key("") == set()


# ─────────────────────────────────────────────────────────────────────
# Sampler Tests
# ─────────────────────────────────────────────────────────────────────


class TestSnowflakeSampler:

    @pytest.fixture
    def sampler(self, mock_connector):
        from app.warehouse.snowflake_sampler import SnowflakeSampler
        return SnowflakeSampler(mock_connector)

    def test_detects_metric_columns(self, sampler):
        profile = sampler._profile_column(
            schema_name="PUBLIC",
            table_name="ORDERS",
            column_name="order_total",
            data_type="NUMBER",
            row_count=100,
            sample_rows=[],
        )
        assert profile.is_likely_metric is True

    def test_detects_date_columns(self, sampler):
        profile = sampler._profile_column(
            schema_name="PUBLIC",
            table_name="ORDERS",
            column_name="order_date",
            data_type="TIMESTAMP_NTZ",
            row_count=100,
            sample_rows=[],
        )
        assert profile.is_likely_date is True

    def test_detects_fk_columns(self, sampler):
        profile = sampler._profile_column(
            schema_name="PUBLIC",
            table_name="ORDERS",
            column_name="customer_sk",
            data_type="INTEGER",
            row_count=100,
            sample_rows=[],
        )
        assert profile.is_likely_fk is True


# ─────────────────────────────────────────────────────────────────────
# Factory Tests
# ─────────────────────────────────────────────────────────────────────


class TestWarehouseFactory:

    def test_create_duckdb(self, tmp_path):
        import duckdb
        db_path = str(tmp_path / "test.duckdb")
        conn = duckdb.connect(db_path)
        conn.close()

        with patch("app.config.settings") as mock_settings:
            mock_settings.active_warehouse = "duckdb"
            mock_settings.duckdb_path = db_path
            mock_settings.duckdb_read_only = False
            mock_settings.duckdb_max_memory = "1GB"
            mock_settings.duckdb_threads = 1

            connector = WarehouseFactory.create("duckdb")
            assert connector is not None
            assert connector.warehouse_type.value == "duckdb"

    def test_list_available_includes_duckdb(self):
        available = WarehouseFactory.list_available()
        assert "duckdb" in available

    def test_unknown_warehouse_raises(self):
        with pytest.raises(ValueError, match="Unknown warehouse type"):
            WarehouseFactory.create("bigquery")
