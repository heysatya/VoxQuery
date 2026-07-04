# Gate 4 Execution Contract — Voice Subsystem STT

**Scope**: Events emitted during Gate 4 (Deepgram streaming, Slices 2–5).  
**Status**: Active — defines what each slice must emit before the gate closes.

> No metric targets are set here. Targets require baseline data. They will be defined
> after the first 50 pilot queries are observed in the Supabase turns table.

---

## Events

Four events. Each has a fixed name, a tier, a required field set, and an assigned slice.

### `stt.mic.permission` — tier 3 (business)

| Field | Type | Value |
|---|---|---|
| `outcome` | string | `"granted"` \| `"denied"` \| `"unavailable"` |
| `session_id` | string | WS session identifier or `"none"` if pre-connection |

**Emitted by**: Frontend `app/page.tsx` (Slice 2), on `getUserMedia` resolution.  
**Why**: Measures voice feature adoption. A high `denied` rate signals a UX or trust problem — not an engineering bug.

---

### `stt.ws.lifecycle` — tier 2 (ai_quality)

| Field | Type | Value |
|---|---|---|
| `action` | string | `"opened"` \| `"closed"` |
| `close_code` | int | Present on `"closed"` only — WebSocket close code |
| `session_id` | string | |
| `tenant_id` | string | |

**Emitted by**: Backend `app/api/ws_audio.py` (Slice 2 for open, Slice 4 for close).  
**Why**: WS connection reliability. Close code 1000 = clean close. Other codes signal
relay errors or client disconnects that need investigation.  
**Must not contain**: Deepgram API key, Clerk token, or any credential.

---

### `stt.transcript.final` — tier 2 (ai_quality)

| Field | Type | Value |
|---|---|---|
| `confidence` | float | Deepgram `channel.alternatives[0].confidence` (0.0–1.0) |
| `latency_ms` | int | Elapsed ms from WS open to this event |
| `provider` | string | `"deepgram"` \| `"fake"` |
| `session_id` | string | |
| `tenant_id` | string | |

**Emitted by**: Backend `app/api/ws_audio.py` or `app/core/stt.py` (Slice 4).  
**Why**: The primary AI quality signal for the voice pipeline. This is the data point
that will define the `stt.confidence.p50` target once 50 pilot queries exist.  
**`fake` provider emits `confidence: 0.97`** — distinguishable from real Deepgram data.

---

### `stt.error` — tier 2 (ai_quality)

| Field | Type | Value |
|---|---|---|
| `error_type` | string | `"deepgram_connection"` \| `"relay"` \| `"idle_timeout"` |
| `session_id` | string | |
| `tenant_id` | string | |

**Emitted by**: Backend `app/api/ws_audio.py` (Slice 4).  
**Why**: Error rate by type distinguishes infrastructure failures (connection) from
product failures (relay logic bugs) from UX failures (idle timeout — user left mic open).  
**Must not contain**: Deepgram API key, stack trace, or internal provider URL.

---

## Telemetry path

```
Route handler / stt.py
    → app.state.telemetry.bind(session_id=..., tenant_id=...)
        → emit("stt.*", tier=..., **fields)
            → JSON line to stdout
```

At pilot readiness: stdout → Railway log aggregation → queryable. Supabase turns table
carries the same data at turn completion via `TurnRecord` persistence (Gate 5 task).

---

## Gate 4 closure conditions

Gate 4 closes when all five are true:

1. All four events above are emitted and visible in terminal output during Slice 5 smoke test.
2. `stt.transcript.final` carries a real Deepgram confidence score (not `0.97` fake constant).
3. `stt.error` is absent from a clean smoke test run.
4. No credential appears in any emitted event payload (manual inspection of smoke test output).
5. All 75 backend tests pass, all 15 frontend tests pass.

---

## What this is NOT

- Not a monitoring alert config (alerts come when we have a production environment).
- Not a Langfuse integration spec (Langfuse is for LLM traces; add at Gate 5/6 when real LLM calls exist).
- Not a database schema (TurnRecord → Postgres persistence is a Gate 5 prerequisite, not Gate 4).
