# VoxQuery — Voice-Driven Data Analyst

VoxQuery is an enterprise-grade, voice-driven data analyst that enables non-technical stakeholders and executives to query data warehouses (like Snowflake) using natural language speech, and receive instant visualizations and spoken summaries.

## Current Branch: `voice-subsystem` (E2E MVP Slice)

> **Status:** Production-Ready End-to-End (E2E) MVP Implementation Slice
> This branch integrates all real providers across the data and voice subsystems to prove application contracts and state flows.

### What Is Real in this Slice
- **FastAPI backend** with strict Pydantic request/response contracts.
- **Next.js frontend**: Fully decoupled headless engine hook (`useVoxQuerySession`) powering an "Ambient Intelligence" 3-state UI (Ready → Thinking → Insight).
- **Voice STT**: Real voice transcript capture through `/ws/audio` piped to Deepgram streaming STT.
- **Voice TTS**: Real-time synthesized narrative audio playback through `/ws/tts` via Deepgram TTS.
- **LLM Engine**: Claude Haiku (claude-haiku-4-5-20251001) for entity extraction, ambiguity detection, SQL generation, and data narrative storytelling.
- **Session Memory**: Upstash Redis for distributed session-store (handling session TTL and context windows).
- **Database & Telemetry**: Supabase PgVector for RAG context retrieval and async Audit writes.
- **Data Warehouse**: Snowflake connector (currently stubbed via `dummy_dsn`, waiting for real credentials for integration).
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

## How To Test Manually (E2E Test Scenarios)

Use the voice recording functionality or text input. The backend must have valid credentials in the `.env` file.

| Prompt | Expected behavior |
|---|---|
| `Show revenue by region` | Claude identifies ambiguity around "revenue" (e.g., net vs gross). Triggers one clarification question. |
| `Show net revenue by customer segment` | Claude generates SQL and queries Snowflake directly. Returns the data payload. UI enters Insight state and Deepgram streams an audio narrative. |
| `Break it down by region` (Follow-up) | UI updates to `Show net revenue by customer segment → Break it down by region`. Claude generates refined SQL and updates the chart. |
| `Show revenue by state` | Triggers clarification. After selection, Claude generates SQL and queries Snowflake for state-level data. |

### UI States
- **State 1: Ready (Listening Concierge)**: Ambient breathing orb, starter questions, and minimal text fallback.
- **State 2: Thinking (Processing)**: Directional orb animation, transcript display, and human-readable pipeline status.
- **State 3: Insight (Answer)**: Storytelling narrative (with Deepgram audio playback), frosted glass Recharts visualization, trust layer (confidence/SQL toggle), and proactive follow-up suggestions (which maintain complete query context).
- **Interruptive: Clarification**: Dark glass overlay requesting user disambiguation before proceeding.

---

## Verification of Architecture Gates

To verify that each gate in the architecture roadmap has been successfully implemented and integrated in this branch:

1. **Gate 1 & 4 - Voice STT & Deepgram Streaming:**
   *Verification:* Click "Start recording" in the frontend and speak. 
   *Success:* Real-time `interim_transcript` fragments appear instantly from the `/ws/audio` WebSocket connection, resolving into a final transcript.

2. **Gate 2 - Session & Clerk JWT Auth:**
   *Verification:* Open Browser DevTools -> Application -> Session Storage.
   *Success:* A `voxquery_session_id` exists. WebSocket requests to `:8000` contain the `?token=` parameter for tenant isolation.

3. **Gate 3 - Redis Session Store:**
   *Verification:* Hit `http://127.0.0.1:8000/health`.
   *Success:* Returns `"redis": "ok"`. Submit an ambiguous query, reload the browser, and select an option; session resumes flawlessly.

4. **Gate 5 - Supabase/Postgres Audit Writes:**
   *Verification:* Check the `audit_log` table in Supabase.
   *Success:* Session telemetry events (e.g., `stt.mic.permission`, `pipeline.completed`) are written asynchronously without failing on timestamp serialization, without blocking flow, or exposing raw warehouse PII.

5. **Gate 6 - Langfuse Observability:**
   *Verification:* Log into Langfuse Dashboard under **Traces**.
   *Success:* A trace for `claude-sql-generation` exists (matching `conversation_id`), displaying the exact prompt, SQL, validation status, confidence score, and token usage.

6. **Gate 7 - Real RAG, SQL, and Snowflake Integration:**
   *Verification:* Submit a domain-specific query.
   *Success:* Backend retrieves similarity chunks via `PgVectorSchemaRetriever`. `sqlglot` validation passes. The Snowflake Connector executes and returns a matching payload.

---

## Project Documents

### Active Specifications (Voice Subsystem)
- **Voice Subsystem Engineering Spec**: [engineering-spec.md](./docs/voice-subsystem/engineering-spec.md)
- **Voice Subsystem Interface Contracts**: [interface-contracts.md](./docs/voice-subsystem/interface-contracts.md)
- **Frontend Architecture Blueprint**: [frontend-architecture-blueprint.md](./docs/voice-subsystem/frontend-architecture-blueprint.md)
- **Data Integration Handoff**: [data-integration-handoff.md](./docs/voice-subsystem/data-integration-handoff.md)

### Active Core Documents
- **Revised MVP Product Requirements Document (PRD)**: [prd.md](./docs/prd.md)


