from uuid import UUID

import asyncpg
from app.models.contracts import SchemaChunk
from app.rag.retriever import SchemaRetriever
from langfuse.openai import AsyncOpenAI


class PgVectorSchemaRetriever(SchemaRetriever):
    def __init__(self, openai_client: AsyncOpenAI, db_pool: asyncpg.Pool) -> None:
        self.openai = openai_client
        self.pool = db_pool

    async def retrieve(self, submitted_text: str, tenant_id: UUID) -> tuple[list[SchemaChunk], float]:
        response = await self.openai.embeddings.create(
            input=submitted_text,
            model="text-embedding-3-small"
        )
        embedding = response.data[0].embedding
        embedding_str = str(embedding)
        
        # Match chunks using vector similarity
        query = """
            SELECT 
                source_ref, 
                content, 
                entity_type, 
                table_name, 
                column_name, 
                1 - (embedding <=> $1::vector) AS similarity
            FROM schema_chunks
            WHERE tenant_id = $2
            ORDER BY embedding <=> $1::vector
            LIMIT 10;
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, embedding_str, str(tenant_id))
            
        chunks = []
        rag_score = 0.0
        
        for row in rows:
            chunk = SchemaChunk(
                source_ref=row["source_ref"],
                content=row["content"],
                entity_type=row["entity_type"],
                table=row["table_name"],
                column=row["column_name"],
                similarity=row["similarity"],
            )
            chunks.append(chunk)
            
        if chunks:
            rag_score = chunks[0].similarity
            
        return chunks, rag_score
