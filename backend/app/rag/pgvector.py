import asyncio
import logging
import json
import asyncpg
from app.models.contracts import SchemaChunk
from app.rag.retriever import SchemaRetriever
from app.rag.query_rewriter import RewrittenQuery
from langfuse.openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class PgVectorSchemaRetriever(SchemaRetriever):
    def __init__(self, openai_client: AsyncOpenAI | None = None, db_pool: asyncpg.Pool = None) -> None:
        if openai_client is None:
            openai_client = AsyncOpenAI(timeout=120.0)
        self.openai = openai_client
        self.pool = db_pool

    async def retrieve(
        self, rewritten: RewrittenQuery, tenant_id: str
    ) -> tuple[list[SchemaChunk], float]:
        retrieval_query = rewritten.get_retrieval_query()
        bm25_query = rewritten.original + " " + " ".join(rewritten.expanded_terms)

        try:
            response = await self.openai.embeddings.create(
                input=retrieval_query, model="text-embedding-3-small"
            )
            embedding_str = json.dumps(response.data[0].embedding)
        except Exception as exc:
            logger.warning("OpenAI embedding generation failed: %s. Proceeding gracefully without RAG vector search.", exc)
            return [], 0.0

        vector_sql = """
            SELECT 
                source_ref, content, entity_type, table_name, column_name, 
                1 - (embedding <=> $1::vector) AS similarity
            FROM schema_chunks
            WHERE tenant_id = $2
            ORDER BY embedding <=> $1::vector
            LIMIT 50;
        """

        bm25_sql = """
            SELECT 
                source_ref, content, entity_type, table_name, column_name, 
                ts_rank(to_tsvector('english', content), to_tsquery('english', replace(plainto_tsquery('english', $1)::text, '&', '|'))) AS similarity
            FROM schema_chunks
            WHERE tenant_id = $2
              AND to_tsvector('english', content) @@ to_tsquery('english', replace(plainto_tsquery('english', $1)::text, '&', '|'))
            ORDER BY similarity DESC
            LIMIT 50;
        """

        # vector_sql and bm25_sql are independent read queries over the same
        # table. Running them concurrently on two pooled connections instead of
        # sequentially on one roughly halves RAG retrieval latency.
        async def _fetch_vector() -> list:
            async with self.pool.acquire() as conn:
                return await conn.fetch(vector_sql, embedding_str, str(tenant_id))

        async def _fetch_bm25() -> list:
            async with self.pool.acquire() as conn:
                return await conn.fetch(bm25_sql, bm25_query, str(tenant_id))

        vector_rows, bm25_rows = await asyncio.gather(_fetch_vector(), _fetch_bm25())

        k = 60
        scores: dict[str, float] = {}
        chunks_by_ref: dict[str, SchemaChunk] = {}

        # 1. Rank vector results
        for rank, row in enumerate(vector_rows):
            ref = row["source_ref"]
            scores[ref] = scores.get(ref, 0.0) + 1.0 / (k + rank + 1)
            chunks_by_ref[ref] = SchemaChunk(
                source_ref=ref,
                content=row["content"],
                entity_type=row["entity_type"],
                table=row["table_name"],
                column=row["column_name"],
                similarity=row["similarity"],
            )

        # 2. Rank bm25 results
        for rank, row in enumerate(bm25_rows):
            ref = row["source_ref"]
            scores[ref] = scores.get(ref, 0.0) + 1.0 / (k + rank + 1)
            if ref not in chunks_by_ref:
                chunks_by_ref[ref] = SchemaChunk(
                    source_ref=ref,
                    content=row["content"],
                    entity_type=row["entity_type"],
                    table=row["table_name"],
                    column=row["column_name"],
                    similarity=row["similarity"],
                )

        # Sort and return top 10
        sorted_refs = sorted(scores.keys(), key=lambda ref: scores[ref], reverse=True)
        final_chunks = [chunks_by_ref[ref] for ref in sorted_refs[:10]]

        rag_score = 0.0
        if sorted_refs:
            top_ref = sorted_refs[0]
            max_possible_rrf = 2.0 / (k + 1)
            rag_score = min(1.0, scores[top_ref] / max_possible_rrf)

        return final_chunks, rag_score
