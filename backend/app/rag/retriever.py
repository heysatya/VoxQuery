from typing import Protocol
from uuid import UUID

from app.models.contracts import SchemaChunk


class SchemaRetriever(Protocol):
    async def retrieve(self, submitted_text: str, tenant_id: UUID) -> tuple[list[SchemaChunk], float]:
        """Retrieve relevant schema chunks using vector search."""
        ...
