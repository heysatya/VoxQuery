# VoxQuery — Architecture & Code Review + Action Plan (v2, Complete)

**Repo:** `heysatya/VoxQuery` · **Branch:** `voxquery-e2e-integration` · **Commit:** `b7d5cf0` (verified clean tree)
**This document supersedes v1.** Every backend module and every frontend file has now been read directly; both test suites have been executed directly. Nothing in the codebase was reviewed from memory or from the README's claims alone.

**Methodology:** `architecture-code-review` skill (12-section rubric, saved to `/mnt/skills` this session). Every finding is tagged **[Verified]** (read the exact code and/or executed a command) or **[Inferred]** (plausible, not directly executed) — all findings below are **[Verified]** unless stated otherwise.

---

## Part A — Executive Summary (updated)

Same overall verdict as v1, reinforced with more evidence: a genuinely well-built MVP with real spec-driven process discipline, undercut by a gap between what's documented/claimed and what's actually wired into the live path. Three new categories of finding emerged in this complete pass:

1. **A second test-rot bug, this time on the frontend**, on the exact PRD-mandated confidence-tier UI.
2. **Two real concurrency/scalability defects** in the WebSocket event-delivery and session-storage layers — the kind of thing that works fine in single-user local testing and degrades under concurrent pilot load.
3. **A recurring architectural pattern**: several well-designed, well-unit-tested guardrail/utility modules (`MetricRegistry`, `validateNarrative`, proactive-question generation) exist and pass their own tests in isolation, but are never actually called from the live request path. This is worth naming as a pattern, not just a list of isolated misses — it suggests the team's "build it + test it" discipline isn't always being followed through to "wire it into the pipeline and prove it end-to-end."

---

## Part B — Remaining Subsystems (completing full coverage)

### B.1 REST API (`app/api/rest.py`) — Solid, one hardcoded gap confirmed twice

**[Verified]** Clean, small, contract-driven routes. Ownership checks are consistent (`get_turn_for_user` checks `user_id`/`tenant_id` match, not just existence — this pattern is applied correctly everywhere I checked, including feedback and clarification resolution).

**[Verified] Confirms FEAT-1 (below) independently:** both `GET /api/result/{turn_id}` (`rest.py:117`) and the WebSocket `render_node` (`graph.py:514`) hardcode `proactive_questions=[]`. Two independent call sites, same gap — this isn't a one-off oversight, the feature genuinely was never implemented on the backend.

**[Verified, P2] Dependency-direction smell, repo-wide, not just one file:** `rest.py`, `telemetry.py`, `ws_audio.py`, `ws_pipeline.py`, and `ws_tts.py` all do `from app.main import app` *inside* route-handler function bodies to reach `app.state.pipeline`/`app.state.sessions`/`app.state.telemetry`, rather than using FastAPI's own `Request` object (`request.app.state.X`) or a proper `Depends()`-injected singleton. This works, but it inverts the natural dependency direction (route modules reaching back into the app-assembly module) across the *entire* API surface, not an isolated case. Recommend: pass `Request` into each handler and read `request.app.state`, or centralize state access behind a small `get_app_state()` dependency.

### B.2 WebSocket Pipeline Channel (`app/api/ws_pipeline.py`, `app/services/events.py`) — **[Verified] Real concurrency/scalability defect**

`PipelineEventBus` (`events.py`) is backed by the **synchronous stdlib `queue.Queue`** (`from queue import Queue`), not `asyncio.Queue`. The WebSocket route (`ws_pipeline.py`) delivers events with a manual busy-poll loop:

```python
try:
    event = queue.get_nowait()
except Empty:
    await asyncio.sleep(0.01)
    continue
```

This is the channel that streams every `PipelineProgressEvent` (stage-by-stage progress) to the client for every active session — it exists specifically to give the user live feedback within the PRD's sub-8-second latency budget. As implemented, every open pipeline-socket connection wakes up 100 times/second, forever, for the life of the connection, whether or not there's an event to deliver. This is fine for one local developer testing solo; it is a real CPU and scalability liability at even modest concurrent-pilot-user counts, and it adds up to 10ms of avoidable latency per event on top of whatever the actual pipeline stage took.

**Fix:** switch `PipelineEventBus` to `asyncio.Queue`, and `await queue.get()` in the WS handler — this delivers events with effectively zero latency and zero idle CPU cost, and is a small, contained change.

### B.3 Session Store (`app/core/session.py`) — Strong design, one blocking-I/O defect

**[Verified] Strength:** `context_block()` correctly implements the PRD's token-budgeted history truncation ("last N turns kept," resolved entities always preserved even when turns are dropped) — a genuinely careful implementation, not a naive slice.

**[Verified, P1] `RedisSessionStore` uses the synchronous `redis` client, not `redis.asyncio`,** inside an async FastAPI application. Every session read/write (which happens on nearly every REST call and WebSocket connect, via `get_for_claims`) is a **blocking** call on the event loop. Combined with `socket_timeout=2` on the Redis client, a slow or degraded Redis connection can stall the *entire* event loop — every other in-flight request/socket in the process — for up to 2 seconds per call, not just the one session lookup that's slow. This is the second of the two real concurrency defects found in this pass, and like B.2, it's invisible in single-user local testing and becomes a real problem under concurrent pilot load.

**Fix:** switch to `redis.asyncio.Redis` and `await` all client calls.

### B.4 Data Contracts (`app/models/contracts.py`) — Well-designed, with two drift bugs

**[Verified] Strength:** `ResultPayload`'s `populate_semantics()` model-validator auto-infers column role (dimension/metric/time/identifier) and value type from the actual row data, and `valid_visualizations_for_result()` derives legitimate chart options from that inference rather than trusting the LLM's chart choice blindly — genuinely good defense against a hallucinated/inappropriate chart type. `QueryRequest`'s `validate_modality_contract()` model-validator is a nice touch: it actively rejects a text-modality request that smuggles in voice-only fields, and *cross-checks* that the client's `transcript_edited` flag actually matches whether `submitted_text` differs from `raw_transcript` — this is real, structural validation, not just type-checking.

**[Verified, P1] `ClarificationResolutionType` enum is missing a value the database schema anticipates.** `db/migrations/001_voice_subsystem.sql` declares `resolution_type TEXT NOT NULL CHECK (resolution_type IN ('option_selected', 'escaped', 'timeout'))`, but `contracts.py`'s `ClarificationResolutionType` StrEnum only defines `option_selected` and `escaped` — no `timeout` member exists in the Python type at all. This is enum/schema drift, and it corroborates a real missing feature (below, FEAT-2): there is no mechanism anywhere in the codebase that ever resolves a stale, unanswered clarification as a timeout.

**[Verified, P1] `ErrorCode.clarification_expired` is dead code.** It's defined with a real user-facing message (`"That clarification has expired. Please submit your question again."`) in `ERROR_MESSAGES`, but `grep` across the entire `app/` tree shows it is **never raised anywhere**. There is no code path that expires a pending clarification. A user could receive a clarification prompt, leave the tab open for days, come back, and answer it — the system will process the stale answer as if it just happened. (The only bound on this today is the Redis session TTL, which is a much coarser, unrelated mechanism — 4 hours by default — not a per-clarification expiry.)

### B.5 Audit / Migrations (`app/audit/migrations_runner.py`) — Minor robustness gap

**[Verified, P2]** `MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "db" / "migrations"` hardcodes a fixed directory-depth assumption to locate the migrations folder from the module's own file location, and `if not MIGRATIONS_DIR.exists(): return` **silently no-ops** if that path doesn't resolve — no warning, no error, no log line. If this file is ever relocated, or the app is packaged/deployed in a way that changes the relative directory layout (a Docker `COPY` that flattens paths, an installed wheel, etc.), migrations would silently stop running with zero indication anything is wrong. Recommend: make the migrations directory an explicit, configurable path (env var or settings field) and raise loudly if it's missing when a Postgres DSN is configured.

### B.6 LLM Adapter — Storyteller and Clarification generation (`app/llm/claude.py`, remainder) — Good, same hardening gap as SQL generation

**[Verified] Strength:** `ClaudeStoryteller.summarize()` correctly matches PRD §4.9's design: a separate LLM call, receiving only `ResultShape` (never raw rows — enforced by the type signature itself, `Storyteller.summarize(self, result_shape: ResultShape, ...)`, not just by convention), with an explicit "STRICT 1-3 sentence... Headline, Driver, Implication" prompt and an instruction to output plain text for TTS (no markdown). The PRD explicitly says the 3-sentence limit should be "enforced by the prompt, not post-processing," and the code's own comment confirms this design choice deliberately (`"we trust the LLM mostly with this strong prompt"`) rather than silently truncating — this is a case of the code correctly following a specific, easy-to-get-wrong spec detail.

**[Verified] `generate_clarification()`** asks Claude for structured JSON (question + 2–4 options, always including a "Skip" option), with a sensible fallback if the JSON fails to parse. Matches PRD §4.2 well.

**[Verified, P1 — same finding as SEC-3 in v1, now confirmed to apply to all three LLM call sites, not just SQL generation]** None of `generate_sql()`, `generate_clarification()`, or `summarize()` use the Anthropic `system` parameter — every call concatenates instructions and untrusted content (schema, history, user input, result shape) into a single `user`-role message. This is a hardening gap across the entire LLM adapter, not an isolated case.

### B.7 Frontend — Full-suite execution and remaining components

**[Verified] Ran the frontend suite directly** (`npx vitest run`, after `npm install`):

```
Test Files  1 failed | 4 passed (5)
     Tests  1 failed | 83 passed (84)
```

The failure: `app/page.test.tsx:910` — `expect(await screen.findByText("Moderate confidence")).toBeInTheDocument()`. The live `TrustPanel.tsx` component's `TIER_CONFIG.Medium.label` is `"Partial match"`, not `"Moderate confidence"` — the test was written against an earlier copy string that has since changed. **This is the same class of bug as the backend's `test_rag.py` failure (TEST-1 in v1): a test encoding a stale contract, on the exact UI element (the three-tier confidence label) that the PRD calls a safety-critical trust signal for executives deciding whether to act on a number immediately.** Combined with there being no CI anywhere, this means the one test guarding the product's primary trust-communication UI has been silently broken.

**[Verified, P2] `frontend/package.json` `engines` field is `"node": ">=20.9.0 <21"`** — strictly excluding Node 22 (the version actually installed in this environment, and a commonly-installed current LTS). This contradicts the README/PRD's own stated `"Node >=20.9"` (open-ended). `npm install` succeeds with only a warning (`npm warn EBADENGINE`) today because npm doesn't hard-enforce `engines` by default, but any CI or tooling with `engine-strict=true` would fail outright, and it's a confusing signal for a new contributor running a normal, current Node install.

**[Verified, P1] `deriveCaveatText()` and `formatDataSources()` in `lib/resultSemantics.ts` reference backend fields that don't exist.** They read `result.confidence_reasons`, `result.trust?.confidence_reasons`, and `result.trust?.data_sources` — all declared as optional fields in the frontend's own `types.ts`, but **none of these fields exist anywhere in the backend's `ResultResponse` or `ResultTrust` Pydantic models** (`contracts.py`), and neither `graph.py` nor `rest.py` ever populates them. TypeScript's optional chaining (`?.`) means this doesn't crash — it silently falls through to generic fallback text (`"We made some assumptions to calculate this..."`) and a regex-based best-effort table-name extraction from the raw SQL string, every single time, in production. The Trust Panel's more specific, backend-computed "why is this Medium confidence" and "which tables/sources fed this answer" sub-features were built on the frontend and are permanently dark.

**[Verified] Strengths confirmed across the rest of the frontend:**
- `lib/audio/pcm.ts`: a genuinely correct client-side resampler + linear-PCM Int16 encoder, producing exactly the format the backend/Deepgram expects (16kHz, mono, little-endian Int16) — with linear-interpolation downsampling, not naive decimation. Has its own test file.
- `app/state/interactionState.ts`: an explicit, table-driven finite-state machine for voice capture with a real allowed-transitions map — the same "state machine, not scattered if/else" discipline seen in the backend's LangGraph orchestration, applied consistently on the frontend too.
- `ClarificationOverlay.tsx`: proper modal semantics (`role="dialog"`, `aria-modal`, focus management on mount), matches PRD §4.2's "tappable buttons, not free text" and "escape" requirements exactly.
- `FailureNotice.tsx`: severity-aware, `aria-live="assertive"` on errors, explicitly reassures the user their data is safe on error — good UX discipline matching the PRD's error-handling intent.

**[Verified, P2] A second instance of the "built + tested in isolation, never wired in" pattern:** `validateNarrative()` in `resultSemantics.ts` (checks TTS narrative is plain-text and ≤3 sentences — a client-side mirror of the backend's storytelling-engine constraint) is defined and has its own test coverage, but `grep` across the entire frontend finds **zero call sites** — it's never invoked from any component. Combined with `MetricRegistry` (backend) and the fully-plumbed-but-always-empty `proactive_questions` path, this makes three separate instances of the same pattern across both codebases.

---

## Part C — PRD Feature Traceability Matrix

Every PRD §3 "in scope for MVP" item and the key §4/§8/§9 requirements, checked directly against the code (not the README's claims).

| PRD Requirement | Status | Evidence |
|---|---|---|
| Voice input (Deepgram streaming STT) + text fallback | ✅ **Done** | `core/stt.py` — real streaming impl, redaction, timeout; `QueryRequest.input_modality` enforces contract |
| Schema-aware RAG over Snowflake metadata | ⚠️ **Partial** | Hybrid BM25+vector RRF retrieval is real (`pgvector.py`); business-glossary/metric mapping is hardcoded to one demo schema, not tenant-configurable (ARCH-1) |
| LLM SQL generation (Sonnet 4) + sqlglot validation | ⚠️ **Partial** | sqlglot validation is strong; model is Haiku, not the PRD-mandated Sonnet, undocumented (MODEL-1) |
| Read-only enforcement (CQRS) | ✅ **Done, strong** | `sql_policy.py` — AST-level, tested adversarially |
| Snowflake execution + row limits | ⚠️ **Partial** | Row limits enforced; DSN is a single global value, not per-tenant/encrypted as specified (SEC-1, SEC-2) |
| Clarification prompt on ambiguity | ⚠️ **Partial** | Detection, generation, UI all real and good; **no expiry/timeout mechanism** despite `ErrorCode.clarification_expired` and a DB `timeout` enum value existing (FEAT-2) |
| Chart selector (bar/line/table/stat) | ✅ **Done** | `valid_visualizations_for_result()`, rationale text, user override supported |
| TTS voice summary (Deepgram Aura) | ✅ **Done** | `core/tts.py`, `ws_tts.py` — real streaming, redaction, graceful degradation on failure per spec |
| Single-session conversation memory | ✅ **Done** | `session.py context_block()` — genuinely careful token-budgeted truncation |
| **Proactive question suggestions** | ❌ **Not implemented** | Backend hardcodes `proactive_questions=[]` at both call sites (`graph.py:514`, `rest.py:117`); frontend component fully built and tested but permanently dark (FEAT-1) |
| Single-tenant Snowflake connection per workspace | ⚠️ **Partial** | Works for exactly one tenant; DB schema supports per-tenant DSNs but the app never queries it (SEC-2) |
| SSO via Clerk | ✅ **Done, strong** | RS256/JWKS, required-claims enforcement |
| Row-level security via Snowflake role passthrough | ✅ **Done** | Tested: `snowflake_role` verified to reach `connect()` |
| Confidence tiering (High/Medium/Low) | ⚠️ **Partial** | Tiering logic correct; LLM-self-confidence term of the formula is permanently `None` in production (ARCH-4); frontend's own test for the Medium-tier label is currently failing (test-rot) |
| Confidence evidence surfaced to user ("why") | ❌ **Not implemented** | Frontend UI built for `confidence_reasons`/`data_sources`; backend never populates these fields (ARCH-6) |
| Data storytelling engine (Headline/Driver/Implication, ≤3 sentences, shape-only) | ✅ **Done, faithfully implemented** | `ClaudeStoryteller.summarize()` — separate call, `ResultShape`-only signature, prompt matches spec exactly |
| Result-set duplication detection | ⚠️ **Partial, weaker than spec** | Textual heuristic, not actual cardinality estimation (ARCH-5) |
| CSV download, one click | ✅ **Done (client-side)** | UI present (`title="Download CSV"` confirmed in rendered test output); generated from already-fetched rows |
| Data confidentiality boundary (no raw rows to LLM) | ✅ **Done, enforced structurally** | `Storyteller.summarize()` type signature only accepts `ResultShape`; `audit/postgres.py` runtime-checks and refuses to persist any payload containing a `rows` key |
| Model-agnostic LLM interface | ✅ **Done** | `LlmAdapter`/`Storyteller` ABCs, no Claude-specific leakage outside `claude.py` |
| Multi-warehouse-ready connector abstraction | ⚠️ **Partial** | `WarehouseConnector` ABC exists correctly in `app/`; but a second, dead, unreferenced connector abstraction with **MySQL/Postgres providers** sits in `staging_lib/`, directly contradicting the PRD's explicit "multi-warehouse is out of scope for MVP" scope decision |
| `turns.source` column for future Morning Briefing Mode (V2 forward-compat) | ✅ **Done, ahead of need** | `db/migrations/001_voice_subsystem.sql` — exactly matches PRD's stated V2 architecture constraint |

---

## Part D — Consolidated Action Plan (v2, complete — supersedes v1's plan)

### P0 — Fix before any further "production-ready" claim

| ID | Finding | Fix | Effort |
|---|---|---|---|
| TEST-1 | Backend: 2/175 tests fail — `test_rag.py` uses a stale `retrieve()` call signature | Update to construct/mock `RewrittenQuery`; confirm 175/175 | S |
| TEST-4 | **[New]** Frontend: 1/84 tests fail — `page.test.tsx` expects `"Moderate confidence"`, live UI renders `"Partial match"` | Update the test string to match current copy, or vice versa if the old copy is actually preferred | S |
| TEST-2 | No CI anywhere in the repo | Add GitHub Actions: backend `pytest`+`ruff`, frontend `vitest`+`eslint`, required before merge | S |
| SEC-1 | Snowflake DSN not encrypted at rest | Encrypt at write time (e.g. `Fernet`/KMS), decrypt only at connector construction | M |
| SEC-2 | Per-tenant DSN routing not wired — one global DSN for all tenants | Wire `execution_node`/orchestrator to resolve `WarehouseConnector` per `tenant_id` via `tenant_connections`; block onboarding a 2nd tenant until this lands | M |
| ARCH-1 | Business glossary hardcoded to one demo schema | Load `metric_synonyms`/`table_synonyms` per-tenant at `rewrite_query_node` time | L |
| FEAT-1 | **[New, named explicitly]** Proactive Question Suggestions — a PRD §3 in-scope MVP feature — is 0% implemented on the backend | Implement generation (likely a 4th LLM call, or derived from `chart_type`+`schema_chunks`+`user_role`, per PRD §4's description) and populate `proactive_questions` at both call sites | M |

### P1 — Architecturally significant, fix within the next iteration

| ID | Finding | Fix | Effort |
|---|---|---|---|
| ARCH-2 | `MetricRegistry` fully unwired dead code | Wire into `sql_generation_node` prompt construction, or remove and correct the README | M |
| ARCH-3 | RAG confidence mixes incompatible similarity scales post-RRF | Use the normalized RRF fusion score, not the source-specific `similarity` field | S |
| ARCH-4 | `llm_self_confidence` always `None` in production | Have Claude emit structured self-confidence, or remove the dead weight/branch and document the formula is currently 2-factor | M |
| MODEL-1 | SQL model silently deviates from PRD-mandated Sonnet to Haiku | ADR with accuracy numbers against `tests/golden_queries.yaml` vs. the PRD's 85% target | S |
| SEC-3 | No `system`/user separation across **all three** Claude adapter methods (SQL gen, clarification, storytelling) | Move static instructions to `system`; delimit untrusted content in the user turn | S |
| SEC-4 | `validate_startup()` doesn't verify `SNOWFLAKE_DSN` is set when needed | Add the same fail-fast pattern used for STT/TTS/LLM/RAG providers | S |
| CODE-1 | `_complete_turn_background` dead, duplicated code | Delete | S |
| ARCH-5 | Duplication-detection heuristic weaker than spec's cardinality language | Implement a real cardinality check, or explicitly document as an accepted MVP simplification | M |
| TEST-3 | `useVoxQuerySession.ts` (901 lines, "the headless engine") has zero direct tests | Add unit tests for session lifecycle, 3-socket coordination, clarification-resume | M |
| STRUCT-1 | `staging_lib/` (974 dead lines, incl. a MySQL/Postgres connector contradicting MVP scope) + 5 stray debug files committed | Delete or relocate with a clear README | S |
| STRUCT-2 | `test_bm25.py` outside `tests/`, never run by `pytest` | Move to `scripts/` or delete | S |
| **PERF-1** | **[New]** `PipelineEventBus` uses a synchronous `queue.Queue` with a 10ms busy-poll loop in the WS route — real CPU/latency/scalability cost on the live-progress channel | Switch to `asyncio.Queue` + `await queue.get()` | S |
| **PERF-2** | **[New]** `RedisSessionStore` uses the synchronous `redis` client inside async handlers — blocks the whole event loop on every session read/write, worst case 2s per call | Switch to `redis.asyncio.Redis` | M |
| **FEAT-2** | **[New]** Clarification timeout/expiry is unimplemented — `ErrorCode.clarification_expired` is dead code, and the DB's `timeout` resolution-type enum value has no corresponding Python enum member | Add `ClarificationResolutionType.timeout`, a background/lazy check that expires stale `ClarificationState`, and actually raise `clarification_expired` | M |
| **ARCH-6** | **[New]** Frontend `deriveCaveatText()`/`formatDataSources()` reference `confidence_reasons`/`data_sources` fields the backend never sends — permanently falls back to generic text | Either implement these fields on the backend (`ResultTrust`) or remove the dead frontend code paths referencing them | M |

### P2 — Hygiene, low-risk, fix opportunistically

| ID | Finding | Fix | Effort |
|---|---|---|---|
| SQL-1 | `sql_policy.py` rejects legitimate `UNION`/`INTERSECT`/`EXCEPT` SELECTs | Broaden accepted-root check | S |
| CONF-1 | `threshold or default` swallows an explicit `0.0` | Use `is not None` check | S |
| AUDIT-1 | Audit writer uses a dedicated thread+event loop for I/O-bound work | Refactor to a same-loop `asyncio.Task` + `asyncio.Queue` | M |
| AUDIT-2 | Busy-wait polling for worker-thread readiness | Signal via `threading.Event`/`Future` | S |
| OBS-1 | `telemetry.emit()` has no secret-detection safety net (currently unviolated) | Add a lightweight regex scrub as defense-in-depth | S |
| DOC-1 | `DeepgramSttProvider` docstring, **and** the `except NotImplementedError` handler in `ws_audio.py`, both describe stale "Slice 4 skeleton" behavior the fully-implemented code no longer has | Update docstring; the exception handler is now dead code and can be removed | S |
| PKG-1 | `pytest`/`pytest-asyncio` declared as main dependencies | Move to a `dev` dependency group | S |
| PKG-2 | No coverage tooling | Add `pytest-cov`, wire into CI | S |
| **PKG-3** | **[New]** `tiktoken` declared as a dependency, never imported/used anywhere (a custom regex tokenizer is used instead, deliberately) | Remove the unused dependency, or switch `TokenCounter` to use it if precision matters more than the documented "credential-free" tradeoff | S |
| **PKG-4** | **[New]** Frontend `engines: "node": ">=20.9.0 <21"` excludes Node 22 (current LTS), contradicting the README's open-ended claim | Widen the range or document the upper bound intentionally | S |
| STRUCT-3 | `docs/dbschema/DB Info` (no extension, space) / `DBScema_Sqls.docx` (typo) | Rename both | S |
| STRUCT-4 | `api/` mixes `ws_<noun>.py` and bare `rest.py`/`telemetry.py` naming | Document convention | S |
| **CODE-2** | **[New]** `from app.main import app` deferred imports inside route handlers, repo-wide (`rest.py`, `telemetry.py`, all three `ws_*.py`) — inverts dependency direction across the whole API surface | Use FastAPI's `Request` object / `request.app.state` instead | M |
| **ROBUST-1** | **[New]** `migrations_runner.py`'s `MIGRATIONS_DIR` uses a fixed relative-path depth and silently no-ops if missing | Make the path explicit/configurable; raise loudly if missing when a Postgres DSN is set | S |
| **DOC-2** | **[New]** `validateNarrative()` (frontend) and `MetricRegistry`/`FollowUpSuggestions` (already tracked) form a recurring pattern: guardrail utilities built + unit-tested in isolation, never wired into the live path | Add a checklist item to the team's Definition of Done: "wired into the live pipeline and covered by an integration test," not just a passing unit test in isolation | — (process fix, not code) |

---

## Part E — What's now fully verified vs. still open

**Now verified (was open in v1):**
- Frontend test suite executed directly — 1/84 failing, root cause identified (TEST-4).
- `contracts.py`, `rest.py`, `ws_pipeline.py`, `ws_tts.py`, `ws_audio.py`, `session.py`, `input_resolver.py`, `tts.py`, `token_count.py`, `events.py`, `providers.py`, `retriever.py`, `audit/store.py`, `audit/noop.py`, `migrations_runner.py`, `api/telemetry.py` — all read in full.
- All 9 frontend components + `page.tsx`, `layout.tsx`, `interactionState.ts`, `pcm.ts`, `api.ts`, `resultSemantics.ts` — all read in full.
- The storytelling/TTS-parallelization question from v1 is now better understood: the storyteller call itself is correctly isolated and shape-only; whether it and the `/ws/tts` call are truly *concurrent* in wall-clock terms is a frontend-orchestration question in `useVoxQuerySession.ts` — that file is read, but proving actual concurrent-vs-sequential timing would require either instrumented tracing or a live run, which is beyond static reading. I'm marking this **[Inferred, not fully resolved]**: the architecture *allows* for client-driven parallel dispatch of the storyteller-backed result and the TTS socket, but I have not traced the exact call ordering in `useVoxQuerySession.ts` to confirm they're dispatched concurrently rather than sequentially.

**Genuinely nothing left unreviewed** in `backend/app/`, `frontend/app/`, or `frontend/lib/` at this point — every source file in both trees has been read directly in this review (excluding generated/config files like `next-env.d.ts`, `tailwind.config.ts`, `postcss.config.mjs`, which carry no product logic).

---

*End of document.*
