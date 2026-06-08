# VoxQuery Engineering Spec - Subsystems 4.1 · 4.2 · 4.3

**Scope:** MVP pilot - single enterprise tenant, desktop-first, Snowflake warehouse  
**Status:** Engineering reference - do not modify without explicit architecture review

---

## 1. What We Are Building

A voice-first query interface for a single enterprise executive. The executive speaks a question, sees a transcript, submits it, and receives a chart with a SQL result and a confidence label. They can correct the transcript before submitting. They can answer a clarification question if the system is unsure what they meant. Their conversation context carries across turns within a session.

Three subsystems are in scope:

- **4.1 Voice Input** - audio capture, Deepgram relay, transcript display
- **4.2 Clarification Loop** - ambiguity detection, confidence scoring, clarification UI
- **4.3 Conversation Memory** - Redis session, history injection, Postgres audit write

Everything else (SQL generation, schema RAG, Snowflake execution, TTS, chart rendering) is owned by other specs. This spec integrates with those subsystems at defined interfaces and stubs them during development.

---

## 2. Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 + TypeScript - Vercel |
| Backend | FastAPI - Python 3.12 - Railway (single instance) |
| STT | Deepgram `nova-2` via FastAPI WebSocket relay |
| LLM | Anthropic `claude-sonnet-4-20250514` |
| Session store | Upstash Redis (TLS + encryption at rest) |
| Database | Supabase Postgres 16 + pgvector |
| Auth | Clerk (SSO / JWT) |
| Observability | Langfuse |
| SQL validation | `sqlglot` |

**Nothing else.** No API gateway. No message queue. No Kubernetes. One Railway instance is the correct infrastructure for one pilot tenant.

---

## 3. Module Map

All backend modules live in the single FastAPI process. These names are canonical - use them from day one.

```
app/
  api/
    ws_audio.py          # 4.1 - Deepgram proxy relay endpoint
    pipeline.py          # Pipeline orchestrator entry point (Orchestration spec owns)
  core/
    stt.py               # 4.1 - STT abstraction layer (Deepgram implementation)
    ambiguity.py         # 4.2 - Deterministic signal detector
    confidence.py        # 4.2 - Composite score computation
    session.py           # 4.3 - Redis read/write/TTL
  llm/
    adapter.py           # Abstract LLM interface - model-agnostic (PRD §8 hard constraint)
    claude.py            # Anthropic Claude implementation of adapter
  warehouse/
    connector.py         # Abstract WarehouseConnector interface (PRD §3 hard constraint)
    snowflake.py         # Snowflake implementation of connector
  middleware/
    auth.py              # Clerk JWT validation (runs before all pipeline code)
```

`llm/adapter.py` and `warehouse/connector.py` are abstract interfaces, not implementations. No Claude-specific API constructs (system prompt formatting, tool use schema) appear outside `llm/claude.py`. No Snowflake-specific connection code appears outside `warehouse/snowflake.py`. These two constraints are PRD requirements for enterprise InfoSec compliance and multi-warehouse roadmap.

Frontend modules (Next.js):

```
components/
  VoiceInput.tsx         # 4.1 - Push-to-talk state machine + transcript field
  ClarificationPanel.tsx # 4.2 - Clarification options + escape
  ResultPanel.tsx        # Result + confidence tier + SQL panel (Orchestration spec)
```

---

## 4. Interfaces - What Each Module Receives and Returns

### 4.1 → Orchestrator

`ws_audio.py` delivers the final transcript and metadata to the pipeline entry point:

```json
{
  "submitted_text":  "string - final text after user edits",
  "raw_transcript":  "string - Deepgram output before edits",
  "input_modality":  "voice | text",
  "stt_confidence":  "float - mean word confidence (null for text path)",
  "session_id":      "string - from browser sessionStorage"
}
```

`input_modality` is an observability tag only. The pipeline treats text and voice identically from this point.

### Orchestrator → 4.2 (inputs consumed)

| Field | Source | Type |
|---|---|---|
| `rag_score` | 4.4 Schema RAG | float 0–1 |
| `validation_passed` | 4.5 SQL Gen | bool |
| `llm_self_confidence` | 4.5 SQL Gen structured output | float 0–1 |
| `schema_chunks` | 4.4 Schema RAG | list |
| `user_role` | Auth middleware / session | string |

### 4.2 → Orchestrator

```json
{
  "composite_score":         "float",
  "confidence_tier":         "High | Medium | Low",
  "clarification_triggered": "bool",
  "clarification_question":  "string | null",
  "clarification_options":   ["string"],
  "ambiguity_signals":       ["string - signal type from taxonomy"],
  "resolved_entity": {
    "term":       "string",
    "resolution": "string - schema reference"
  }
}
```

### 4.3 → Orchestrator (session context block - injected into SQL prompt Layer 2)

```json
{
  "history": [
    {
      "user_query":     "string",
      "generated_sql":  "string",
      "result_shape": {
        "columns":           ["string"],
        "chart_type":        "string",
        "row_count":         "int",
        "aggregate_summary": "string - no raw row values"
      },
      "confidence_tier": "string",
      "quality_flag":    "ok | low"
    }
  ],
  "resolved_entities": {
    "<term>": {
      "resolution":       "string",
      "resolved_at_turn": "int",
      "option_selected":  "string"
    }
  },
  "truncated":     "bool",
  "turns_dropped": "int"
}
```

### Orchestrator → 4.3 (inputs consumed per turn)

| Field | Source |
|---|---|
| `validated_sql` | 4.5 SQL Gen |
| `chart_type` | 4.6 Chart Selector |
| `chart_rationale` | 4.6 Chart Selector - one-line explanation shown beneath chart (e.g. "Showing as line chart - time series detected on date column") |
| `aggregate_summary` | 4.9 Storytelling |
| `confidence_tier` | 4.2 |
| `thumbs_down` event | Frontend |

---

## 5. State Machines

### 5.1 Voice input (browser-side, 4.1)

```
microphonePermission: unknown | granted | denied | prompt
  unknown  → granted | denied | prompt   (on session load: permission check)
  prompt   → granted | denied            (user responds to browser prompt)
  granted  → denied                      (browser reports revocation)
  denied is terminal unless user changes browser settings

recordingState: idle | connecting | recording | processing
  idle       → connecting    (record click; permission = granted)
  connecting → recording     (Deepgram WS established)
  connecting → idle          (connection failed; toast)
  recording  → processing    (stop click)
  recording  → idle          (device disconnect or WS drop; toast; preserve transcript)
  processing → idle          (final transcript received; Submit activates)
  processing → idle          (retries exhausted; toast; preserve partial transcript)

pipeline-in-flight (UI state, not a recordingState value):
  triggered by: Submit click (non-empty transcript; no active recording)
  → Submit disabled; input field locked
  cleared by:   result rendered OR pipeline error
```

### 5.2 Clarification loop (pipeline-level, 4.2)

```
CONFIDENCE_EVALUATION
  score ≥ 0.65                       → SQL_EXECUTION
  score < 0.65                       → CLARIFICATION_PENDING

CLARIFICATION_PENDING
  executive selects option           → CLARIFICATION_RESOLVED
  "None of these - let me rephrase"  → CLARIFICATION_ESCAPED
  30-second inactivity timeout       → QUERY_SUBMITTED

CLARIFICATION_RESOLVED             → SQL_REGENERATION

SQL_REGENERATION
  score ≥ 0.50                       → SQL_EXECUTION
  score < 0.50                       → ERROR_STATE

QUERY_SUBMITTED                    → SQL_EXECUTION
  (original query proceeds; pre-clarification composite_score and confidence_tier used)

CLARIFICATION_ESCAPED              → [terminal]
  (pipeline halts; turn not written to history; original query restored to input field)

SQL_EXECUTION                      → (Orchestration spec)
ERROR_STATE                        → (structured error to UI; turn not written)
```

State name rules: these names are canonical. The Orchestration spec must use them without renaming.

### 5.3 Session memory lifecycle (4.3)

```
[page load]    → SESSION_CREATED   (new session_id in sessionStorage)
SESSION_CREATED → ACTIVE           (first query submitted)
ACTIVE          → ACTIVE           (each turn - TTL extended; history appended)
ACTIVE          → ACTIVE           (token budget exceeded - truncate oldest turns;
                                    resolved_entities always preserved)
ACTIVE          → CLEARED          ("New Conversation" click)
ACTIVE          → ORPHANED         (browser refresh - sessionStorage cleared)
ACTIVE          → EXPIRED          (inactivity > 4h TTL)
CLEARED         → SESSION_CREATED  (new session_id issued)
ORPHANED        → [terminal]       (Redis TTL expires independently)
EXPIRED         → [terminal]       (Redis releases key)
```

---

## 6. Per-Turn Pipeline Sequence

The sequence below is the authoritative execution order for a single turn. Phase ownership is noted.

```
PHASE 1 - INPUT (4.1)
1.  Record click → idle → connecting → recording
2.  Audio frames relay: browser WS → /ws/audio → Deepgram WS
3.  Interim transcripts relay back; transcript field updates in real time
4.  Stop click → Deepgram stream-close → final transcript → processing → idle
5.  Executive reviews, edits if needed, clicks Submit
6.  Dispatch: submitted_text, raw_transcript, input_modality, stt_confidence, session_id

PHASE 2 - SESSION READ (4.3)
7.  core/session.py reads Redis by session_id
    → failure: halt; return "Session unavailable - please refresh."
8.  Token budget check: count resolved_entities + history tokens
    → if over budget: drop oldest turns; resolved_entities always kept
9.  session_context_block assembled for prompt injection

PHASE 3 - RAG + SQL GENERATION (4.4, 4.5 - stubs)
10. 4.4 Schema RAG: submitted_text + session_context_block → schema_chunks, rag_score
11. 4.5 SQL Gen: submitted_text + schema_chunks + session_context_block
    → sql, llm_self_confidence, validation_passed

PHASE 4 - CONFIDENCE EVALUATION (4.2)
12. core/ambiguity.py: submitted_text + schema_chunks → ambiguity_signals (< 10ms)
    → suppress signals for entities already in resolved_entities
    → suppressed signals logged in Langfuse; not passed to confidence.py
13. core/confidence.py: rag_score + validation_passed + llm_self_confidence
    + post-suppression ambiguity signal penalties → composite_score, confidence_tier
14. composite_score ≥ 0.65 → PHASE 5
    composite_score < 0.65 → PHASE 4A

PHASE 4A - CLARIFICATION (4.2, conditional)
14a. Clarification LLM call: highest-severity signal → question + 2–4 options (JSON)
     → validate options against schema_chunks; remove any referencing entities not in chunks
     → if < 2 valid options remain: suppress clarification; proceed to PHASE 5
     → if ≥ 2 valid options: display to UI; state: CLARIFICATION_PENDING
14b. Executive responds:
     → option selected: write resolved_entity to Redis (≤ 20 entries; evict oldest if exceeded)
       state: CLARIFICATION_RESOLVED → SQL_REGENERATION
       re-run phases 3–4 with resolved_entity injected; post-clarification threshold: 0.50
       if score < 0.50: ERROR_STATE; structured error; turn not written
     → escape: state: CLARIFICATION_ESCAPED; pipeline halts; turn not written
     → 30s timeout: state: QUERY_SUBMITTED; proceed to PHASE 5 at original score

PHASE 5 - SQL EXECUTION (4.5 - stub)
15. Redis cache check: hash(normalised SQL + tenant_id)
    → hit: return cached result
    → miss: Snowflake executes (30s timeout); result cached on return
    → 4.5 enforces 10,000 row hard cap via LIMIT injection if not present
    → 4.5 detects implicit cross-join duplicate rows post-execution; flags to user
      with offer to re-run with DISTINCT (PRD §4.5 AC - 4.5 spec owns this)
    → 4.5 retries once with error correction prompt on sqlglot validation failure
      before surfacing an error to the pipeline (PRD §4.5 AC - 4.5 spec owns this)

PHASE 6 - OUTPUT (4.6, 4.7, 4.9 - stubs, run in parallel)
16. Chart Selector → chart_type + chart_rationale (one-line auto-select explanation)
17. TTS generation + Storytelling LLM call (parallel, non-blocking)
18. Chart renders; confidence_tier displayed; SQL panel collapsed by default
    → Medium confidence: show inline caveat: "I'm moderately confident - the query
      joined tables I'm less familiar with. Review the SQL before actioning."
18a. Proactive question suggestions: LLM call (4.6/Orchestration spec owns) generates
    2–3 follow-up questions from result shape + schema context + user_role; displayed
    after chart renders. This spec contributes user_role and session context as inputs.

PHASE 7 - SESSION WRITE (4.3)
19. format_turn_for_injection() → new history entry appended to Redis
    resolved_entities updated if clarification resolved
    Redis TTL extended (settings.SESSION_TTL_SECONDS)
20. Async fire-and-forget: turn row written to Postgres turns table

PHASE 8 - POST-RENDER FEEDBACK (4.3, async)
21. Thumbs-down (if fired):
    → Redis: quality_flag ok → low for this turn_id
    → Postgres: async update same row
    → Langfuse: score event tagged with turn_id, composite_score, confidence_tier
```

---

## 7. Data Schemas

### 7.1 Redis session object (canonical - freeze before writing session code)

```json
{
  "session_id":           "uuid",
  "user_id":              "uuid",
  "tenant_id":            "uuid",
  "conversation_id":      "uuid",
  "turn_count":           0,
  "last_interaction_ts":  "ISO-8601 - updated on each successful turn write",
  "snowflake_role":       "string - cached from user_snowflake_roles at session creation",
  "clarification_state":  null,
  "history": [
    {
      "turn_index":              0,
      "turn_id":                 "uuid - same as Postgres turns.id",
      "user_query":              "string",
      "generated_sql":           "string",
      "result_shape": {
        "columns":           ["string"],
        "chart_type":        "string",
        "row_count":         0,
        "aggregate_summary": "string"
      },
      "confidence_tier":         "High | Medium | Low",
      "quality_flag":            "ok | low",
      "clarification_triggered": false,
      "input_modality":          "voice | text"
    }
  ],
  "resolved_entities": {
    "<term>": {
      "resolution":       "string",
      "resolved_at_turn": 0,
      "option_selected":  "string"
    }
  }
}
```

`clarification_state` is `null` when idle. When a clarification is pending:
```json
{ "pending": true, "issued_at": "ISO-8601", "turn_id": "uuid" }
```

On session resume: if `pending: true` and `now - issued_at > 30s`, treat as expired - reset to `null`, proceed to `SQL_EXECUTION` at original confidence tier per Phase 4A timeout path.

Redis key pattern: `session:{tenant_id}:{session_id}`

The session object is read and written atomically (full JSON string). No partial Redis hash updates. If `resolved_entities` would exceed 20 entries, evict the entry with the lowest `resolved_at_turn` before writing.

### 7.2 Postgres tables (create on Day 1 - schema is frozen)

**`tenants`**

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | text | Organisation name |
| `created_at` | timestamptz | |

Note: `snowflake_dsn` lives in `tenant_connections` (encrypted), not here - keeping sensitive credentials in a separate table with tighter access control.

**`users`**

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | mirrors Clerk user ID |
| `tenant_id` | UUID FK → tenants.id | |
| `email` | text UNIQUE | from Clerk SSO |
| `role` | text | `viewer` or `admin` |
| `created_at` | timestamptz | |

Clerk is the identity authority. This table is a local mirror for FK integrity, role lookup, and audit. Do not duplicate Clerk's auth logic here.

**`turns`**

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | = `turn_id` in Redis history |
| `conversation_id` | UUID FK | links to `conversations` |
| `user_id` | UUID | from Clerk JWT |
| `tenant_id` | UUID | from Clerk JWT |
| `user_input` | text | = `submitted_text` |
| `raw_transcript` | text | Deepgram output before edits |
| `deepgram_confidence_raw` | float | mean word confidence from Deepgram |
| `generated_sql` | text | validated SQL executed |
| `result_json` | jsonb | result shape only - no raw rows (columns, chart_type, row_count, aggregate_summary). Note: PRD §6 data model says "Raw Snowflake query result" - this spec deliberately diverges. PRD §8 security requirement prohibits raw rows from leaving the execution boundary; the spec's position is correct and governs. |
| `chart_type` | text | |
| `chart_rationale` | text | one-line auto-select explanation shown beneath chart |
| `confidence_tier` | text | High / Medium / Low |
| `composite_score` | float | internal only - not shown to user |
| `clarification_triggered` | bool | |
| `quality_flag` | text | default `'ok'`; updated async on thumbs-down |
| `source` | text | `'user'` at MVP; `'scheduled'` reserved for V2 |
| `input_modality` | text | `'voice'` or `'text'` |
| `latency_ms` | int | end-to-end pipeline time |
| `created_at` | timestamptz | |

**`conversations`**

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | = `conversation_id` in session |
| `user_id` | UUID FK → users.id | |
| `tenant_id` | UUID | |
| `title` | text | auto-generated: first 60 characters of `submitted_text` from turn 1, truncated at word boundary; written in Phase 7 of the first turn alongside the session write |
| `created_at` | timestamptz | |

**`user_snowflake_roles`**

| Column | Type | Notes |
|---|---|---|
| `user_id` | UUID PK | |
| `tenant_id` | UUID | |
| `snowflake_role` | text | read once at session creation; cached in Redis |

**`tenant_connections`**

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | UUID PK | |
| `snowflake_dsn` | text | AES-256 encrypted at rest - never logged |
| `created_at` | timestamptz | |

**`clarifications`**

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `turn_id` | UUID FK → turns.id | |
| `prompt_sent` | text | clarifying question shown to user |
| `user_choice` | text | option selected; null if escaped or timeout |
| `resolution_type` | text | `option_selected` / `escaped` / `timeout` |
| `created_at` | timestamptz | |

Written async alongside the turns row when a clarification was triggered. Enables post-pilot analysis of which ambiguity types most frequently required clarification and which options were selected.

**What Postgres never stores:** raw Snowflake result rows. Audio bytes. Interim transcript states. Session state that would be read on the hot path.

### 7.3 Ambiguity signal taxonomy (canonical - `core/ambiguity.py`)

| Signal | Trigger condition |
|---|---|
| `entity_ambiguity` | noun matches 2+ schema entities with high cosine similarity |
| `temporal_ambiguity` | relative time expression with multiple candidate date columns |
| `metric_ambiguity` | generic metric reference maps to 2+ distinct schema columns |
| `scope_ambiguity` | scope-modifying words without qualifying threshold or dimension |
| `missing_join_path` | query references entities from separate tables with no declared relationship |
| `pronoun_reference_failure` | pronoun present; no prior turns provide a referent |

Severity order (highest → lowest) for single-question selection:
1. `entity_ambiguity`
2. `metric_ambiguity`
3. `missing_join_path`
4. `pronoun_reference_failure`
5. `temporal_ambiguity`
6. `scope_ambiguity`

Only the highest-severity signal drives the clarification question per turn. All detected signals are logged in the Langfuse span.

---

## 8. `core/confidence.py` - Formula Specification

**Inputs:**
- `rag_score` - float 0–1 from 4.4
- `validation_passed` - bool from 4.5
- `llm_self_confidence` - float 0–1 from 4.5 structured output
- `ambiguity_signals` - post-suppression list from `core/ambiguity.py`

**Outputs:**
- `composite_score` - float
- `confidence_tier` - `High | Medium | Low`

**Thresholds (environment variables - not hardcoded):**
```
CONFIDENCE_THRESHOLD_PRIMARY=0.65           # clarification trigger
CONFIDENCE_THRESHOLD_POST_CLARIFICATION=0.50
```

**Tier mapping:**
- High (≥ 0.80): result displayed immediately with no friction
- Medium (0.65–0.79): result displayed with inline caveat: *"I'm moderately confident - the query joined tables I'm less familiar with. Review the SQL before actioning."*
- Low (< 0.65): clarification loop triggers

**Note on PRD §4.8 confidence inputs:** The PRD lists three inputs as: RAG retrieval score, sqlglot validation pass/fail, and *result row count plausibility check*. This spec substitutes `llm_self_confidence` (Claude's structured self-assessment of schema match quality) for the row count plausibility check. Rationale: `llm_self_confidence` is available before Snowflake execution and captures schema uncertainty more directly than post-execution row count heuristics. Row count anomaly detection is handled separately by 4.5 as a post-execution deduplication check (PRD §4.5). This substitution is an architectural decision; if the PRD owner disagrees, align before Week 4 implementation.

**Penalty model:** Each ambiguity signal applies a penalty to the base weighted composite. `missing_join_path` and `pronoun_reference_failure` carry larger penalties than `temporal_ambiguity` and `scope_ambiguity`. Penalty magnitudes are configurable post-pilot. Formula weights must be logged per turn - not just the final `composite_score` - to enable post-pilot calibration.

**`stt_confidence` is not an input to `confidence.py`.** It is logged in the `stt_capture` Langfuse span for observability only.

**Single source of truth:** No other module may compute or store a confidence score. If a parallel confidence computation is found anywhere in the codebase, it is an architecture violation.

---

## 9. Token Budget and Truncation

**Budget:** `TOKEN_BUDGET` environment variable, default ~2,500 tokens for history. Use `tiktoken` with the correct encoding for Claude - character-length heuristics are not acceptable.

**Algorithm (runs at session read, Phase 2):**
1. Count tokens in `resolved_entities` - reserve this; it is never dropped
2. Iterate history from most recent to oldest; accumulate token count
3. Include turns until remaining budget (total − reserved) is exhausted
4. Drop turns that don't fit; record `turns_dropped`
5. If `turns_dropped > 0`, prepend to history injection:
   > "Note: {turns_dropped} earlier turns were omitted due to length. Resolved entity mappings from all turns are preserved above."

`resolved_entities` is always injected in full, even when the clarification turn that produced the resolution has been aged out of the history. Entity resolutions outlive the turns that created them.

**Always injected (never truncated):** `resolved_entities`, current turn context (submitted_text, ambiguity signals, resolved_entity from this turn's clarification if any).

**Never injected:** raw Snowflake result rows, Langfuse span data, `stt_confidence`, `raw_transcript`, `edit_distance`.

---

## 10. Security Constraints

These are not preferences. Any deviation is an architectural defect.

| Constraint | Enforcement |
|---|---|
| Audio bytes never reach any LLM API | FastAPI relay is pure pass-through; no buffering to Claude |
| Raw Snowflake result rows never cross LLM boundary | `format_turn_for_injection()` stores result shape only |
| Deepgram API key never in browser | No client-side Deepgram SDK; key is a Railway env var only |
| Snowflake DSN AES-256 encrypted at rest | Never logged; never in Langfuse spans |
| User input injected as quoted user message | Never concatenated into system prompt string |
| `sqlglot` AST validation rejects non-SELECT root node | Runs before any Snowflake connection opens |
| Snowflake role passthrough - no elevation | User's assigned role used as-is; VoxQuery has no shadow permission layer |
| `session_id` in `sessionStorage` - not `localStorage` | Cleared on browser refresh intentionally |
| Redis keys scoped per tenant | Key pattern: `session:{tenant_id}:{session_id}` |
| All transport TLS 1.3 | Browser → Vercel → Railway → all APIs |

**Pre-pilot blockers (must be confirmed contractually):**
- Deepgram no-log data retention option confirmed
- Permission modal audio disclosure text reviewed by legal

---

## 11. Langfuse Instrumentation

Every turn produces one root Langfuse trace. The following spans are mandatory. Absent spans in production are instrumentation bugs.

### Spans always present (every turn)

**`stt_capture`**
```
inputs:  session_id, input_modality
outputs: raw_transcript, submitted_text, stt_confidence,
         edit_distance_ratio (= edit_distance / len(submitted_text))
```

**`memory_retrieval`**
```
inputs:  session_id, turn_count
outputs: history_turns_available, history_turns_injected,
         resolved_entities_count, token_count_before, token_count_after,
         truncation_occurred, turns_dropped, retrieval_latency_ms
```
Target `retrieval_latency_ms` < 5ms P99. Values > 10ms consistently indicate a Redis connectivity or session object size problem.

**`history_injection`**
```
outputs: turns_injected, resolved_entities_injected,
         total_prompt_tokens, truncation_sentinel_included
```

**`ambiguity_detection`**
```
inputs:  submitted_text, schema_chunks_count
outputs: signals_detected, signals_suppressed, dominant_signal,
         detection_latency_ms
```
`detection_latency_ms` must be < 10ms. Alert if P95 > 15ms - this is deterministic code.

**`confidence_computation`**
```
inputs:  rag_score, validation_passed, llm_self_confidence,
         ambiguity_signals, ambiguity_penalty_total
outputs: composite_score, confidence_tier, clarification_triggered,
         threshold_used,
         formula_weights: { rag, validation, llm, ambiguity_penalty_per_signal }
```
All three named inputs (`rag_score`, `validation_passed`, `llm_self_confidence`) are individually logged - this is a governance invariant. Logging only `composite_score` makes post-pilot calibration impossible.

### Spans present only when clarification triggered

**`clarification_generation`**
```
inputs:  dominant_signal, ambiguous_term, schema_chunks_count
outputs: question, options_generated, options_validated, options_suppressed,
         clarification_suppressed (bool - true if < 2 valid options remain),
         generation_latency_ms
```

**`clarification_resolution`**
```
inputs:  clarification_question, options_presented, time_to_resolve_ms
outputs: resolution_type (option_selected | escaped | timeout),
         option_selected (string | null), resolved_entity
```

### Thumbs-down - score event (not a span)

Attaches to the already-closed trace via Langfuse score API:
```
trace_id:   string
name:       "user_feedback"
value:      -1
metadata:   turn_id, confidence_score (= composite_score at render time),
            confidence_tier, clarification_triggered, option_selected
```

### Alert

Langfuse alert configured: clarification trigger rate > 50% for a tenant. Treat > 40% as a manual review trigger before the automated alert fires.

---

## 12. Error Handling

| Failure point | Behaviour |
|---|---|
| WebSocket connect failure | recordingState → idle; toast: "Couldn't connect. Try again." |
| Device disconnect mid-recording | recordingState → idle; toast: "Microphone disconnected."; partial transcript preserved |
| WS drop during streaming | recordingState → idle; toast: "Connection lost."; partial transcript preserved |
| Final transcript not received after retries | recordingState → idle; toast: "Couldn't confirm transcript."; preserve partial if non-empty |
| Redis read failure | Pipeline halts; return: "Session unavailable - please refresh." |
| Clarification < 2 valid options | Suppress clarification; proceed to SQL execution at current composite_score |
| SQL_REGENERATION score < 0.50 | ERROR_STATE; return: "I couldn't generate a valid query even after clarification. Try rephrasing or use the text input."; turn not written |
| Snowflake timeout (30s) | Return: "Query timed out - the data warehouse may need a moment to wake up. Try again in 30 seconds." |
| Snowflake cold-start (30–60s) | Same timeout message; document cold-start in pilot onboarding |
| Postgres async write failure | Log; non-blocking; Redis session unaffected |
| Orphaned Deepgram connection | On client WS close: always close corresponding Deepgram WS in `finally` block |

---

## 13. Environment Variables

```
# Confidence thresholds
CONFIDENCE_THRESHOLD_PRIMARY=0.65
CONFIDENCE_THRESHOLD_POST_CLARIFICATION=0.50

# Session
SESSION_TTL_SECONDS=14400
TOKEN_BUDGET=2500
RESULT_CACHE_TTL_SECONDS=300      # Redis query result cache; default 5 min (PRD §8)

# External APIs (Railway env vars - never in code)
DEEPGRAM_API_KEY=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
UPSTASH_REDIS_URL=
SUPABASE_DATABASE_URL=
SNOWFLAKE_DSN=            # AES-256 encrypted at rest

# Auth
CLERK_SECRET_KEY=
CLERK_PUBLISHABLE_KEY=    # Vercel env var (public)

# Observability
LANGFUSE_SECRET_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_HOST=

# Backend URL (Vercel env var - public)
NEXT_PUBLIC_API_URL=
```

All production secrets are in Railway (backend) and Vercel (frontend) dashboards only. No secrets in the repository. `.env.example` in the repo lists all keys with placeholder values. `.env.local` is gitignored.

Startup validation: on FastAPI startup, assert all required env vars are present. Fail fast with a clear error if any are missing - do not start a partially configured service.

---

## 14. Build Sequence

Priority order is strict. Each item unblocks the next. Do not reorder.

### Phase 1 - Foundation (Weeks 1–3)
Goal: pipeline runs end-to-end with stubs; all data contracts in place; no LLM quality required.

**Week 1 - Infrastructure and data contracts**

1. **Supabase schema migration (Day 1).** Create `turns`, `conversations`, `user_snowflake_roles`, `tenant_connections`. All columns in §7.2 - including `source`, `input_modality`, `quality_flag`, `composite_score`, `deepgram_confidence_raw` - must be in the initial migration. Schema changes after subsystems are built cause cascading rework.

2. **Redis session schema definition (Day 1).** Define the full session object (§7.1) before writing a single line of session code. Freeze it for Phase 1.

3. **Railway skeleton (Day 2).** Minimal FastAPI: `/health` returning 200, startup env var validation, structured JSON logging to stdout, CORS for localhost:3000. Goal: confirm Railway WebSocket support and deployment pipeline before writing feature code.

4. **Clerk JWT middleware (Day 2–3).** FastAPI middleware validates every request before subsystem code runs. Auth is not added later - it is part of the foundation. Every integration test from this point is auth-aware.

5. **Vercel + Next.js skeleton (Day 3).** Login screen + placeholder query page, Clerk integrated, stable custom domain configured. Confirm Vercel deployment pipeline. Vercel Preview Deployments must not be used for pilot sessions (different subdomains break `sessionStorage` scoping).

6. **Upstash Redis round-trip test (Day 3).** Write a session. Read it back. Confirm sub-5ms latency from Railway in the same region. If latency is outside target, resolve region co-location before any feature work.

**Checkpoint - End of Week 1:** Schema deployed · Redis round-trip confirmed · Railway health-checked · Vercel + Clerk live · All env vars in dashboards.

---

**Week 2 - Core pipeline skeleton**

7. **Deepgram WebSocket proxy (Days 6–8).** Build `/ws/audio`. Test in this exact order - do not combine steps:
   - Step 1: open a Railway WebSocket from a Python test client - confirm Railway supports persistent WebSocket connections
   - Step 2: open a Deepgram WebSocket from the Railway process - confirm nova-2 streaming transcript format
   - Step 3: route audio bytes from test client through to Deepgram - confirm relay
   - Step 4: implement lifecycle management - client close → Deepgram close; Deepgram close → client error; idle timeout → both sides close. Test with forced disconnects (kill browser tab, simulate network block, 30s idle). Confirm Deepgram connection is closed in every case.
   - Step 5: add interim/final transcript discrimination
   - Step 6: connect the Next.js frontend

   Compounding all layers before testing each pair independently produces an untraceable debugging surface.

8. **Snowflake connector (Days 8–9).** Per-request open/close. Read-only role assertion before execution. 30-second timeout with structured error. `sqlglot` AST validation before connection opens. Test against the actual pilot schema with pilot user credentials. Confirm Snowflake enforces the read-only role restriction - not just VoxQuery's validation layer.

9. **LLM adapter (stub) (Day 10).** Implement the interface with hardcoded SQL and hardcoded clarification options. Real adapter must swap in with zero changes to orchestration code.

**Checkpoint - End of Week 2:** Deepgram proxy functional (tested in isolation + with frontend) · Snowflake connector functional (against real schema) · End-to-end pipeline: audio → transcript → stub SQL → stub result.

---

**Week 3 - Schema embedding and real LLM**

10. **Schema chunk ingestion (Days 11–13).** Fetch schema metadata from Snowflake. Chunk. Embed with `text-embedding-3-small`. Store in pgvector. Validate retrieval: run 10+ representative natural language queries; manually confirm top-5 retrieved chunks contain the correct tables and columns (PRD §4.4 specifies top-5 retrieval). High cosine similarity scores alone are not sufficient - manual verification is the gate. If retrieval is poor, fix it now. Fixing it in Week 7 delays the pilot.

11. **Real LLM integration (Days 13–15).** Replace stub adapter with Anthropic Claude for SQL generation and clarification. Replace with OpenAI for TTS and embeddings. Run full end-to-end. SQL quality will be inconsistent at this stage - that is expected. Goal is confirming integration, not production quality.

**Phase 1 Gate - End of Week 3:** Schema embeddings validated · Real LLM end-to-end functional · Full pipeline: voice → transcript → retrieval → SQL → Snowflake → result → TTS · No stubs in integration path · Auth enforced · Session written to Redis; turn written to Postgres.

**If this gate is not met, do not proceed to Phase 2.** Fix what is blocking. Do not add feature complexity on top of a broken foundation.

---

### Phase 2 - Subsystem Integration (Weeks 4–6)
Goal: all three subsystems integrated and functionally correct; confidence scoring calibrated; no pilot users yet.

**Week 4 - Clarification loop**

12. **`core/ambiguity.py` (write tests first).** Rule-based classifier: entity count, operator count, temporal reference, named metrics. Every signal combination must have a unit test before integration. If ambiguity.py is written without tests, miscalibration will be invisible until the pilot.

13. **`core/confidence.py`.** Three named inputs + ambiguity signal penalties. Formula and weights per §8. Thresholds from environment variables - not hardcoded. Log all three input components individually per turn; `formula_weights` logged even when weights are constant.

14. **Clarification option generation and UI.** Clarification LLM call produces structured JSON: one question, 2–4 options, ambiguity type. Validate options against schema_chunks - remove any referencing entities not in the chunks. Render in Next.js. If < 2 valid options remain after validation, suppress clarification and proceed.

15. **30-second timeout and escape paths.** Timeout → `QUERY_SUBMITTED` → SQL execution at original score. Escape → `CLARIFICATION_ESCAPED` → pipeline halts; turn not written. Both must work before pilot.

**Checkpoint - End of Week 4:** ambiguity.py unit-tested · confidence.py correct on 10 representative transcripts · Clarification UI functional · Both exit paths tested.

---

**Week 5 - Memory and multi-turn**

16. **`core/session.py` complete.** Session create/read/write/TTL. `resolved_entities` suppression every turn. Token budget enforcement with tiktoken. Truncation algorithm per §9. Write full history to Redis always; budget only affects injection.

17. **`quality_flag` write-back.** Thumbs-down updates Redis in-place for the relevant `turn_id`. Async Postgres update. Next turn's session read reflects the updated flag.

18. **Multi-turn continuity test.** Run 5+ turn sessions. Verify: second turn receives first turn context; `resolved_entities` from turn 3 suppresses the same signal in turn 7; truncation fires and sentinel is injected when budget is exceeded.

**Checkpoint - End of Week 5:** Multi-turn sessions working · Resolved entities persisted and suppressed correctly · Truncation tested.

---

**Week 6 - Calibration and integration validation**

19. **Confidence threshold calibration.** Run 50 representative queries against the pilot schema with real transcripts. Plot the composite_score distribution. Identify the natural break between queries that needed clarification and those that did not. Adjust `CONFIDENCE_THRESHOLD_PRIMARY` if the empirical break differs from 0.65. Document the calibration basis in a `calibration-log.md` file - not in code.

20. **End-to-end integration test suite.** Must cover all of the following before Phase 3:
    - Happy path: voice → result
    - Clarification triggered: score < 0.65 → options → selection → result
    - Clarification suppressed: < 2 valid options → proceed without clarification
    - Escape path: "None of these" → pipeline halts; turn not written
    - Timeout path: 30s → `QUERY_SUBMITTED` → SQL execution
    - Session resume: Redis TTL not expired → context injected
    - Session expiry: Redis TTL expired → new session
    - Snowflake timeout: 30s → structured error
    - Audio fallback: Deepgram unavailable → text input mode
    - `resolved_entities` suppression: entity resolved in turn N → same signal suppressed in turn N+2

21. **Langfuse instrumentation validation.** Run end-to-end and confirm: one root trace per turn · all spans present with correct latency · `confidence_tier` tag on trace · thumbs-down score event attaches to correct trace · formula_weights logged.

**Phase 2 Gate - End of Week 6:** All 10 integration scenarios pass · Thresholds calibrated against real data · Langfuse traces complete.

---

### Phase 3 - Pilot Hardening (Weeks 7–8)
Goal: launch blockers cleared; monitoring live; stable under manual load.

22. **Pre-launch checklist (Week 7):**
    - Railway WebSocket persistent connections confirmed
    - Chrome, Edge, and Safari desktop confirmed (all three required per PRD §4.1 AC - Safari desktop `MediaRecorder` is supported on current versions; iOS Safari is out of scope)
    - Deepgram no-log retention confirmed contractually
    - Snowflake cold-start behaviour documented and communicated to pilot customer
    - Langfuse alert (> 50% clarification rate) configured
    - `/health` endpoint configured as Railway health probe
    - All env vars in Railway and Vercel dashboards; startup validation passes clean

23. **Internal soft launch (Mid Week 8).** 2-day internal test with real schema. No pilot users. Confirm no blocking errors. Fix anything that surfaces before pilot user is onboarded.

**Pilot-readiness is binary.** All of the following must be true before a pilot user is onboarded:
- Full pipeline passes all 10 integration scenarios
- Thresholds backed by real data
- Pre-launch checklist fully confirmed
- Chrome, Edge, and Safari desktop confirmed
- Langfuse monitoring live
- 2-day internal soft launch passed with no blockers

---

## 15. What Not to Build

These items are explicitly deferred. Building any of them before pilot data exists is a governance violation.

| Item | Trigger for building |
|---|---|
| Open-mic VAD | Never at MVP; Fast-Follow only |
| Deepgram keyword boosting | After pilot glossary data exists (Week 2 of pilot at earliest) |
| Per-tenant confidence threshold tuning | After 50 queries per tenant |
| `nova-2-meeting` model evaluation | Only if open-office noise is flagged in pilot feedback |
| Alternative STT evaluation | Only if domain accuracy < 90% in pilot weeks 1–2 |
| Conversation summarisation on truncation | Only after pilot confirms truncation at P90 session depth |
| `resolved_entities` adaptive auto-resolution | Requires per-user history; Fast-Follow |
| Clarification option ranking by usage frequency | Requires pilot selection pattern data |
| Cross-session memory | V2; turns table already captures the data |
| Column-level encryption for `user_input` | Post-pilot enterprise hardening |
| Connection pooling for Snowflake | Post-pilot performance optimisation |
| Sticky session config on Railway | Only if scaling beyond single instance |
| Smaller model for clarification generation | After 4 weeks of Langfuse token count data |
| Waveform visualisation | Static pulsing animation is sufficient at MVP |

---

## 16. Top Risks

**Risk 1 - Schema embedding quality (Critical).** If retrieval returns wrong chunks, SQL generation fails regardless of prompt quality. This failure is invisible until you run real queries against the real schema. It cannot be discovered with unit tests or stubs. Week 3 retrieval validation with real queries and manual verification of top-3 chunks is non-negotiable. If retrieval is poor, fix it in Week 3. Fixing it in Week 7 delays the pilot.

**Risk 2 - Deepgram WebSocket lifecycle (High).** Orphaned Deepgram connections accumulate cost and are hard to reproduce in development. Explicitly test: kill the browser tab, simulate network block, 30s idle. Confirm Deepgram connection is closed in every case.

**Risk 3 - Confidence threshold miscalibration (High).** If 80% of real queries score below 0.65, the executive is asked to clarify every query and disengages. If 5% score below 0.65, genuinely ambiguous queries produce wrong SQL without clarification. Either outcome ends the pilot. Week 6 calibration against 50 real queries is mandatory - do not launch with the default 0.65 unvalidated.

**Risk 4 - Snowflake cold-start (Medium).** If the warehouse auto-suspends and the first query of the day hits a 45-second cold start with no explanation, the pilot customer concludes the product is broken. Discuss pre-warming with the customer before Day 1. Document it in the pilot onboarding guide.

**Risk 5 - Session schema drift mid-development (Medium).** Changing the Redis session object or Postgres turns table after subsystems are built requires coordinated updates across every subsystem that reads or writes it. Define both schemas on Day 1 and freeze them for Phase 1.

---

## 17. Latency Budget

P95 end-to-end target: **< 8 seconds** excluding Snowflake cold-start.

| Stage | Target |
|---|---|
| STT: speech → final transcript at client | < 500ms |
| RAG retrieval | < 500ms |
| Ambiguity detection | < 10ms |
| SQL generation (LLM) | < 1,500ms |
| sqlglot validation | < 50ms |
| Clarification generation (when triggered) | < 500ms; total to display < 2,500ms |
| Snowflake execution (pre-warmed) | < 10,000ms P50 |
| Redis cache hit | < 200ms (bypasses Snowflake) |
| TTS + Storytelling (parallel with chart) | < 3,000ms |

Progress events are triggered by real Orchestrator events - not setTimeout approximations.

---

*VoxQuery Engineering Spec - Subsystems 4.1 · 4.2 · 4.3*  
*Derived from Architecture Foundation Document v1.0 + Batches 1–5*  
*Changes require explicit architecture review*
