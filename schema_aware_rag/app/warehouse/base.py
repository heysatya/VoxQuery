"""
base.py
────────
Abstract base class defining the warehouse connector interface.

All warehouse implementations (Snowflake, DuckDB, Postgres, BigQuery)
must implement this interface to be pluggable into the RAG pipeline.

Design decisions:
- Abstract base enforces contract without coupling to any warehouse
- Dataclasses for metadata (warehouse-agnostic)
- Context manager pattern for safe connection lifecycle
- Sync API (async wrappers added at service layer)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generator, Iterator, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────


class WarehouseType(str, Enum):
    """Supported warehouse types."""
    DUCKDB = "duckdb"
    SNOWFLAKE = "snowflake"
    POSTGRES = "postgres"
    BIGQUERY = "bigquery"


class ConnectionStatus(str, Enum):
    """Connection health states."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    UNKNOWN = "unknown"


# ─────────────────────────────────────────────────────────────────────
# Shared Dataclasses (warehouse-agnostic)
# ─────────────────────────────────────────────────────────────────────


@dataclass
class RawColumnInfo:
    """
    Column metadata extracted from any warehouse.
    Normalized to a common format regardless of source.
    """
    schema_name: str
    table_name: str
    column_name: str
    ordinal_position: int
    data_type: str
    is_nullable: bool
    column_default: Optional[str] = None
    comment: Optional[str] = None         # Snowflake column comment
    is_primary_key: bool = False
    is_unique: bool = False


@dataclass
class RawTableInfo:
    """
    Table metadata extracted from any warehouse.
    Normalized to a common format regardless of source.
    """
    schema_name: str
    table_name: str
    table_type: str                        # TABLE, VIEW, EXTERNAL
    columns: list[RawColumnInfo] = field(default_factory=list)
    row_count: Optional[int] = None
    bytes_size: Optional[int] = None
    created_at: Optional[str] = None
    last_altered: Optional[str] = None
    comment: Optional[str] = None         # Snowflake table comment
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    cluster_keys: list[str] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.schema_name}.{self.table_name}"

    @property
    def has_description(self) -> bool:
        return bool(self.comment and self.comment.strip())


@dataclass
class QueryHistoryEntry:
    """
    A query from warehouse history, used for sample query mining.
    """
    query_id: str
    query_text: str
    database_name: str
    schema_name: str
    user_name: str
    role_name: str
    warehouse_name: str
    execution_time_ms: int
    rows_produced: int
    execution_count: int
    last_executed: str


@dataclass
class SchemaSnapshot:
    """
    Complete schema snapshot from a warehouse.
    """
    warehouse_type: WarehouseType
    database: str
    tables: list[RawTableInfo] = field(default_factory=list)
    views: list[RawTableInfo] = field(default_factory=list)
    extracted_at: str = ""
    total_tables: int = 0
    total_columns: int = 0


# ─────────────────────────────────────────────────────────────────────
# Abstract Base Connector
# ─────────────────────────────────────────────────────────────────────


class BaseWarehouseConnector(ABC):
    """
    Abstract interface for all warehouse connectors.

    Every warehouse implementation must:
    1. Implement all abstract methods
    2. Handle connection lifecycle in get_connection()
    3. Return normalized RawTableInfo / RawColumnInfo objects
    4. Never expose warehouse-specific types to callers
    """

    def __init__(self, warehouse_type: WarehouseType):
        self.warehouse_type = warehouse_type
        self._status = ConnectionStatus.UNKNOWN
        logger.info("Initializing %s connector", warehouse_type.value)

    # ── Abstract Methods ──────────────────────────────────────────

    @abstractmethod
    @contextmanager
    def get_connection(self) -> Generator:
        """Context manager providing a warehouse connection."""
        ...

    @abstractmethod
    def test_connection(self) -> bool:
        """Test connectivity. Returns True if healthy."""
        ...

    @abstractmethod
    def list_schemas(self) -> list[str]:
        """List all user-accessible schemas/databases."""
        ...

    @abstractmethod
    def list_tables(
        self,
        schema: Optional[str] = None,
        include_views: bool = True,
    ) -> list[dict[str, str]]:
        """List all tables with schema, name, type."""
        ...

    @abstractmethod
    def extract_columns(
        self,
        schema_name: str,
        table_name: str,
    ) -> list[RawColumnInfo]:
        """Extract all columns for a table."""
        ...

    @abstractmethod
    def get_row_count(
        self,
        schema_name: str,
        table_name: str,
    ) -> Optional[int]:
        """Return exact or approximate row count."""
        ...

    @abstractmethod
    def get_sample_rows(
        self,
        schema_name: str,
        table_name: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return sample rows as list of dicts."""
        ...

    @abstractmethod
    def execute(
        self,
        sql: str,
        params: Optional[list] = None,
    ) -> list[tuple]:
        """Execute SQL and return all rows."""
        ...

    @abstractmethod
    def get_warehouse_version(self) -> str:
        """Return warehouse version string."""
        ...

    # ── Concrete Methods (optional override) ──────────────────────

    def extract_table(
        self,
        schema_name: str,
        table_name: str,
        table_type: str = "TABLE",
        include_sample: bool = True,
    ) -> RawTableInfo:
        """
        Extract complete metadata for a single table.
        Default implementation using abstract methods.
        Subclasses can override for efficiency.
        """
        columns = self.extract_columns(schema_name, table_name)
        row_count = self.get_row_count(schema_name, table_name)
        sample_rows = (
            self.get_sample_rows(schema_name, table_name)
            if include_sample else []
        )

        return RawTableInfo(
            schema_name=schema_name,
            table_name=table_name,
            table_type=table_type,
            columns=columns,
            row_count=row_count,
            sample_rows=sample_rows,
        )

    def extract_all_tables(
        self,
        excluded_schemas: Optional[list[str]] = None,
    ) -> list[RawTableInfo]:
        """
        Extract metadata for all tables.
        Uses list_tables() + extract_table() in sequence.
        """
        excluded = set(excluded_schemas or [])
        table_list = self.list_tables()
        tables = []

        for t in table_list:
            if t["schema_name"].upper() in excluded:
                continue
            try:
                table_info = self.extract_table(
                    t["schema_name"],
                    t["table_name"],
                    t.get("table_type", "TABLE"),
                )
                tables.append(table_info)
            except Exception as e:
                logger.error(
                    "Failed to extract %s.%s: %s",
                    t["schema_name"], t["table_name"], e
                )

        return tables

    def get_schema_summary(self) -> dict[str, Any]:
        """Return a high-level summary of the warehouse."""
        tables = self.list_tables()
        return {
            "warehouse_type": self.warehouse_type.value,
            "version": self.get_warehouse_version(),
            "total_tables": len(tables),
            "schemas": list({t["schema_name"] for t in tables}),
        }

    @property
    def status(self) -> ConnectionStatus:
        return self._status
