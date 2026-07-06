CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS schema_chunks (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  table_name TEXT NOT NULL,
  column_name TEXT,
  content TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  entity_type TEXT NOT NULL DEFAULT 'column',
  embedding vector(1536),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for vector similarity search (cosine distance)
CREATE INDEX IF NOT EXISTS schema_chunks_embedding_idx ON schema_chunks USING hnsw (embedding vector_cosine_ops);
