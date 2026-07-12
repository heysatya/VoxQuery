from typing import Protocol
from uuid import UUID

from app.models.contracts import SchemaChunk
from app.rag.query_rewriter import RewrittenQuery


class SchemaRetriever(Protocol):
    async def retrieve(self, rewritten: RewrittenQuery, tenant_id: UUID) -> tuple[list[SchemaChunk], float]:
        """Retrieve relevant schema chunks using vector search."""
        ...
