"""
warehouse_factory.py
─────────────────────
Factory that creates the correct warehouse connector
based on configuration.

Design decisions:
- Factory pattern keeps callers decoupled from connector classes
- Supports runtime switching between warehouses
- Validates configuration before returning connector
"""

from __future__ import annotations

import logging
from typing import Optional

from app.config import settings
from app.warehouse.base import BaseWarehouseConnector, WarehouseType

logger = logging.getLogger(__name__)


class WarehouseFactory:
    """
    Creates and validates warehouse connectors.

    Usage:
        # Auto-detect from config
        connector = WarehouseFactory.create()

        # Explicit selection
        connector = WarehouseFactory.create("snowflake")
        connector = WarehouseFactory.create("duckdb")
    """

    @staticmethod
    def create(
        warehouse_type: Optional[str] = None,
    ) -> BaseWarehouseConnector:
        """
        Create the appropriate warehouse connector.

        Args:
            warehouse_type: Override config selection
                           "snowflake", "duckdb", or None (auto)

        Returns:
            Configured BaseWarehouseConnector

        Raises:
            ValueError: Unknown warehouse type
            ImportError: Required package not installed
        """
        wtype = warehouse_type or settings.active_warehouse

        logger.info("Creating warehouse connector: %s", wtype)

        if wtype == "snowflake":
            return WarehouseFactory._create_snowflake()
        elif wtype == "duckdb":
            return WarehouseFactory._create_duckdb()
        else:
            raise ValueError(
                f"Unknown warehouse type: '{wtype}'. "
                f"Supported: snowflake, duckdb"
            )

    @staticmethod
    def _create_snowflake() -> BaseWarehouseConnector:
        """Create and validate Snowflake connector."""
        try:
            from app.warehouse.snowflake_connector import SnowflakeConnector
        except ImportError:
            raise ImportError(
                "snowflake-connector-python required. "
                "Install with: pip install snowflake-connector-python"
            )

        connector = SnowflakeConnector(config=settings.snowflake)

        if not connector.test_connection():
            raise ConnectionError(
                f"Cannot connect to Snowflake: {settings.snowflake.account}. "
                "Check credentials in .env (SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, etc.)"
            )

        logger.info(
            "Snowflake connector ready: account=%s, db=%s",
            settings.snowflake.account,
            settings.snowflake.database,
        )
        return connector

    @staticmethod
    def _create_duckdb() -> BaseWarehouseConnector:
        """Create DuckDB connector using existing implementation."""
        from app.duckdb_connector.connection import DuckDBConnectionManager

        class DuckDBAdapter(BaseWarehouseConnector):
            """Thin adapter wrapping DuckDBConnectionManager."""

            def __init__(self):
                super().__init__(WarehouseType.DUCKDB)
                self.conn_mgr = DuckDBConnectionManager()

            def get_connection(self):
                return self.conn_mgr.get_connection()

            def test_connection(self):
                return self.conn_mgr.test_connection()

            def list_schemas(self):
                rows = self.conn_mgr.execute(
                    "SELECT DISTINCT table_schema "
                    "FROM information_schema.tables "
                    "ORDER BY table_schema"
                )
                return [r[0] for r in rows]

            def list_tables(self, schema=None, include_views=True):
                sql = (
                    "SELECT table_schema, table_name, table_type "
                    "FROM information_schema.tables "
                    "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') "
                    "ORDER BY table_schema, table_name"
                )
                rows = self.conn_mgr.execute(sql)
                return [
                    {"schema_name": r[0], "table_name": r[1],
                        "table_type": r[2]}
                    for r in rows
                ]

            def extract_columns(self, schema_name, table_name):
                from app.duckdb_connector.schema_extractor import DuckDBSchemaExtractor
                extractor = DuckDBSchemaExtractor(self.conn_mgr)
                return extractor.extract_columns(schema_name, table_name)

            def get_row_count(self, schema_name, table_name):
                from app.duckdb_connector.schema_extractor import DuckDBSchemaExtractor
                extractor = DuckDBSchemaExtractor(self.conn_mgr)
                return extractor.get_row_count(schema_name, table_name)

            def get_sample_rows(self, schema_name, table_name, limit=5):
                from app.duckdb_connector.schema_extractor import DuckDBSchemaExtractor
                extractor = DuckDBSchemaExtractor(self.conn_mgr)
                return extractor.get_sample_rows(schema_name, table_name, limit)

            def execute(self, sql, params=None):
                return self.conn_mgr.execute(sql, params)

            def get_warehouse_version(self):
                return self.conn_mgr.get_duckdb_version()

        return DuckDBAdapter()

    @staticmethod
    def list_available() -> list[str]:
        """List all available (installed) warehouse connectors."""
        available = ["duckdb"]

        try:
            import snowflake.connector
            available.append("snowflake")
        except ImportError:
            pass

        return available
