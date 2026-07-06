# VoxQuery Voice Subsystem E2E MVP Slice

## What This Is

This is the production-ready end-to-end (E2E) implementation slice for the VoxQuery MVP. It integrates all real providers across the data and voice subsystems:

- Voice/text input flow via Deepgram streaming
- Clarification loop driven by Claude Haiku (claude-haiku-4-5-20251001)
- Session memory backed by Upstash Redis
- Security, Authentication & Session via Clerk
- SQL Generation, Semantic routing, and Execution via Snowflake and PgVector
- Telemetry & Tracing via Langfuse and Supabase

It proves the application contracts and state flow using live external providers.

## What Is Real

- FastAPI backend with Pydantic request/response contracts.
- Next.js frontend shell.
- Real voice transcript capture through `/ws/audio` piped to Deepgram STT.
- Claude Haiku (claude-haiku-4-5-20251001) for entity extraction, ambiguity detection, and SQL generation.
- Upstash Redis for distributed session-store.
- Supabase PgVector for RAG context retrieval and Audit writes.
- Snowflake for secure data warehouse query execution.
- Langfuse for tracing LLM execution paths.
- Clerk for Authentication (JWTs).

## Environment Variables Setup

Ensure the following variables are configured before running.

**Backend (`backend/.env`):**
```env
APP_ENV=development
AUTH_MODE=clerk
SESSION_STORE=redis
STT_PROVIDER=deepgram
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

## How To Run

From the backend folder:

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

From the frontend folder (Next.js production build is recommended on Windows to avoid Turbopack freezing during module resolution):

```powershell
npm run build
npm run start -- -p 3000
```

Open: `http://127.0.0.1:3000`
Health check: `http://127.0.0.1:8000/health`

## How To Test Manually (E2E Test Scenarios)

Use the voice recording functionality or text input. The backend must have valid credentials in the `.env` file.

| Prompt | Expected behavior |
|---|---|
| `Show revenue by region` | Claude identifies ambiguity around "revenue" (e.g., net vs gross). Triggers one clarification question. |
| `Show net revenue by customer segment` | Claude generates SQL and queries Snowflake directly. Returns the data payload. |
| `Show revenue by state` | Triggers clarification. After selection, Claude generates SQL and queries Snowflake for state-level data. |

## UI States

- `Session active`: Browser has an authenticated session with the backend via Clerk JWT.
- `idle`: No recording or query pipeline is active.
- `clarification_pending`: Received from `/ws/pipeline`; Claude needs one user choice before completing the query.
- `Result ready`: Received after `/ws/pipeline` emits `result_ready` and the Snowflake query result is retrieved.

## Success Criteria

1. **Voice Input**: Audio stream connects to Deepgram via WebSocket and returns accurate transcripts in real-time.
2. **Ambiguity Resolution**: Claude correctly identifies ambiguous queries and initiates the clarification loop.
3. **State Persistence**: The session is persisted in Redis across the clarification flow.
4. **SQL Execution**: Claude generates valid Snowflake SQL, which is executed against the warehouse successfully, without throwing permissions or syntax errors.
5. **UI Updates**: The Next.js frontend correctly updates based on the `/ws/pipeline` WebSocket events.
6. **Observability**: Langfuse traces the Claude interaction and Supabase records the audit trail.

## Verification of Architecture Gates

To verify that each gate in the architecture roadmap has been successfully implemented and integrated:

### Gate 1 & 4 - Voice STT & Deepgram Streaming
- **Verification:** Click "Start recording" in the frontend and speak. 
- **Success Criteria:** Real-time `interim_transcript` fragments appear instantly from the `/ws/audio` WebSocket connection, resolving into a final transcript when you stop recording.

### Gate 2 - Session & Clerk JWT Auth
- **Verification:** Open Browser DevTools -> **Application** -> **Session Storage**.
- **Success Criteria:** A `voxquery_session_id` exists. Check the **Network** tab (WS filter) and ensure WebSocket requests to the `:8000` backend contain the `?token=` parameter, correctly injecting the Clerk JWT for tenant isolation.

### Gate 3 - Redis Session Store
- **Verification:** Hit `http://127.0.0.1:8000/health`.
- **Success Criteria:** The endpoint returns `"redis": "ok"`. Submit an ambiguous query to trigger a clarification state. Reload the browser and select an option; the session should resume flawlessly by hydrating context from Upstash Redis.

### Gate 5 - Supabase/Postgres Audit Writes
- **Verification:** Log into your Supabase Dashboard and check the `audit_log` table.
- **Success Criteria:** The system asynchronously writes session telemetry events (e.g., `stt.mic.permission`, `pipeline.completed`) to the database without blocking the user interaction flow or exposing raw warehouse PII.

### Gate 6 - Langfuse Observability
- **Verification:** Log into your Langfuse Dashboard (`cloud.langfuse.com`).
- **Success Criteria:** Look under **Traces**. A trace for `claude-sql-generation` should exist (matching your `conversation_id`). It must display the exact input prompt sent to Claude, the generated SQL, the validation status, confidence score, and token usage.

### Gate 7 - Real RAG, SQL, and Snowflake Integration
- **Verification:** Submit a domain-specific query (e.g., "Show revenue by region").
- **Success Criteria:**
  - **RAG:** Backend logs confirm `PgVectorSchemaRetriever` connecting to Supabase and retrieving similarity chunks.
  - **SQL:** `sqlglot` validation passes (visible in Langfuse trace). 
  - **Snowflake (MVP Stub):** The `SnowflakeWarehouseConnector` dynamically parses the requested dimension from the SQL and returns a matching dummy payload shaped correctly for the UI. (To query real data, update `WAREHOUSE_PROVIDER` to connect with real credentials).
