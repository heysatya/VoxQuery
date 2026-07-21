# VoxQuery — Architecture & Code Review + Action Plan

**Repo:** `heysatya/VoxQuery` · **Branch:** `voxquery-e2e-integration` · **Commit:** `b7d5cf0` (verified clean working tree)
**Reviewer methodology:** `architecture-code-review` skill (12-section rubric — spec traceability, trust boundaries, data modeling, API contracts, orchestration, observability, resilience, test/CI, dependency hygiene, folder structure, frontend, AI-pipeline-specific). Every finding below is tagged **[Verified]** (I read the exact code and/or executed a command) or **[Inferred]** (plausible from evidence but not directly executed).

---

## 0. Executive Summary

VoxQuery is a materially above-average MVP for a project this size: real spec-driven development (532-line PRD → 893-line engineering spec → gated commit history), a genuinely sound SQL trust boundary, a real LangGraph state machine, real RS256 auth, real hybrid BM25+vector retrieval with Reciprocal Rank Fusion, and defensive startup config validation that hard-blocks unsafe prod configs.

But the branch's own claims — "Production-Ready E2E Certification," "Stabilize end-to-end pipeline... E2E testing" — are not fully backed by what's on disk:

- **2 of 175 backend tests fail on execution**, on a genuine API contract drift (not flakiness).
- **No CI exists anywhere in the repo** — nothing would have caught the above before merge.
- **A ~974-line, fully dead, parallel implementation tree** (`backend/staging_lib/`) sits committed in the repo, unreferenced by the live app — including a second Postgres/MySQL/Snowflake connector abstraction that contradicts the PRD's "Snowflake only, multi-warehouse is V2" scope.
- **The "schema-aware, multi-tenant RAG" is not actually tenant-configurable at runtime.** The query rewriter's business-glossary synonyms and the metric registry are hardcoded to one demo e-commerce schema (or unwired entirely), not sourced from the tenant-onboarding glossary the PRD mandates.
- **Snowflake DSN encryption-at-rest and per-tenant DSN routing, both explicit PRD security/architecture requirements, are not implemented** — the app boots with a single global DSN from an env var, and the `tenant_connections` table that was clearly designed for per-tenant DSNs is never queried by the running app.
- **Model choice silently deviates from spec** (Haiku in place of the PRD-mandated Sonnet for SQL generation) with no recorded rationale, and the confidence-scoring formula's LLM-self-confidence term is permanently `None` in the live Claude adapter — a third of the intended confidence formula is dead weight in production.

None of this means the system is badly built — the craftsmanship in the parts that *are* wired up is genuinely good. It means the "production-ready / certified" label is premature, and the gap between what the docs claim and what's on disk is itself the top risk to track.

---

## 1. Methodology note (per your question about skills)

Before this pass, I had no dedicated code/architecture-review skill — findings came from general judgment applied ad hoc, which is exactly the blind-spot risk you flagged. I built and saved a skill, `architecture-code-review` (`SKILL.md` + `references/action-plan-template.md`), encoding a 12-section rubric so every review — this one and future ones — walks the same checklist instead of whatever happens to catch my eye. Every section below maps to one rubric item. I did not run the full skill-creator eval-optimization loop (that tunes *when* a skill auto-triggers across unrelated future conversations via trigger-phrase benchmarking) because it wasn't the bottleneck here — the checklist itself was.

---

## 2. Subsystem-by-subsystem deep review

### 2.1 SQL Trust Boundary (`app/warehouse/sql_policy.py`) — **Strong**

**[Verified]** Every generated statement is parsed with `sqlglot`; non-`SELECT` roots, multi-statement payloads (stacked-query injection), explicit `CROSS JOIN`, and joins without `ON`/`USING` are all rejected before a Snowflake connection opens. `LIMIT` is injected/clamped to 10,000. An optional schema allowlist rejects hallucinated table/column references. `test_warehouse.py` proves the connector's `connect()` is never called on policy failure (`mock_connect.assert_not_called()`), which is the right way to test a trust boundary — asserting the *absence* of a dangerous side effect, not just the presence of an exception.

**Gap [Verified]:** `isinstance(parsed, exp.Select)` rejects `UNION`/`INTERSECT`/`EXCEPT` queries outright (sqlglot parses these as `exp.Union`, not `exp.Select`), even though they're legitimate read-only SQL. Not a security bug — a functionality gap that will surface as confusing rejections for otherwise-safe analytical queries.

### 2.2 Orchestration (`app/services/graph.py`, `app/services/pipeline.py`) — **Strong, with debt**

**[Verified]** LangGraph state machine with explicit conditional edges for retry-once-on-validation-failure and the clarification branch; each node is independently unit-testable. The SQL-hash-must-match-the-confidence-scored-hash assertion in `execution_node` is good defensive engineering — it guards against SQL silently diverging between scoring and execution.

**Debt [Verified]:** `pipeline.py` defines `_complete_turn_background`, a ~35-line near-duplicate of `_run_turn_background`. `grep -rn "_complete_turn_background" backend/` returns only its own definition — it is dead code. This is a DRY violation *and* a maintenance trap: if it's ever wired in later, it will have silently diverged from the maintained path.

**Weaker-than-spec [Verified]:** `detect_possible_duplication()` (PRD 4.5: "detectable via row-count anomaly vs expected cardinality") is a textual heuristic — `row_count >= 100 and " join " in sql.lower() and "distinct" not in sql.lower()`. This false-positives on any query with `join_date`/`is_distinct_flag`-style identifiers and does no actual cardinality estimation.

### 2.3 RAG / Retrieval (`app/rag/pgvector.py`, `query_rewriter.py`, `metric_registry.py`) — **Mixed: real hybrid search, but not actually multi-tenant**

**[Verified] Strength:** `pgvector.py` genuinely implements hybrid retrieval — a cosine-similarity vector query and a Postgres full-text (`ts_rank`) BM25-style query, fused with textbook Reciprocal Rank Fusion (`1/(k+rank+1)`, `k=60`, the standard RRF constant). This part of the README's claim is accurate.

**[Verified] Major gap — hardcoded, single-schema glossary, contradicting the PRD's multi-tenant design:** `query_rewriter.py`'s `METRIC_SYNONYMS`/`TABLE_SYNONYMS`/`DOMAIN_SIGNALS` are hardcoded Python dicts keyed to one specific e-commerce demo schema (`ORDERS`, `ORDER_ITEMS`, `CUSTOMERS`, `SELLERS`, `ORDER_REVIEWS`, `GEOLOCATION` — an Olist-style dataset). `rewrite_query_node` in `graph.py` instantiates `QueryRewriter()` with **no arguments**, so it always uses these hardcoded defaults — never a tenant's admin-configured business glossary. This directly contradicts PRD §4.4: *"the admin explicitly maps executive-facing terms... this glossary is embedded alongside schema chunks and co-retrieved."* As shipped, this only works correctly for the one demo tenant whose table names match the hardcoded dict.

**[Verified] Unwired subsystem:** `MetricRegistry` (loads certified metric definitions from `data/metrics.yaml`, explicitly described as *"Critical for preventing LLM metric hallucination"*) is **never instantiated anywhere in the live application** — `grep` for `MetricRegistry(` across `app/` finds only the class's own docstring example. The README's claim of a "semantic Metric Registry" powering retrieval overstates what's wired into the running pipeline.

**[Verified] Scale-mismatch bug:** `rag_score = final_chunks[0].similarity` after RRF fusion takes the *raw per-source* similarity of the top fused result — cosine similarity (~0–1) if it came from the vector branch, or a `ts_rank` value (arbitrary small-magnitude units) if it came from the BM25 branch. `compute_confidence()` then weights this at 40% of the composite confidence score as if it were a normalized 0–1 signal. When the top RRF result originates from the BM25 branch, the confidence score is computed against an out-of-scale number — a real correctness bug in the confidence pipeline, not just a design nit.

### 2.4 LLM Adapter (`app/llm/claude.py`, `app/llm/adapter.py`) — **Functional, with un-hardened prompt construction and a dead formula term**

**[Verified]:** Clean ABC seam (`LlmAdapter`/`Storyteller`), no Claude-specific constructs leak outside `claude.py`, matching the PRD's model-agnostic requirement.

**[Verified] Model deviates from spec, undocumented:** `config.py`: `canonical_sql_model` defaults to `claude-haiku-4-5-20251001`. PRD §7 mandates `claude-sonnet-4-20250514` specifically *"for best-in-class SQL generation & schema reasoning."* No ADR, comment, or test documents the tradeoff against the PRD's 85%-first-attempt-accuracy target.

**[Verified] `llm_self_confidence` is always `None` in production:** `generate_sql()` never asks Claude to self-report confidence (no structured output field for it) and always returns `SqlGenerationResult(..., llm_self_confidence=None, ...)`. `compute_confidence()`'s weighting scheme (`DEFAULT_WEIGHTS = {rag: 0.40, validation: 0.20, llm: 0.40}`) was clearly designed as a three-factor formula; in the live path it silently collapses to a renormalized two-factor formula (rag ≈0.67, validation ≈0.33) on every single query. This isn't wrong per se, but it means 40% of the intended signal is permanently absent and nobody currently sees that in the confidence tier output.

**[Verified] No system/user prompt separation:** `generate_sql()` builds one long string containing instructions, schema context, conversation history, and the user's raw request, all passed as a single `user`-role message — no `system` parameter is used at all. This is a moderate prompt-injection *and* prompt-reliability weakness (Anthropic's own guidance recommends separating trusted instructions from untrusted content via `system` + clear delimiters). The blast radius is bounded by the downstream `sql_policy.py` allowlist (worst case is an allowed read, not arbitrary execution), but it's still a real hardening gap, and separating system/user content generally improves instruction-following independent of security.

### 2.5 Auth & Config (`app/middleware/auth.py`, `app/config.py`) — **Strong**

**[Verified]:** RS256 JWKS verification, required-claims enforcement, 60s leeway, cached verifier. `Settings.validate_startup()` — confirmed called at import time in `main.py` — hard-fails boot if any `*_PROVIDER=fake`/`AUTH_MODE=fake` is set in staging/production, and enforces `https://`/`rediss://` in those environments. This is genuinely good defense-in-depth, not just documentation.

**Gap [Verified]:** `validate_startup()` does **not** check that `SNOWFLAKE_DSN` is actually set when `WAREHOUSE_PROVIDER=snowflake`. `main.py` line 102: `dsn = settings.snowflake_dsn or "dummy_dsn"` — a misconfigured production deploy with `WAREHOUSE_PROVIDER=snowflake` but no `SNOWFLAKE_DSN` env var will boot successfully and fail confusingly at first query time instead of failing fast at startup like every other provider.

### 2.6 Multi-tenancy & Data Confidentiality — **[Verified] Significant gap between schema design and runtime wiring**

- `db/migrations/001_voice_subsystem.sql` defines `tenant_connections(tenant_id PK, snowflake_dsn TEXT NOT NULL, ...)` — clearly designed for per-tenant Snowflake DSN storage, matching the PRD's *"separate Postgres schema + encrypted Snowflake DSN per tenant"* mitigation for the "won't share credentials with external vendor" risk.
- **[Verified]** `grep` across `app/` for `tenant_connections` / `snowflake_dsn` shows it is only referenced in `config.py` (a single global `Settings` field) and `main.py` (used to build one global `SnowflakeWarehouseConnector` at startup). **The `tenant_connections` table is never queried by the running application.** Every tenant shares one global DSN from a single env var.
- **[Verified]** No encryption logic exists anywhere in `app/` — `grep -rln "encrypt|AES|Fernet|cryptography" backend/app/` returns nothing, and no such package is a dependency. The PRD's explicit security NFR *"Snowflake DSN stored encrypted at rest (AES-256)"* is not implemented; the DSN is stored/read as plain text.
- Net effect: this is fine for a true single-tenant pilot (which is all the MVP needs), but the DB schema and the "single-tenant logical isolation... per tenant" language in the PRD imply multi-tenant readiness that does not currently exist in the app layer. If a second pilot tenant is onboarded before this is fixed, they will share the first tenant's Snowflake credentials.

### 2.7 Audit / Persistence (`app/audit/postgres.py`) — **Strong, with one over-engineered pattern**

**[Verified] Strength:** An explicit, tested runtime invariant — `enqueue_turn()` checks for a `rows` key in the serialized result and refuses to enqueue (emitting a `security_violation` telemetry event) rather than ever persisting raw warehouse rows. This is exactly the right way to enforce the PRD's "raw result rows never leave the execution boundary" confidentiality guarantee — as code, not just as a document.

**[Verified] Complexity smell:** The audit writer runs on a dedicated OS thread with its own `asyncio` event loop and `asyncpg` pool, communicating with the main FastAPI loop via `call_soon_threadsafe`. Since `asyncpg` is already async-native and I/O-bound (not CPU-bound), a same-loop background `asyncio.Task` + `asyncio.Queue` would achieve the same non-blocking fire-and-forget behavior with less moving-parts complexity (no cross-thread scheduling, no thread-join-with-timeout shutdown logic). Not wrong, just more machinery than the problem needs. Also: `start()` busy-waits (`await asyncio.sleep(0.01)` in a loop) for the worker thread's event loop to initialize, instead of signaling via a `threading.Event`/`asyncio.Future` — minor but a real busy-wait.

### 2.8 Observability (`app/services/telemetry.py`, `app/observability/langfuse.py`) — **Strong**

**[Verified]:** Tiered structured logging (`tier=1` trust invariant / `2` AI quality / `3` business), fail-safe (`emit()` never raises), Langfuse fully wrapped so a tracing failure can never crash the pipeline, `propagate_attributes` correctly carries tenant/session/model context.

**Gap [Verified, currently unviolated]:** `emit()`'s own docstring states it *"has no secret-detection logic"* — callers are trusted not to pass secrets into telemetry payloads. I grepped every `emit(...)` call site for secret-shaped kwargs (`dsn`, `token`, `api_key`, `password`, `secret`) and found none currently — so this is not an active leak today, but it's an unguarded blast-radius: one future careless `emit("x", dsn=raw_dsn)` call anywhere in the codebase would ship a secret straight to stdout logs with no safety net, unlike the DSN/token redaction that *is* implemented at the warehouse-error and log-filter layers.

### 2.9 Voice I/O (`app/core/stt.py`, ws routes) — **More complete than its own docs claim**

**[Verified]:** `DeepgramSttProvider.stream()` is a real, complete streaming implementation — proper `websockets` connect, concurrent sender/receiver tasks, 15s idle timeout, and API-key redaction from both error-frame messages and exception strings. The class's own docstring, however, says *"This skeleton exists... The stream() method raises NotImplementedError until Slice 4 is implemented"* — stale documentation describing behavior the code no longer has. Low-severity but worth fixing: a future maintainer skimming the docstring could wrongly assume this path is untested placeholder code.

### 2.10 Frontend (`frontend/app/hooks/useVoxQuerySession.ts` and friends) — **Thin test coverage relative to risk**

**[Verified]:** `useVoxQuerySession.ts` is 901 lines and is described in the README as "the headless engine" driving the entire 3-state UI (session lifecycle, 3 WebSocket connections for audio/pipeline/TTS, clarification flow, transcript editing). **[Verified]** Only 5 test files exist in the whole frontend (`page.test.tsx`, `interactionState.test.ts`, `api.test.ts`, `pcm.test.ts`, `resultSemantics.test.ts`) against 13 substantive components/hooks, and none target this hook directly. This is the classic "coverage inversely correlated with risk" pattern the rubric asks to check for — the single highest-blast-radius piece of frontend logic (state desync across three concurrent sockets would be a genuinely hard bug to diagnose in production) is the one place without direct tests.

### 2.11 Test Suite & CI — **[Verified] Currently red, and nothing gates it**

Ran the backend suite directly (`python3 -m pytest tests/ -q` after installing declared dependencies):

```
2 failed, 173 passed, 1 skipped, 4 warnings in 7.89s
FAILED tests/test_rag.py::test_pgvector_retriever_success
FAILED tests/test_rag.py::test_pgvector_retriever_empty
AttributeError: 'str' object has no attribute 'get_retrieval_query'
```

Root cause: `PgVectorSchemaRetriever.retrieve()` now takes a `RewrittenQuery` object (post the query-rewriter/RRF refactor), but `test_rag.py` still calls it with a raw string — the test file's own docstring states a stale contract: `SPEC: PgVectorSchemaRetriever.retrieve(submitted_text, tenant_id)`. This is test-rot on exactly the retrieval path the system depends on to prevent hallucinated SQL.

**[Verified]** `find . -iname "*.yml" -path "*workflows*"` and `ls .github` both come back empty — **there is no CI configuration anywhere in this repository.** Nothing would catch this regression, or any future one, before merge. The "stabilize e2e pipeline" / "production-ready" claims in the commit message and README are not backed by a green, gated test run at `HEAD`.

Where the suite *is* green, it's genuinely good: DSN redaction, empty-DSN rejection, ownership/ForbiddenTurn checks, non-SELECT rejection with `mock_connect.assert_not_called()` — real adversarial-style tests on the safety-critical paths, not just happy-path coverage.

### 2.12 Dependency & Packaging Hygiene — **[Verified] Minor**

- `pyproject.toml` lists `pytest`/`pytest-asyncio` as main (non-dev) dependencies with no `[dependency-groups]`/dev split — a production install pulls in the test framework.
- No `pytest-cov` or equivalent anywhere — there's currently no way to know actual line/branch coverage %, only which test files exist.

---

## 3. Folder / File Structure Assessment

### 3.1 What's committed that shouldn't be

**[Verified via `git ls-files`]**, all of the following are genuinely tracked in git, not artifacts of my local clone:

| Path | Issue |
|---|---|
| `backend/staging_lib/` (15 files, 974 lines) | Fully dead, unreferenced parallel implementation — a second DB connector abstraction (with **MySQL and Postgres providers**, contradicting the PRD's explicit "Snowflake only for MVP, multi-warehouse is out of scope") plus a second LangGraph pipeline, SQL validator, chart selector, TTS summary generator, rate limiter, and guardrails module. |
| `backend/rag_test_output.txt` … `rag_test_output5.txt` | 5 stray manual debug-output text files (40KB) committed to the repo root of `backend/`. |
| `backend/test_bm25.py` | A standalone ad hoc script at the backend root (not under `tests/`), requires live `SUPABASE_DATABASE_URL` to run, and — because `pyproject.toml` sets `testpaths = ["tests"]` — **is never executed by `pytest` at all.** It's neither a real test nor a real script; it's an orphaned scratch file. |

**Recommendation:** delete `staging_lib/` and the `rag_test_output*.txt` files outright (or, if `staging_lib` is intentionally kept as a "future work" sketchpad, move it to a clearly-labeled `experiments/` or `rfc/` directory *outside* `backend/`, with a README explaining it's not live code — as-is, any new engineer will burn real time figuring out whether `staging_lib/db/providers/snowflake.py` or `app/warehouse/snowflake.py` is the real one). Move `test_bm25.py` into `backend/scripts/` (it's structurally a manual diagnostic script, like `ingest_kaggle.py`/`sync_schema.py` which already live there) or delete it if superseded by `tests/test_rag.py`.

### 3.2 Naming & organization inconsistencies

- **WebSocket route naming is inconsistent**: `ws_audio.py`, `ws_pipeline.py`, `ws_tts.py` follow a `ws_<noun>` pattern — fine — but `rest.py` and `telemetry.py` (also REST) don't follow a parallel `rest_<noun>` convention, so the `api/` folder mixes two naming schemes for what's otherwise a flat, single-level directory of route modules. Minor, but worth normalizing (`rest.py` → arguably fine as the single catch-all REST router; just document the convention).
- **`docs/dbschema/` mixes binary office documents into a git repo**: `DBScema_Sqls.docx` (note: filename typo — "Schema" is misspelled), `DBSchema_Diagram.pdf`, `voxquery-sampleexecutivequestions.xlsx`, alongside a proper `schema-review.md`. Binary docs in git bloat history and can't be diffed/reviewed in PRs. Recommend converting the diagram to a checked-in Mermaid/`.md` source (rendered on demand) and moving the `.docx`/`.xlsx` content into the markdown files where feasible, keeping binaries only where a tool genuinely requires them (e.g., a stakeholder-facing slide deck).
- **`docs/dbschema/DB Info`** — a file with a space in its name and no extension. Rename to something like `db-info.md` or `db-info.txt` with an explicit extension.
- **Two SQL "schema" sources of truth**: `db/migrations/` (the real, applied migrations) vs `db/demo_warehouse/001_ecommerce_schema.sql` (the demo Snowflake dataset's DDL) — these serve different purposes (app DB vs. customer warehouse) but sit in sibling folders under `db/` with similar naming (`001_...sql` in both), which invites confusion about which one a migration runner actually applies. Recommend renaming to `db/app_migrations/` and `db/demo_warehouse_seed/` (or similar) to make the distinction unmistakable from the path alone.
- **Frontend component folders are named by UI concept, not by feature/domain** (`components/clarification/`, `components/data/`, `components/hero/`, `components/insight/`, `components/notice/`, `components/query/`, `components/thread/`, `components/transcript/`) — this is a reasonable, fairly common Next.js pattern and is not wrong, but it means there's no single place that maps 1:1 to the PRD's subsystem list (4.1 Voice Input, 4.2 Clarification, 4.6 Chart Selector, etc.), unlike the backend's `docs/voice-subsystem/engineering-spec.md` module map which explicitly lists canonical component names. Worth adding a short `frontend/ARCHITECTURE.md` mapping PRD sections → component folders, mirroring what already exists for the backend.

### 3.3 What's genuinely good about the structure

- Backend `app/` is cleanly layered by responsibility (`api/`, `core/`, `llm/`, `warehouse/`, `rag/`, `audit/`, `observability/`, `middleware/`, `models/`, `services/`) and this maps directly onto the engineering-spec's module map — a real example of docs and code structure staying in sync (outside of `staging_lib`).
- `models/contracts.py` as a single Pydantic contracts file is a defensible choice at this scale (617 lines) — keeps all wire/domain types in one auditable place rather than scattered.
- Test file naming (`test_<module>.py`) mirrors source module names 1:1, which is good — except for the orphaned `test_bm25.py` noted above.

### 3.4 Proposed structural changes (concrete, not hand-wavy)

```diff
  backend/
- ├── staging_lib/                     # DELETE (dead, unreferenced, contradicts scope)
+ │                                     # or: mv to /experiments/staging_lib/ + README
- ├── rag_test_output.txt .. 5.txt      # DELETE
- ├── test_bm25.py                      # mv -> backend/scripts/probe_bm25.py
  ├── app/                              # unchanged — this layer is well-organized
  ├── data/
  ├── scripts/
  └── tests/

  db/
- ├── demo_warehouse/001_ecommerce_schema.sql
+ ├── demo_warehouse_seed/001_ecommerce_schema.sql
- ├── migrations/
+ ├── app_migrations/

  docs/
  ├── dbschema/
- │   ├── DB Info
+ │   ├── db-info.md
- │   ├── DBScema_Sqls.docx             # fold into schema-review.md where practical
- │   ├── DBSchema_Diagram.pdf          # replace with checked-in Mermaid source
  │   └── schema-review.md
  └── voice-subsystem/

  frontend/
  ├── app/
+ │   ├── ARCHITECTURE.md               # NEW: PRD section -> component folder map
  │   ├── components/
  │   └── hooks/
```

---

## 4. Consolidated Action Plan

### P0 — Fix before any further "production-ready" claim

| ID | Finding | Evidence | Fix | Effort |
|---|---|---|---|---|
| TEST-1 | 2/175 backend tests fail — `test_rag.py` calls `retrieve()` with a stale (pre-refactor) string argument instead of a `RewrittenQuery` | Direct `pytest` run (§2.11) | Update `test_rag.py` to construct/mock a `RewrittenQuery`; re-run full suite to confirm 175/175 | S |
| TEST-2 | No CI exists at all — nothing gates merges | `find`/`.github` empty (§2.11) | Add a minimal GitHub Actions workflow: backend `pytest` + `ruff`, frontend `vitest` + `eslint`, required to pass before merge to this branch | S |
| SEC-1 | Snowflake DSN not encrypted at rest despite explicit PRD security requirement | `tenant_connections.snowflake_dsn TEXT`, no crypto library anywhere in `app/` (§2.6) | Encrypt DSN at write time (e.g. `cryptography.Fernet` with a KMS-backed key), decrypt only at connector construction; add a test asserting the column never contains a plaintext-parseable DSN | M |
| SEC-2 | Per-tenant DSN routing is not wired — one global DSN serves all tenants despite a `tenant_connections` table designed for per-tenant storage | `main.py` builds one global `SnowflakeWarehouseConnector` from `settings.snowflake_dsn`; `tenant_connections` never queried (§2.6) | Wire `PipelineOrchestrator`/`execution_node` to resolve `WarehouseConnector` per `claims.tenant_id` via `tenant_connections`; block onboarding a second pilot tenant until this lands | M |
| ARCH-1 | Business glossary / metric synonyms are hardcoded to one demo schema, not tenant-configurable — contradicts PRD §4.4's admin-glossary requirement | `query_rewriter.py` defaults, `QueryRewriter()` called with no args in `graph.py` (§2.3) | Load `metric_synonyms`/`table_synonyms` per-tenant from `schema_chunks`/a new `tenant_glossary` table at `rewrite_query_node` time, falling back to the current hardcoded set only for the demo tenant | L |

### P1 — Architecturally significant, fix within the next iteration

| ID | Finding | Evidence | Fix | Effort |
|---|---|---|---|---|
| ARCH-2 | `MetricRegistry` is fully unwired dead code despite being described as "critical for preventing LLM metric hallucination" | `grep` for instantiation finds none (§2.3) | Either wire it into `sql_generation_node`'s prompt construction (inject certified metric defs alongside schema chunks) or remove it and correct the README's claim | M |
| ARCH-3 | RAG confidence score mixes incompatible similarity scales (cosine vs. `ts_rank`) post-RRF | `pgvector.py`: `rag_score = final_chunks[0].similarity` (§2.3) | Compute `rag_score` from the normalized RRF fusion score itself (already 0–1-ish by construction with `k=60`), not the source-specific `similarity` field | S |
| ARCH-4 | `llm_self_confidence` is always `None` in the live Claude adapter — 40% of the intended confidence formula is dead in production | `claude.py generate_sql()`, `confidence.py` `DEFAULT_WEIGHTS` (§2.4) | Either have Claude emit a structured self-confidence field (e.g., via tool-use/JSON output) and populate it, or remove the `llm` weight/dead branch from `compute_confidence` and document that confidence is currently RAG+validation only | M |
| MODEL-1 | SQL-generation model silently deviates from PRD-mandated Sonnet to Haiku, no recorded rationale or accuracy validation | `config.py canonical_sql_model` default, README (§2.4) | Write a short ADR: cost/latency numbers vs. accuracy numbers on a representative query set (`tests/golden_queries.yaml` already exists — use it) against the PRD's 85% first-attempt-accuracy target; decide and document | S |
| SEC-3 | No `system` parameter used in `generate_sql()` — instructions and untrusted schema/history/user content are concatenated into one `user` message | `claude.py` prompt construction (§2.4) | Move static instructions into the `system` parameter; wrap untrusted content (schema, history, user text) in clear delimiters within the user turn | S |
| SEC-4 | `validate_startup()` doesn't verify `SNOWFLAKE_DSN` is set when `WAREHOUSE_PROVIDER=snowflake` | `main.py`: `dsn = settings.snowflake_dsn or "dummy_dsn"` (§2.5) | Add the same fail-fast pattern used for STT/TTS/LLM/RAG providers | S |
| CODE-1 | `_complete_turn_background` is dead, duplicated orchestration code | `grep` confirms zero call sites (§2.2) | Delete it | S |
| ARCH-5 | Duplication-detection heuristic is textual substring matching, weaker than PRD's "row-count anomaly vs. expected cardinality" language | `detect_possible_duplication()` (§2.2) | Either implement a real cardinality estimate (e.g., compare result row count against a pre-join `COUNT(DISTINCT primary_key)` check) or explicitly document the current heuristic as an accepted MVP simplification in the PRD/spec | M |
| TEST-3 | `useVoxQuerySession.ts` (901 lines, described as "the headless engine") has zero direct tests | File census (§2.10) | Add unit tests for session lifecycle, the 3-socket coordination, and clarification-resume paths, using `vitest` mocks for the WebSocket layer | M |
| STRUCT-1 | `staging_lib/` (974 lines, dead) and 5 stray debug output files committed to the repo | `git ls-files` (§3.1) | Delete or relocate to a clearly-labeled non-`app/` experiments folder with a README | S |
| STRUCT-2 | `test_bm25.py` sits outside `tests/`, is never run by `pytest` (`testpaths=["tests"]`), and requires live credentials | `pyproject.toml`, file content (§3.1) | Move to `backend/scripts/` as a manual diagnostic tool, or delete if superseded by `tests/test_rag.py` | S |

### P2 — Hygiene, low-risk, fix opportunistically

| ID | Finding | Fix | Effort |
|---|---|---|---|
| SQL-1 | `sql_policy.py` rejects legitimate `UNION`/`INTERSECT`/`EXCEPT` SELECT queries via strict `isinstance(parsed, exp.Select)` | Broaden the accepted-root check to include `exp.Union`/`exp.Intersect`/`exp.Except` whose ultimate leaves are all `Select` | S |
| CONF-1 | `compute_confidence`'s `threshold or settings.confidence_threshold_primary` treats an explicit `threshold=0.0` as falsy | Change to `threshold if threshold is not None else settings.confidence_threshold_primary` | S |
| AUDIT-1 | Audit writer uses a dedicated OS thread + event loop for what is a purely I/O-bound async workload | Refactor to a same-loop `asyncio.Task` + `asyncio.Queue`; drop the thread-join shutdown machinery | M |
| AUDIT-2 | `start()` busy-waits on `asyncio.sleep(0.01)` polling loop for worker-thread readiness | Signal readiness via `threading.Event`/`concurrent.futures.Future` instead | S |
| OBS-1 | `telemetry.emit()` has no secret-detection safety net (currently unviolated, but unguarded) | Add a lightweight regex scrub for common secret shapes (`sk-`, `Bearer `, DSN patterns) in `_safe_dumps` as defense-in-depth | S |
| DOC-1 | `DeepgramSttProvider` docstring says it "raises NotImplementedError" — stale, contradicts the fully-implemented code below it | Update docstring | S |
| PKG-1 | `pytest`/`pytest-asyncio` declared as main (non-dev) dependencies | Move to a `[dependency-groups] dev` section | S |
| PKG-2 | No coverage tooling (`pytest-cov`) anywhere | Add and wire into the new CI workflow (TEST-2) | S |
| STRUCT-3 | `docs/dbschema/DB Info` — no extension, space in filename; `DBScema_Sqls.docx` — filename typo | Rename both | S |
| STRUCT-4 | `api/` route files mix `ws_<noun>.py` and bare `rest.py`/`telemetry.py` naming | Document the convention explicitly (not necessarily rename) | S |

---

## 5. What I have *not* yet verified (flagging rather than guessing)

- I did not execute the frontend test suite (`npm install && npm run test`) — the "thin frontend coverage" finding (§2.10) is based on a file census, which is solid evidence, but I have not confirmed the 5 existing frontend tests currently pass.
- I did not verify the parallelization claim for storytelling + TTS (PRD step 8a/9) end-to-end — `render_node` calls the storyteller inline, but TTS appears to be client-driven via `/ws/tts` separately, and confirming actual latency-budget compliance would require either a live trace or reading the frontend's socket-orchestration timing in `useVoxQuerySession.ts` in detail.
- I have not reviewed `app/models/contracts.py` (617 lines) or `app/api/rest.py`/`ws_pipeline.py`/`ws_tts.py` at the same line-by-line depth as the modules above — if you want the same rigor applied there (contract completeness, REST error-envelope consistency, WS reconnect/backpressure handling), say so and I'll do that pass next.

---

*End of document.*
