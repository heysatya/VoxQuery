"""
schema_extractor.py
────────────────────
Extracts complete schema metadata from DuckDB.

Design decisions:
- Per-table extraction (not bulk) for retrieval precision
- Handles DuckDB's information_schema dialect
- Returns normalized Python objects (not raw tuples)
- Graceful handling of tables with no data
- Excludes system schemas automatically
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.duckdb_connector.connection import DuckDBConnectionManager

logger = logging.getLogger(__name__)

# DuckDB system schemas to exclude from extraction
SYSTEM_SCHEMAS = frozenset({
    "information_schema",
    "pg_catalog",
    "pg_toast",
})


@dataclass
class RawColumnInfo:
    """Raw column metadata directly from information_schema."""
    schema_name: str
    table_name: str
    column_name: str
    ordinal_position: int
    data_type: str
    is_nullable: bool
    column_default: Optional[str]


@dataclass
class RawTableInfo:
    """Raw table metadata with all columns and statistics."""
    schema_name: str
    table_name: str
    table_type: str                         # BASE TABLE, VIEW
    columns: list[RawColumnInfo] = field(default_factory=list)
    row_count: Optional[int] = None
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    estimated_size_bytes: Optional[int] = None

    @property
    def full_name(self) -> str:
        """Return fully qualified table name."""
        return f"{self.schema_name}.{self.table_name}"


class DuckDBSchemaExtractor:
    """
    Extracts complete schema metadata from a DuckDB database.

    Usage:
        conn_mgr = DuckDBConnectionManager()
        extractor = DuckDBSchemaExtractor(conn_mgr)

        # Extract all tables
        tables = extractor.extract_all_tables()

        # Extract single table
        table = extractor.extract_table("main", "orders")
    """

    def __init__(
        self,
        conn_mgr: DuckDBConnectionManager,
        sample_row_limit: int = 5,
        excluded_schemas: Optional[frozenset[str]] = None,
    ):
        self.conn_mgr = conn_mgr
        self.sample_row_limit = sample_row_limit
        self.excluded_schemas = excluded_schemas or SYSTEM_SCHEMAS

    def list_tables(self) -> list[dict[str, str]]:
        """
        List all user-defined tables and views.

        Returns:
            List of dicts with keys: schema_name, table_name, table_type
        """
        sql = """
        SELECT
            table_schema AS schema_name,
            table_name,
            table_type
        FROM information_schema.tables
        WHERE table_schema NOT IN ({placeholders})
        ORDER BY table_schema, table_name
        """.format(
            placeholders=", ".join(
                f"'{s}'" for s in self.excluded_schemas
            )
        )

        rows = self.conn_mgr.execute(sql)
        return [
            {
                "schema_name": row[0],
                "table_name": row[1],
                "table_type": row[2],
            }
            for row in rows
        ]

    def extract_columns(
        self,
        schema_name: str,
        table_name: str,
    ) -> list[RawColumnInfo]:
        """
        Extract column metadata for a specific table.

        Returns:
            List of RawColumnInfo objects ordered by ordinal_position
        """
        sql = """
        SELECT
            table_schema,
            table_name,
            column_name,
            ordinal_position,
            data_type,
            CASE WHEN is_nullable = 'YES' THEN true ELSE false END AS is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = ?
          AND table_name = ?
        ORDER BY ordinal_position
        """

        rows = self.conn_mgr.execute(sql, [schema_name, table_name])

        return [
            RawColumnInfo(
                schema_name=row[0],
                table_name=row[1],
                column_name=row[2],
                ordinal_position=row[3],
                data_type=row[4],
                is_nullable=row[5],
                column_default=row[6],
            )
            for row in rows
        ]

    def get_row_count(
        self,
        schema_name: str,
        table_name: str,
    ) -> Optional[int]:
        """
        Get exact row count for a table.

        Returns:
            Row count or None if table cannot be counted
        """
        sql = f'SELECT COUNT(*) FROM "{schema_name}"."{table_name}"'
        try:
            result = self.conn_mgr.execute_one(sql)
            return int(result[0]) if result else 0
        except Exception as e:
            logger.warning(
                "Could not get row count for %s.%s: %s",
                schema_name,
                table_name,
                e,
            )
            return None

    def get_sample_rows(
        self,
        schema_name: str,
        table_name: str,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """
        Get sample rows from a table.

        Returns:
            List of row dicts (column_name -> value)
        """
        limit = limit or self.sample_row_limit
        sql = f'SELECT * FROM "{schema_name}"."{table_name}" LIMIT {limit}'

        try:
            df = self.conn_mgr.query_df(sql)
            # Convert to records, handling NaN/None
            records = df.where(df.notna(), None).to_dict(orient="records")
            return records
        except Exception as e:
            logger.warning(
                "Could not get sample rows for %s.%s: %s",
                schema_name,
                table_name,
                e,
            )
            return []

    def get_column_stats(
        self,
        schema_name: str,
        table_name: str,
        column_name: str,
        data_type: str,
    ) -> dict[str, Any]:
        """
        Get basic statistics for a column.
        Only runs on numeric and date columns to avoid expensive string scans.

        Returns:
            Dict with min, max, null_count, approx_distinct
        """
        stats: dict[str, Any] = {}

        # Approximate distinct values (fast)
        try:
            sql = f"""
            SELECT approx_count_distinct("{column_name}")
            FROM "{schema_name}"."{table_name}"
            """
            result = self.conn_mgr.execute_one(sql)
            if result:
                stats["approx_distinct"] = result[0]
        except Exception:
            pass

        # Null count
        try:
            sql = f"""
            SELECT COUNT(*) - COUNT("{column_name}")
            FROM "{schema_name}"."{table_name}"
            """
            result = self.conn_mgr.execute_one(sql)
            if result:
                stats["null_count"] = result[0]
        except Exception:
            pass

        # Min/max for numeric and date types
        numeric_types = {"INTEGER", "BIGINT",
                         "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC"}
        date_types = {"DATE", "TIMESTAMP", "TIMESTAMPTZ"}
        type_upper = data_type.upper()

        if any(t in type_upper for t in numeric_types | date_types):
            try:
                sql = f"""
                SELECT
                    MIN("{column_name}"),
                    MAX("{column_name}")
                FROM "{schema_name}"."{table_name}"
                """
                result = self.conn_mgr.execute_one(sql)
                if result:
                    stats["min_value"] = str(
                        result[0]) if result[0] is not None else None
                    stats["max_value"] = str(
                        result[1]) if result[1] is not None else None
            except Exception:
                pass

        return stats

    def extract_table(
        self,
        schema_name: str,
        table_name: str,
        table_type: str = "BASE TABLE",
        include_stats: bool = False,
    ) -> RawTableInfo:
        """
        Extract complete metadata for a single table.

        Args:
            schema_name: Database schema name
            table_name: Table name
            table_type: 'BASE TABLE' or 'VIEW'
            include_stats: Whether to compute column stats (slower)

        Returns:
            RawTableInfo with all metadata populated
        """
        logger.info("Extracting table: %s.%s", schema_name, table_name)

        columns = self.extract_columns(schema_name, table_name)
        row_count = self.get_row_count(schema_name, table_name)
        sample_rows = self.get_sample_rows(schema_name, table_name)

        table_info = RawTableInfo(
            schema_name=schema_name,
            table_name=table_name,
            table_type=table_type,
            columns=columns,
            row_count=row_count,
            sample_rows=sample_rows,
        )

        return table_info

    def extract_all_tables(
        self,
        include_stats: bool = False,
    ) -> list[RawTableInfo]:
        """
        Extract metadata for ALL user tables in the database.

        Args:
            include_stats: Whether to compute per-column statistics (slow)

        Returns:
            List of RawTableInfo objects
        """
        table_list = self.list_tables()
        tables = []

        logger.info("Found %d tables to extract", len(table_list))

        for table_meta in table_list:
            try:
                table_info = self.extract_table(
                    schema_name=table_meta["schema_name"],
                    table_name=table_meta["table_name"],
                    table_type=table_meta["table_type"],
                    include_stats=include_stats,
                )
                tables.append(table_info)
                logger.debug(
                    "Extracted %s (%d rows, %d columns)",
                    table_info.full_name,
                    table_info.row_count or 0,
                    len(table_info.columns),
                )

            except Exception as e:
                logger.error(
                    "Failed to extract table %s.%s: %s",
                    table_meta["schema_name"],
                    table_meta["table_name"],
                    e,
                )
                continue

        logger.info(
            "Successfully extracted %d/%d tables",
            len(tables),
            len(table_list),
        )
        return tables

    def get_schema_summary(self) -> dict[str, Any]:
        """
        Get a high-level summary of the database schema.

        Returns:
            Dict with table count, total columns, etc.
        """
        tables = self.list_tables()
        total_tables = len(tables)

        total_columns = 0
        for t in tables:
            cols = self.extract_columns(t["schema_name"], t["table_name"])
            total_columns += len(cols)

        return {
            "database_path": self.conn_mgr.db_path,
            "duckdb_version": self.conn_mgr.get_duckdb_version(),
            "total_tables": total_tables,
            "total_columns": total_columns,
            "tables": [
                f"{t['schema_name']}.{t['table_name']}"
                for t in tables
            ],
        }
