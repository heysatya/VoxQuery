# VoxQuery Voice Subsystem Implementation Roadmap

## Gate 0 - Local Stubbed E2E Slice

Status: complete.

Acceptance criteria:

- Backend and frontend run locally without credentials.
- Text fallback submits through the same query path as fake voice.
- Ambiguous revenue query triggers clarification.
- Explicit net revenue query completes directly.
- Result SQL references e-commerce demo warehouse tables.
- Backend and frontend tests pass.

## Gate 1 - Pre-Redis Contract Hardening

Status: complete after the hardening verification suite passes.

Acceptance criteria:

- `POST /api/query` returns `processing`; observable progress comes from `/ws/pipeline`.
- Clarification request/options render from backend pipeline events, not hardcoded frontend text.
- Clarification timeout warning updates the visible countdown.
- Fake voice uses `/ws/audio` while remaining credential-free.
- Stale clarification timeout is handled by session/pipeline lifecycle.
- Health does not report fake Redis/Postgres dependencies as real `ok` services.
- Dependency audit has no moderate/high/critical frontend vulnerabilities.
- Backend, frontend, and production build verification pass.

## Gate 2 - Redis Session Store

Acceptance criteria:

- In-memory session store remains available for tests.
- Redis adapter implements the same session-store contract.
- Session keys follow `session:{tenant_id}:{session_id}`.
- TTL refreshes on turn write.
- Resolved entities are preserved through history truncation.
- Redis failures return the spec-defined session error.

## Gate 3 - Clerk Auth

Acceptance criteria:

- `AUTH_MODE=fake` remains development/test only.
- Clerk JWT validation works for REST and WebSocket connections.
- Tenant and user claims are enforced.
- Mismatched tenant requests fail.
- Production/staging fail startup if fake auth is enabled.

## Gate 4 - Real Deepgram Streaming

Acceptance criteria:

- Browser microphone flow requests permission clearly.
- Audio is converted to 16-bit 16kHz mono PCM.
- `/ws/audio` relays binary frames to Deepgram.
- Interim transcripts update live.
- Final transcript includes confidence.
- Client disconnect closes the upstream Deepgram connection.
- Text fallback still works if audio fails.

## Gate 5 - Supabase/Postgres Audit Writes

Acceptance criteria:

- App metadata migration is applied separately from demo warehouse schema.
- Turns are written asynchronously.
- Clarifications are written asynchronously.
- Feedback updates quality flag.
- Raw warehouse rows are not stored in app metadata tables.

## Gate 6 - Langfuse Observability

Acceptance criteria:

- One trace exists per turn.
- Required spans are emitted:
  - `stt_capture`
  - `memory_retrieval`
  - `history_injection`
  - `ambiguity_detection`
  - `confidence_computation`
- Thumbs-down feedback emits a score event.
- Langfuse failures do not break the user flow.

## Gate 7 - Real RAG / SQL / Snowflake Integration

Acceptance criteria:

- Schema-aware retrieval uses the demo/customer warehouse metadata.
- SQL generation stays behind the model-agnostic adapter.
- Generated SQL passes validation before execution.
- Snowflake connector stays behind the warehouse interface.
- Read-only enforcement happens before opening a warehouse connection.
- Result shapes feed chart selection and storytelling without raw rows crossing the LLM boundary.
