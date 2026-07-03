# VoxQuery Voice Subsystem Local MVP Slice

## What This Is

This is a credential-free local implementation slice for VoxQuery user stories 4.1, 4.2, and 4.3:

- voice/text input flow
- clarification loop
- single-session conversation memory

It proves the application contracts and state flow before real external providers are wired in.

## What Is Real

- FastAPI backend with Pydantic request/response contracts.
- Next.js frontend shell.
- REST endpoints for session, query, clarification, result, and feedback.
- WebSocket endpoints for fake audio and pipeline events.
- Frontend-driven pipeline UI from `/ws/pipeline` events.
- Fake voice transcript capture through `/ws/audio`.
- Deterministic ambiguity detection.
- Deterministic confidence scoring.
- In-memory session memory.
- Redis session-store adapter behind the same session contract.
- Clarification state and resolved entity handling.
- E-commerce warehouse-shaped fake schema, SQL, and results.
- Tests for backend contracts and frontend behavior.

## What Is Fake

The following are intentionally stubbed for this local slice:

- Deepgram STT
- Clerk auth
- Credentialed Upstash Redis validation
- Supabase/Postgres audit writes
- Langfuse tracing
- Claude SQL generation
- Snowflake execution
- TTS

The fake provider layer is deliberate. It lets the team validate contracts and product flow without credentials or provider latency.

## How To Run

From the backend folder:

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

From the frontend folder:

```powershell
npm run dev -- --hostname 127.0.0.1 --port 3000
```

Open:

```text
http://127.0.0.1:3000
```

Health check:

```text
http://127.0.0.1:8000/health
```

## How To Test Manually

Use these prompts:

| Prompt | Expected behavior |
|---|---|
| `Show revenue by region` | Triggers one clarification question because revenue is ambiguous. |
| `Show net revenue by customer segment` | Completes directly and returns a result. |
| `Show revenue by state` | Triggers clarification, then returns state-level e-commerce data after selection. |
| `Show product category revenue` | Returns product-category-shaped SQL/result once metric ambiguity is resolved or explicit. |

Use `Fake voice` to simulate a local voice transcript through the backend `/ws/audio` endpoint. It does not access the microphone or Deepgram, but it exercises the same browser-to-backend WebSocket surface that real audio will later use. The transcript remains editable; when submitted, `/api/query` is still the text-only reviewed-query path.

## UI States

- `Session active`: browser has a backend session.
- `idle`: no recording or query pipeline is active.
- `clarification_pending`: received from `/ws/pipeline`; the backend needs one user choice before completing the query.
- `Result ready`: received after `/ws/pipeline` emits `result_ready` and the read-model result is loaded.

## How To Explain This To Teammates

The local MVP slice is a working, testable skeleton of the voice subsystem. It proves that the frontend, backend contracts, WebSocket event flow, clarification loop, confidence logic, and session memory can work together. It does not yet prove real STT accuracy, real SQL quality, real Snowflake execution, or production observability. Those are later gates.

## Current Contract Behavior

- `POST /api/query` is text-only and returns `202` with `status: processing`.
- `/ws/pipeline` drives progress, clarification, and result-ready UI state.
- `/api/result/{turn_id}` remains as a read-model endpoint after `result_ready`; the frontend does not poll it.
- `SESSION_STORE=memory` is the default and reports Redis as `local_stub`.
- `SESSION_STORE=redis` enables the Redis adapter and requires `UPSTASH_REDIS_URL`.
- `/health` reports Redis as `ok` or `degraded` only when Redis mode is enabled. Postgres remains `not_configured`.

## Current Demo Warehouse

The local fake providers now use the DB team's e-commerce schema:

- `customers`
- `orders`
- `order_items`
- `products`
- `sellers`
- `order_payments`
- `order_reviews`
- `geolocation`

The corrected demo schema is in `db/demo_warehouse/001_ecommerce_schema.sql`.
