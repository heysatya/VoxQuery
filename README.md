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
- **Schema-Aware RAG**: Supabase PgVector powering a semantic Query Rewriter, combining vector similarity and BM25 Reciprocal Rank Fusion for high-recall warehouse schema injection.
- **Database & Telemetry**: Supabase Postgres for async Audit writes, feedback collection, and database-driven synonym glossaries.
- **Data Warehouse**: Snowflake connector running live against the real E-commerce dataset for accurate BI results, optimized with a high-performance, thread-safe `SnowflakeConnectionPool`.
- **Admin Console**: Strict RBAC-protected administrative cockpit at `/admin` to manage Tenant Glossaries, review low-quality query feedback, and monitor database telemetry.
- **Tenant Provisioning**: Clerk Webhooks endpoint (`/api/webhooks/clerk`) that automates user onboarding, tenant creation, and default glossary seeding (Kaggle E-Commerce mappings).
- **Observability**: Langfuse for tracing LLM execution paths, latency, and tokens.
- **Authentication**: Clerk for enterprise SSO, user roles, and secure JWT verification.

---

## MVP Simplifications
- **ARCH-5 (Result-set duplication detection)**: The system currently relies on a textual heuristic (detecting JOIN without DISTINCT and row_count > 100) instead of a real Snowflake metadata cardinality check. This is an accepted MVP simplification to reduce execution latency.

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
CLERK_SECRET_KEY=<clerk_secret_key>
CLERK_WEBHOOK_SECRET=<clerk_webhook_secret>
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

The system is verified against the following comprehensive test cases under the live certification test plan:

*   **Category A: Core Happy Path & Execution**
    *   **A1: Simple Aggregation** — Natural language to Snowflake SQL execution and Stat card display.
    *   **A2: Time-Series Data Visualization** — Renders interactive Line Charts.
    *   **A3: Snowflake Connection Pool** — Validates query latency reduction on subsequent execution turns.
*   **Category B: The Clarification Loop**
    *   **B1: Entity Ambiguity Block** — Triggers a modal for user clarification before compiling queries.
*   **Category C: Schema-Aware RAG & Hybrid Retrieval**
    *   **C1: Metric Registry Resolution** — Resolves net revenue/margin formulas dynamically.
    *   **C2: RRF Multi-Hop Schema Injection** — Joins multiple tables (e.g. active vs churned customers).
*   **Category D: Memory & Multi-Turn Context**
    *   **D1: Pronoun Resolution via History** — Retains context across multiple conversational turns.
*   **Category E: Deliberate Errors (Safety Tests)**
    *   **E1: Destructive Intent** — Blocks SQL injection attempts (e.g., DROP/DELETE).
*   **Category F: Telemetry Verification**
    *   **F1: Langfuse Thumbs Down Scoring** — Submits user feedback directly to Langfuse.
*   **Category G: Break Cases & Rough Edges (Graceful Degradation)**
    *   **G1: LLM SQL Hallucination** — Graceful handling of invalid columns/tables.
    *   **G2: Clarification Modal Abandonment** — Automatically cleans and updates state if a new query is submitted.
    *   **G3: Voice Input Graceful Degradation** — Smooth reversion to text if microphone access is denied.
    *   **G4: Clarification Timeout Expiry** — Graceful session resets on stale interaction loops.
*   **Category H: Admin Console & Role-Based Access Control (RBAC)**
    *   **H1: Unauthorized Access Prevention** — Restricts access to `/admin` route.
    *   **H2: Tenant Glossary Visualization** — Displays custom tenant glossary and default mappings.
    *   **H3: Feedback Loop Review** — Inspects user thumbs-down feedback.
*   **Category I: Production-Readiness Constraints**
    *   **I1: Rate Limiter Throttling** — Enforces a maximum threshold of requests per user/session.
*   **Category J: World-Class Interactive UI Features**
    *   **J1: Interactive Chart Drill-down** — Enables chart interaction to dispatch sub-queries automatically.
    *   **J2: Anomaly Narration Validation** — Detects anomalies (spikes/drops) and adds contextual explanations.
    *   **J3: Sharing & Export (Permalinks)** — Instantly renders historical queries and charts via static URLs.
*   **Category K: Authentication & Tenant Provisioning (Webhooks)**
    *   **K1: Automated Tenant and User Provisioning** — Automatically registers users via Clerk signup webhooks.
    *   **K2: Secure DSN Isolation Enforcement** — Guarantees tenant isolation for Snowflake queries.
    *   **K3: Automated Glossary Provisioning** — Confirms that default Kaggle synonyms are auto-seeded on user onboarding.

For the exhaustive step-by-step test plan, please refer to: [VoxQuery E2E Test Plan](file:///docs/test/VoxQuery_E2E_Test_Plan.md).

---

## Active Core Documents
- **Revised MVP Product Requirements Document (PRD)**: [prd.md](./docs/prd.md)
- **Live E2E Test Plan**: [VoxQuery_E2E_Test_Plan.md](./docs/test/VoxQuery_E2E_Test_Plan.md)
- **Admin Console Test Plan**: [Admin_UI_Test_Plan.md](./docs/test/Admin_UI_Test_Plan.md)
