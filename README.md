# VoxQuery — Voice-Driven Data Analyst

VoxQuery is an enterprise-grade, voice-driven data analyst that enables non-technical stakeholders and executives to query data warehouses (like Snowflake) using natural language speech, and receive instant visualizations and spoken summaries.

## Current Branch: `voxquery-e2e-integration` (Live E2E Certification)

> **Status:** Production-Ready End-to-End (E2E) Certification
> This branch moves beyond the MVP slice, fully integrating the LangGraph orchestration layer, a schema-aware semantic RAG pipeline, and real production warehouse credentials to certify the application for deployment.

### What Is Real in this Slice
- **FastAPI backend** with strict Pydantic request/response contracts and robust LangGraph cyclic orchestration for interruption and clarification routing.
- **Next.js frontend**: Fully decoupled headless engine hook (`useVoxQuerySession`) powering an "Ambient Intelligence" 3-state UI (Ready → Thinking → Insight).
- **Voice STT**: Real voice transcript capture through `/ws/audio` piped to Deepgram streaming STT.
- **Voice TTS**: Real-time synthesized narrative audio playback through `/ws/tts` via Deepgram TTS.
- **LLM Engine**: Claude Haiku (claude-haiku-4-5-20251001) for entity extraction, ambiguity detection, SQL generation, and data narrative storytelling.
- **Session Memory**: Upstash Redis for distributed session-store (handling session TTL and context windows).
- **Schema-Aware RAG**: Supabase PgVector powering a semantic Metric Registry and Query Rewriter, combining vector similarity and BM25 Reciprocal Rank Fusion for high-recall warehouse schema injection.
- **Database & Telemetry**: Supabase Postgres for async Audit writes.
- **Data Warehouse**: Snowflake connector running live against the real E-commerce dataset for accurate BI results.
- **Observability**: Langfuse for tracing LLM execution paths, latency, and tokens.
- **Authentication**: Clerk for enterprise SSO and JWT generation.

---

## Environment Variables Setup

Ensure the following variables are configured before running. Do **not** commit these to version control.

**Backend (`backend/.env`):**
```env
APP_ENV=development
AUTH_MODE=clerk
SESSION_STORE=redis
STT_PROVIDER=deepgram
TTS_PROVIDER=deepgram
LLM_PROVIDER=claude
RAG_PROVIDER=pgvector
WAREHOUSE_PROVIDER=snowflake

# API Keys & Connections (Replace with your actual keys)
UPSTASH_REDIS_URL=<upstash_redis_url>
CLERK_ISSUER=<clerk_issuer_url>
CLERK_JWKS_URL=<clerk_jwks_url>
ANTHROPIC_API_KEY=<anthropic_api_key>
OPENAI_API_KEY=<openai_api_key>
DEEPGRAM_API_KEY=<deepgram_api_key>
SUPABASE_DATABASE_URL=<supabase_database_pooler_url>
LANGFUSE_SECRET_KEY=<langfuse_secret_key>
LANGFUSE_PUBLIC_KEY=<langfuse_public_key>
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

**Frontend (`frontend/.env.local`):**
```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
NEXT_PUBLIC_AUTH_MODE=clerk
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=<clerk_publishable_key>
```

---

## How To Run Locally

### 1. Start the Backend
From the `backend` folder, run the FastAPI server:
```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```
*Health check:* `http://127.0.0.1:8000/health`

### 2. Start the Frontend
From the `frontend` folder, a production build is recommended on Windows to avoid Turbopack freezing during module resolution:
```powershell
npm run build
npm run start -- -p 3000
```
*Application:* `http://127.0.0.1:3000`

---

## Live E2E Certification Test Plan

The system should be verified against the following real-world test scenarios using live credentials.

### Category A: Core Happy Path & Execution
**Test Case A1: Simple Aggregation**
* **Action:** Submit: *"What is the total revenue for the last 30 days?"*
* **Expected:** A `Stat` card (large number) appears in the main feed. The "Trust Panel" displays "Confidence: High".

**Test Case A2: Time-Series Data Visualization**
* **Action:** Submit: *"Show me daily order volume for the past week."*
* **Expected:** The UI dynamically renders a **Line Chart**.

### Category B: The Clarification Loop (Pre-SQL Ambiguity)
**Test Case B1: Entity Ambiguity Block**
* **Action:** Submit: *"How many customers do we have in the US?"*
* **Expected:** A Clarification Modal appears asking *"By 'US', do you mean Shipping Country or Billing Country?"* Click a button and ensure the query resumes successfully.

### Category C: Schema-Aware RAG & Hybrid Retrieval
**Test Case C1: Metric Registry Resolution**
* **Action:** Submit: *"What is our Net Revenue by region?"*
* **Expected:** The Trust Panel text or generated SQL explicitly shows the correct formula for Net Revenue (as defined in the Metric Registry), verifying the `rewrite_query_node` successfully mapped the term to specific warehouse tables.

**Test Case C2: RRF Multi-Hop Schema Injection**
* **Action:** Submit: *"Show me the conversion rate for active customers vs churned customers."*
* **Expected:** Check the generated SQL in the Trust Panel. It should accurately join `customers`, `orders`, and tables governing `churn` logic, proving that Reciprocal Rank Fusion retrieved all disparate DDL chunks necessary.

### Category D: Memory & Multi-Turn Context
**Test Case D1: Pronoun Resolution via History**
* **Action:** Submit: *"Show me the top 5 product categories by sales."* Wait for the Bar Chart. Follow up with: *"Now filter those for just the state of California."*
* **Expected:** The Bar Chart updates. The visual categories remain the same, but the numerical values change. The Trust Panel's SQL snippet should show a `WHERE` clause for California applied to the previous context.

### Category E: Deliberate Errors (Safety Tests)
**Test Case E1: Destructive Intent (SQL Injection Guard)**
* **Action:** Submit: *"Delete all records from the orders table."*
* **Expected:** A Graceful Error component appears stating the agent is read-only and cannot modify data. Ensure NO chart or table is rendered.

### Category F: Telemetry Verification
**Test Case F1: Langfuse Thumbs Down Scoring**
* **Action:** On any successful chart response, click the "Thumbs Down" icon.
* **Expected:** The icon highlights or shows a "Feedback submitted" toast.

---

## Active Core Documents
- **Revised MVP Product Requirements Document (PRD)**: [prd.md](./docs/prd.md)
