# SchemaAware-RAG – DuckDB

A self-contained submodule that implements schema-aware Retrieval-Augmented Generation (RAG) over a DuckDB warehouse, translating natural-language questions into validated SQL.

## Architecture

```
User question
     │
     ▼
QueryRewriter  ──►  HybridRetriever (FAISS + BM25)
                          │
                          ▼
                      Reranker
                          │
                          ▼
                   ContextBuilder
                          │
                          ▼
                    SQLGenerator  ──►  SQLValidator  ──►  SQLExecutor
```

## Project Structure

| Path                    | Purpose                                                              |
| ----------------------- | -------------------------------------------------------------------- |
| `app/duckdb_connector/` | Connection management, schema extraction, row sampling               |
| `app/metadata/`         | Data models, metric registry, enrichment, text chunking              |
| `app/indexing/`         | Embedding (OpenAI), FAISS vector store, BM25 keyword index, pipeline |
| `app/retrieval/`        | Query rewriting, hybrid retrieval, LLM reranking, context assembly   |
| `app/sql/`              | SQL generation, syntax validation (sqlglot), safe execution          |
| `app/eval/`             | Golden queries fixture and evaluation harness                        |
| `data/`                 | DuckDB warehouse, metric definitions, index artefacts                |

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env   # fill in OPENAI_API_KEY, DUCKDB_PATH, etc.

# 3. Build the index
python -c "
from app.duckdb_connector.connection import get_connection
from app.duckdb_connector.schema_extractor import extract_schema
from app.metadata.models import TableMeta, ColumnMeta
from app.indexing.index_pipeline import build_index
conn = get_connection('data/warehouse.duckdb')
build_index(tables=[], openai_api_key='sk-...')
"

# 4. Run the API
uvicorn app.main:app --reload
```

## Environment Variables

| Variable         | Default                  | Description                                |
| ---------------- | ------------------------ | ------------------------------------------ |
| `DUCKDB_PATH`    | `data/warehouse.duckdb`  | Path to DuckDB file                        |
| `OPENAI_API_KEY` | —                        | OpenAI API key for embeddings & generation |
| `EMBED_MODEL`    | `text-embedding-3-small` | Embedding model name                       |
| `TOP_K`          | `10`                     | Retrieval candidate count                  |
| `RERANK_TOP_N`   | `5`                      | Context chunks after reranking             |

# ── Setup (if not done) ───────────────────────────────────────

cd schema_aware_rag
source .venv/bin/activate

# ── Step 1: Run the indexing pipeline (creates all indexes) ───

python -m app.indexing.index_pipeline --setup-schema

# Expected output:

# INFO | STARTING INDEXING PIPELINE

# INFO | Extracted 8 tables, 48 columns in 1.2s

# INFO | Loaded 7 metrics (5 certified)

# INFO | Loaded 12 sample queries

# INFO | Loaded 7 business rules

# INFO | Created 26 total chunks

# INFO | Embedded 26 chunks in 3.1s

# INFO | Saved vector store: 26 vectors

# INFO | Saved BM25 index: 26 chunks

# INFO | ✅ SUCCESS

# ── Step 2: Start the API ─────────────────────────────────────

uvicorn app.main:app --reload --port 8000

# ── Step 3: Test the API ──────────────────────────────────────

# Health check

curl http://localhost:8000/health | python -m json.tool

# Retrieve context

curl -X POST http://localhost:8000/retrieve \
 -H "Content-Type: application/json" \
 -d '{"query": "What was revenue by region last quarter?", "top_k": 10}' \
 | python -m json.tool

# List metrics

curl http://localhost:8000/metrics | python -m json.tool

# ── Step 4: Run evaluation ────────────────────────────────────

python -m app.eval.evaluator \
 --golden app/eval/golden_queries.yaml \
 --output data/eval_report.json

# ── Step 5: Run all tests ─────────────────────────────────────

pytest tests/ -v --cov=app --cov-report=term-missing

# Run specific test files

pytest tests/test_api.py -v
pytest tests/test_hybrid_retriever.py -v
pytest tests/test_schema_extractor.py -v

# ============================================================

# QUICK REFERENCE — Schema-Aware RAG Layer

# ============================================================

# SETUP (first time only)

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# INITIALIZE DATABASE

python3 -m app.indexing.index_pipeline --setup-schema

# RE-INDEX (after schema/metrics change)

python3 -m app.indexing.index_pipeline

# START API

uvicorn app.main:app --reload --port 8000

# RUN TESTS

pytest tests/ -v

# RUN EVALUATION

python3 -m app.eval.evaluator --output data/eval_report.json

# HEALTH CHECK

curl http://localhost:8000/health

# TEST RETRIEVAL

curl -X POST http://localhost:8000/retrieve \
 -H "Content-Type: application/json" \
 -d '{"query": "What was revenue last quarter?", "top_k": 10}'

# TEST FULL QUERY (Phase 4)

curl -X POST http://localhost:8000/query \
 -H "Content-Type: application/json" \
 -d '{"query": "How many delivered orders do we have?"}' \
 | python3 -m json.tool

# INTERACTIVE DOCS

open http://localhost:8000/docs

# LOGS

tail -f logs/api.log
