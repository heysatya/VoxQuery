# VoxQuery Interface Contracts Addendum

**Companion to:** VoxQuery Engineering Spec — Subsystems 4.1 · 4.2 · 4.3  
**Covers:** WebSocket message schemas · REST API contracts · HTTP error envelope  
**Status:** Required before Day 6 (Deepgram proxy implementation)

---

## 1. WebSocket — Audio Relay (`/ws/audio`)

One WebSocket connection per recording session. Opened on Record click, closed on final transcript receipt or error.

### Auth

Connection established with Clerk JWT as a query parameter (WebSocket does not support Authorization headers):

```
wss://api.voxquery.com/ws/audio?token=<clerk_jwt>&session_id=<uuid>
```

Backend validates JWT in the `ws_audio.py` connection handler before accepting the connection. Reject with close code `4001` if token is missing or invalid.

### Browser → Backend (upstream frames)

**Audio frames** — sent continuously while recording:

```
Binary frames — raw PCM audio bytes
Encoding:    Linear PCM, 16-bit, 16kHz, mono
Chunk size:  ~100ms of audio per frame
```

No JSON wrapper. Raw binary only. The relay passes these directly to Deepgram without inspection.

**Control message — stop recording:**

```json
{ "type": "stop_recording" }
```

Sent when the user clicks Stop. Signals the backend to send `CloseStream` to Deepgram and wait for the final transcript.

### Backend → Browser (downstream frames)

All downstream messages are JSON text frames.

**Interim transcript** — sent on every Deepgram interim result:

```json
{
  "type":       "interim_transcript",
  "text":       "string — partial transcript text",
  "is_final":   false
}
```

**Final transcript** — sent once, after Deepgram `is_final: true`:

```json
{
  "type":           "final_transcript",
  "text":           "string — complete transcript",
  "confidence":     0.97,
  "is_final":       true
}
```

`confidence` is Deepgram's mean word confidence for the final result. Stored as `stt_confidence` / `deepgram_confidence_raw` in the pipeline.

**Error** — sent when the relay encounters a non-recoverable error:

```json
{
  "type":    "error",
  "code":    "deepgram_unavailable | auth_failed | relay_error",
  "message": "string — shown in toast; see §3 error codes"
}
```

After sending an `error` frame, the backend closes the WebSocket. The frontend transitions `recordingState → idle` and preserves any partial transcript.

**WebSocket close codes:**

| Code | Meaning |
|---|---|
| 1000 | Normal close — final transcript delivered |
| 1011 | Internal server error — relay_error |
| 4001 | Auth failed — invalid or missing JWT |
| 4002 | Session not found — session_id not in Redis |
| 4003 | Already recording — duplicate connection rejected |

---

## 2. WebSocket — Pipeline Events (`/ws/pipeline`)

A second, persistent WebSocket connection carries server-sent pipeline progress events for the duration of a browser session. Opened on page load, kept alive across turns.

### Auth

Same pattern as audio relay:

```
wss://api.voxquery.com/ws/pipeline?token=<clerk_jwt>&session_id=<uuid>
```

### Backend → Browser only (downstream only)

The browser never sends frames on this connection. All frames are JSON text.

**Pipeline stage progress:**

```json
{
  "type":       "pipeline_progress",
  "stage":      "rag_retrieval | sql_generation | sql_validation | snowflake_executing | rendering",
  "turn_id":    "uuid",
  "elapsed_ms": 340
}
```

Triggered by real Orchestrator events — not polling. Not setTimeout. Each stage fires exactly once when it starts. Frontend uses these to advance the progress indicator.

**Clarification request** — sent when Phase 4A triggers:

```json
{
  "type":     "clarification_request",
  "turn_id":  "uuid",
  "question": "string — question shown to user",
  "options":  ["string", "string", "string"],
  "timeout_seconds": 30
}
```

Frontend renders `ClarificationPanel` on receipt. Starts the 30-second countdown.

**Clarification timeout warning** — sent at 10 seconds remaining:

```json
{
  "type":           "clarification_timeout_warning",
  "turn_id":        "uuid",
  "seconds_remaining": 10
}
```

**Result ready:**

```json
{
  "type":              "result_ready",
  "turn_id":           "uuid",
  "confidence_tier":   "High | Medium | Low",
  "chart_type":        "bar | line | table | stat",
  "chart_rationale":   "string",
  "result_json": {
    "columns":           ["string"],
    "row_count":         142,
    "aggregate_summary": "string"
  },
  "proactive_questions": ["string", "string", "string"],
  "from_cache":          false
}
```

`result_json` here is result shape only — never raw rows. Raw rows are fetched separately via the REST result endpoint (§3.4) using `turn_id`.

**Pipeline error:**

```json
{
  "type":      "pipeline_error",
  "turn_id":   "uuid",
  "code":      "string — see error code table §3",
  "message":   "string — shown to user"
}
```

**Session expired:**

```json
{
  "type":    "session_expired",
  "reason":  "ttl_exceeded | new_conversation"
}
```

Frontend clears local session state and issues a new session on next query.

---

## 3. REST API

Base URL: `https://api.voxquery.com`  
All endpoints require `Authorization: Bearer <clerk_jwt>` header.  
All request and response bodies are `application/json`.  
All timestamps are ISO-8601 UTC.

### 3.1 `POST /api/session`

Create a new session. Called on page load (no existing `session_id` in `sessionStorage`) and on "New Conversation" click.

**Request:**
```json
{
  "tenant_id": "uuid"
}
```

`tenant_id` is read from the Clerk JWT claims — do not trust the request body value. The body value is for routing only; backend validates it matches the JWT.

**Response `201`:**
```json
{
  "session_id":      "uuid",
  "conversation_id": "uuid",
  "expires_at":      "ISO-8601 — now + SESSION_TTL_SECONDS"
}
```

`session_id` is stored in `sessionStorage` immediately on receipt. Never `localStorage`.

**Response `401`:** Invalid or expired JWT — see error envelope §3.6.  
**Response `409`:** Active session already exists for this user — return existing session_id.

---

### 3.2 `POST /api/query`

Submit a query for pipeline execution. Text input path only — voice input goes through `/ws/audio` then triggers the pipeline internally.

**Request:**
```json
{
  "session_id":    "uuid",
  "submitted_text": "string — max 500 characters",
  "input_modality": "text"
}
```

`input_modality` is always `"text"` here. Voice queries are dispatched internally from the audio WebSocket relay.

**Response `202 Accepted`:**
```json
{
  "turn_id":    "uuid",
  "status":     "processing"
}
```

Pipeline executes asynchronously. Progress and result arrive via `/ws/pipeline`. Frontend should not poll — wait for WebSocket events.

**Response `400`:** `submitted_text` empty or > 500 characters.  
**Response `409`:** Pipeline already in flight for this session.  
**Response `401`:** Auth failure.

---

### 3.3 `POST /api/clarification`

Submit the user's clarification option selection.

**Request:**
```json
{
  "session_id":    "uuid",
  "turn_id":       "uuid",
  "selection":     "string — exact text of the option selected",
  "resolution_type": "option_selected | escaped"
}
```

`resolution_type: "escaped"` is sent when the user clicks "None of these — let me rephrase". `selection` is `null` for escaped.

**Response `200`:**
```json
{
  "status": "received",
  "turn_id": "uuid"
}
```

Pipeline resumes immediately. Result arrives via `/ws/pipeline`.

**Response `404`:** `turn_id` not found or clarification already resolved.  
**Response `409`:** Clarification timeout already expired for this `turn_id`.

---

### 3.4 `GET /api/result/{turn_id}`

Fetch the full result for a completed turn, including the raw chart data needed for rendering and CSV export.

**Response `200`:**
```json
{
  "turn_id":         "uuid",
  "chart_type":      "bar | line | table | stat",
  "chart_rationale": "string",
  "confidence_tier": "High | Medium | Low",
  "generated_sql":   "string",
  "result": {
    "columns":    ["string"],
    "rows":       [["value", "value"]],
    "row_count":  142
  },
  "tts_text":        "string — the narrative summary for TTS",
  "from_cache":      false
}
```

`result.rows` contains the actual data for chart rendering and CSV export. This is the only endpoint where row data is returned to the browser. It does not cross the LLM boundary. Frontend fetches this after receiving `result_ready` on the pipeline WebSocket.

`tts_text` is the plain text the frontend passes to the TTS player. It is the `aggregate_summary` from 4.9 Storytelling, formatted for speech.

**Response `404`:** Turn not found.  
**Response `403`:** Turn belongs to a different user or tenant.  
**Response `202`:** Turn still processing — frontend should not have called this yet.

---

### 3.5 `POST /api/feedback`

Submit thumbs-down feedback for a completed turn.

**Request:**
```json
{
  "session_id": "uuid",
  "turn_id":    "uuid",
  "rating":     -1
}
```

`rating` is always `-1` at MVP. Thumbs-up is not instrumented (absence of thumbs-down is the positive signal).

**Response `200`:**
```json
{ "status": "recorded" }
```

**Response `404`:** Turn not found.  
**Response `409`:** Feedback already submitted for this turn.

---

### 3.6 `GET /health`

Railway health probe. No auth required.

**Response `200`:**
```json
{
  "status":   "ok",
  "redis":    "ok | degraded",
  "postgres": "ok | degraded",
  "version":  "string — git SHA"
}
```

`degraded` means the dependency is reachable but slow (> 100ms ping). The health endpoint does not fail on degraded dependencies — Railway should not restart a healthy process because Redis is slow. It returns `200` with the degraded status so monitoring can observe it.

---

## 4. HTTP Error Response Envelope

All REST error responses use this shape. No exceptions.

```json
{
  "error": {
    "code":    "string — machine-readable; see table below",
    "message": "string — safe to display to users",
    "detail":  "string | null — internal detail; never displayed to users; only in non-production"
  }
}
```

`detail` is `null` in production. Present in `development` and `staging` for debugging. Never log `detail` to Langfuse — it may contain query context.

### Error codes

| Code | HTTP status | User-facing `message` |
|---|---|---|
| `auth_invalid` | 401 | "Your session has expired. Please sign in again." |
| `auth_missing` | 401 | "Authentication required." |
| `session_not_found` | 404 | "Session unavailable — please refresh." |
| `session_expired` | 410 | "Your session has expired. Start a new conversation." |
| `query_empty` | 400 | "Please enter a question before submitting." |
| `query_too_long` | 400 | "Your question is too long. Please shorten it and try again." |
| `pipeline_in_flight` | 409 | "A query is already running. Please wait for it to complete." |
| `clarification_expired` | 409 | "That clarification has expired. Please submit your question again." |
| `clarification_not_found` | 404 | "Clarification not found." |
| `turn_not_found` | 404 | "Result not found." |
| `turn_forbidden` | 403 | "You don't have access to this result." |
| `turn_processing` | 202 | "Still processing — please wait." |
| `feedback_duplicate` | 409 | "Feedback already recorded for this query." |
| `warehouse_timeout` | 504 | "Query timed out — the data warehouse may need a moment to wake up. Try again in 30 seconds." |
| `warehouse_error` | 502 | "The data warehouse returned an error. Check that your schema access is configured correctly." |
| `sql_generation_failed` | 422 | "I couldn't generate a valid query even after clarification. Try rephrasing or use the text input." |
| `llm_unavailable` | 503 | "The AI service is temporarily unavailable. Please try again in a moment." |
| `internal_error` | 500 | "Something went wrong. Please try again." |

`warehouse_timeout` and `sql_generation_failed` match the user-facing strings in Engineering Spec §12. All other strings in §12 are toast messages triggered by WebSocket events, not REST errors — they are consistent with this table but arrive via a different channel.

---

## 5. Clarification Payload — Full Round-Trip

This section shows the complete data flow for a clarification event, combining WebSocket and REST into a single readable sequence.

```
1. Backend sends on /ws/pipeline:
   {
     "type":     "clarification_request",
     "turn_id":  "abc-123",
     "question": "Which revenue metric did you mean?",
     "options":  ["Gross revenue", "Net revenue", "Recognised revenue"],
     "timeout_seconds": 30
   }

2. Frontend renders ClarificationPanel. Starts 30s countdown.
   At 10s remaining, backend sends clarification_timeout_warning.

3a. User selects "Net revenue":
   POST /api/clarification
   {
     "session_id":      "sess-456",
     "turn_id":         "abc-123",
     "selection":       "Net revenue",
     "resolution_type": "option_selected"
   }
   → 200 { "status": "received", "turn_id": "abc-123" }
   → Pipeline resumes → result_ready arrives on /ws/pipeline

3b. User clicks "None of these — let me rephrase":
   POST /api/clarification
   {
     "session_id":      "sess-456",
     "turn_id":         "abc-123",
     "selection":       null,
     "resolution_type": "escaped"
   }
   → 200 { "status": "received", "turn_id": "abc-123" }
   → Pipeline halts. Turn not written. Input field pre-populated with original query.

3c. 30 seconds pass with no user action:
   Backend fires QUERY_SUBMITTED state transition internally.
   Backend sends on /ws/pipeline:
   {
     "type":    "pipeline_progress",
     "stage":   "sql_generation",
     "turn_id": "abc-123",
     "elapsed_ms": 30000
   }
   → Pipeline proceeds at original confidence tier.
   → No frontend action required for timeout — pipeline continues automatically.
```

---

## 6. Frontend State Contract — What the Browser Must Track

The browser maintains this state object in React context (not `localStorage`, not `sessionStorage` beyond `session_id`):

```typescript
interface VoxQueryClientState {
  // Session
  sessionId:      string | null;        // from sessionStorage
  conversationId: string | null;

  // Recording
  micPermission:  'unknown' | 'granted' | 'denied' | 'prompt';
  recordingState: 'idle' | 'connecting' | 'recording' | 'processing';
  partialTranscript: string;            // live Deepgram interim text
  submittedText:  string;               // editable before submit

  // Pipeline
  pipelineInFlight: boolean;
  currentTurnId:    string | null;
  pipelineStage:    string | null;      // last received stage from pipeline_progress

  // Clarification
  clarificationPending: boolean;
  clarificationQuestion: string | null;
  clarificationOptions:  string[];
  clarificationSecondsRemaining: number;

  // Result (cleared on new query)
  lastResult: {
    turnId:          string;
    confidenceTier:  'High' | 'Medium' | 'Low';
    chartType:       string;
    chartRationale:  string;
    resultData:      ResultPayload | null;  // from GET /api/result/:turn_id
    proactiveQuestions: string[];
  } | null;
}
```

`session_id` is the only value persisted to `sessionStorage`. Everything else lives in React state and is reset on page load. On page load, if `sessionStorage` contains a valid `session_id`, the frontend opens the `/ws/pipeline` connection and resumes. If not, it calls `POST /api/session` first.

---

## 7. Deployment Topology

```
Browser (Vercel CDN)
  │
  ├── HTTPS/WSS ──→ Railway (single instance, single region)
  │                   ├── FastAPI process
  │                   │     ├── /ws/audio       → Deepgram WS (outbound)
  │                   │     ├── /ws/pipeline    → browser (downstream only)
  │                   │     ├── /api/*          → REST endpoints
  │                   │     ├── core/session.py → Upstash Redis (TLS)
  │                   │     ├── llm/claude.py   → Anthropic API (HTTPS)
  │                   │     └── warehouse/snowflake.py → Snowflake (JDBC/HTTPS)
  │                   └── async writes → Supabase Postgres (TLS)
  │
  └── Langfuse SDK (in-process) → Langfuse Cloud (HTTPS, async, non-blocking)
```

Single Railway instance. Single region. No load balancer. No sticky sessions required at MVP. WebSocket connections are direct — no proxy that would drop them on idle.

**Vercel Preview Deployments must be disabled for pilot sessions.** Preview deployments run on different subdomains. `sessionStorage` is scoped to origin — a user on `preview-abc.vercel.app` cannot resume a session created on `app.voxquery.com`. Disable preview deployments in Vercel project settings before onboarding the pilot user.

---

*VoxQuery Interface Contracts Addendum*  
*Read alongside VoxQuery Engineering Spec — Subsystems 4.1 · 4.2 · 4.3*
