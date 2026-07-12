from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.contracts import ResultPayload, ResultShape, SchemaTable


class WarehouseConnector(ABC):
    @abstractmethod
    async def execute_readonly(self, sql: str, *, snowflake_role: str) -> tuple[ResultPayload, ResultShape]:
        """Execute canonical, validated read-only SQL using the caller's warehouse role."""

    @abstractmethod
    def fetch_schema_snapshot(self) -> list[SchemaTable]:
        """Fetch the schema metadata (tables and columns) from the warehouse."""
