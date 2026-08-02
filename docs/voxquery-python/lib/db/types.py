from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ColumnInfo:
    name: str
    data_type: str


@dataclass
class QueryExecutionResult:
    columns: list[ColumnInfo]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    execution_ms: float


@dataclass
class SchemaTable:
    table_name: str
    columns: list[ColumnInfo] = field(default_factory=list)


class DBAdapter(ABC):
    """Every backend provider implements this. The pipeline, validator, and
    API routes only ever talk to this interface — swapping backends means
    editing config/db_config.json, not this code or its callers."""

    provider_name: str
    validator_dialect: str  # sqlglot dialect string: "postgres", "snowflake", "mysql", ...

    @abstractmethod
    def execute_select(self, sql: str, statement_timeout_ms: int) -> QueryExecutionResult:
        """Executes an already-validated, already-capped SELECT statement.
        Must NOT re-validate — that already happened in the pipeline.
        Must enforce statement_timeout_ms at the connection/session level
        as a second guardrail layer, independent of the row cap already
        injected by the validator."""
        raise NotImplementedError

    @abstractmethod
    def fetch_schema_snapshot(self) -> list[SchemaTable]:
        """Used at startup / admin 're-index schema' trigger — not on the hot query path."""
        raise NotImplementedError

    @abstractmethod
    def dispose(self) -> None:
        raise NotImplementedError
