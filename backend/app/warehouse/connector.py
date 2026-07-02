from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.contracts import ResultPayload, ResultShape


class WarehouseConnector(ABC):
    @abstractmethod
    async def execute_readonly(self, sql: str, *, snowflake_role: str) -> tuple[ResultPayload, ResultShape]:
        """Execute validated read-only SQL using the caller's warehouse role."""
