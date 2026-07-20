# VoxQuery Remediation — Coding Agent Implementation Prompt

Paste this whole document to your coding agent as the task brief. It references three
review documents that must be loaded into context first:

1. `VoxQuery_Architecture_Review_and_Action_Plan_v1.md` (v1)
2. `VoxQuery_Architecture_Review_and_Action_Plan_v2.md` (v2 — supersedes v1, complete)
3. `VoxQuery_Part_F_WorldClass_and_ProductionReadiness_Addendum.md` (Part F)

---

## Your mandate

You are implementing a remediation plan. Every item you
will work on is documented in the three files above with exact file:line evidence — do
not re-derive findings from scratch; read the evidence, then act on it.

**You must follow this discipline for every single item, no exceptions:**

```
1. BEHAVIOR SPEC  → Write a short, explicit behavior spec BEFORE touching code:
                     "Given <state>, when <action>, then <observable outcome>."
                     One spec per acceptance criterion. Put it as a comment block or
                     docstring at the top of the relevant test file, or in a
                     `specs/<item-id>.md` file if the change spans multiple files.

2. TEST            → Write the test(s) that encode the behavior spec, and confirm they
                     FAIL for the right reason (not a typo/import error) before writing
                     any implementation. Run them and paste the failing output as
                     evidence in your work log before proceeding.

3. CODE            → Write the minimum implementation that makes the test(s) pass.
                     Do not add scope beyond what the spec/test describes.

4. VERIFY          → Run the full existing test suite (not just your new tests) plus
                     lint. Confirm nothing else broke. Paste the full pass/fail summary.

5. DOD CHECK       → An item is only "done" when: spec exists, tests exist and pass,
                     full suite is green, AND — for anything marked "wire into live
                     path" below — there is an integration/e2e test proving it's
                     actually reachable from a real request, not just unit-tested in
                     isolation. (This last rule exists because the review found three
                     separate cases — MetricRegistry, validateNarrative,
                     proactive_questions — of well-unit-tested code that was never
                     wired into the live pipeline. Do not repeat that pattern.)
```

Do not mark any item complete without all five steps evidenced in your output. If you
cannot complete a step (e.g., you don't have a live Snowflake/Redis instance to test
against), say so explicitly and mark the item **blocked**, not done.

---

## Sequencing — work in this exact order

Do not skip ahead. Later phases assume earlier phases are green. Within a phase, order
is not critical unless noted.

### Phase 0 — Stop the bleeding (get to a real, CI-gated green baseline)

Everything else is unreliable until this phase is done, because right now nothing
gates merges and two tests are already silently broken.

- **TEST-1**: Fix `backend/tests/test_rag.py` — `PgVectorSchemaRetriever.retrieve()` now
  takes a `RewrittenQuery` object, not a raw string. Update the test to construct/mock
  one. Spec: "Given a tenant_id and a rewritten query object, when retrieve() is called,
  then it returns fused (RRF) results without raising AttributeError." Verify: full
  backend suite reaches 175/175 (or the new correct total after other fixes).
- **TEST-4**: Fix `frontend/app/page.test.tsx` — decide whether `"Moderate confidence"`
  or `"Partial match"` is the correct product copy for the Medium confidence tier
  (check with product/design if unclear; default to keeping the live component's
  current copy, `"Partial match"`, and updating the test, unless told otherwise).
  Verify: full frontend suite reaches 84/84 (or new correct total).
- **TEST-2**: Add CI. Create `.github/workflows/ci.yml` (or equivalent) that on every PR
  runs: `backend: pytest + ruff`, `frontend: vitest + eslint + tsc --noEmit`. Make it a
  required check. Spec: "Given a PR with a failing test, when CI runs, then the PR is
  blocked from merge." Verify by deliberately breaking a test locally, confirming CI
  would fail, then reverting.
- **STRUCT-1**: Delete `backend/staging_lib/` (974 lines, confirmed dead/unreferenced —
  BUT read `staging_lib/pipeline/rate_limiter.py` and `staging_lib/pipeline/guardrails.py`
  first and port the useful logic per PROD-1 below before deleting the directory).
  Also delete `backend/rag_test_output.txt` through `rag_test_output5.txt`.
- **STRUCT-2**: Move `backend/test_bm25.py` to `backend/scripts/probe_bm25.py` (it's a
  manual diagnostic tool requiring live credentials, not a pytest test — `testpaths`
  never picked it up anyway).
- **PKG-1**: Move `pytest`/`pytest-asyncio` to a dev-dependency group in `pyproject.toml`.
- **PKG-2**: Add `pytest-cov` to CI; report coverage % on every PR (informational at
  first — don't gate on a coverage threshold yet, just get visibility).
- **PKG-3**: Remove the unused `tiktoken` dependency (or wire `TokenCounter` to actually
  use it — pick one, don't leave it declared-but-unused).
- **PKG-4**: Fix `frontend/package.json` `engines.node` — either widen to
  `">=20.9.0"` (open-ended, matching the README) or document why the upper bound exists.

### Phase 1 — P0 security & correctness (block any "production ready" claim)

- **SEC-1**: Encrypt `tenant_connections.snowflake_dsn` at rest.
  - Spec: "Given a DSN is written to `tenant_connections`, when the row is read directly
    from Postgres (bypassing the app), then the DSN is not parseable as a plaintext
    connection string."
  - Test: write a DSN through the app layer, query the raw column directly via
    `asyncpg`, assert it does NOT match the plaintext pattern; then read it back through
    the app layer and assert it DOES match (round-trip correctness).
  - Implementation: `cryptography.Fernet` (or KMS-backed equivalent) with the key
    sourced from settings/env, decrypt only at `WarehouseConnector` construction time.
    Add `PKG: cryptography` dependency.
- **SEC-2**: Wire per-tenant DSN routing.
  - Spec: "Given two tenants with different `tenant_connections` rows, when each submits
    a query, then each query executes against its own tenant's Snowflake DSN, never the
    other's."
  - Test: seed two tenant rows with distinct (fake/mock) DSNs, run the pipeline for
    each, assert the connector received the correct DSN per tenant.
  - Implementation: `PipelineOrchestrator`/`execution_node` resolves the
    `WarehouseConnector` per `claims.tenant_id` by querying `tenant_connections`
    (through the now-decrypting SEC-1 path), instead of the current single global
    `app.state` connector built once at startup. Cache resolved connectors per-tenant
    to avoid a DB round-trip on every query.
  - **Do not allow onboarding a second pilot tenant until this item is done and tested.**
- **ARCH-1**: Make the business glossary tenant-configurable.
  - Spec: "Given a tenant has custom metric/table synonyms stored in the database, when
    a query is rewritten for that tenant, then the tenant's synonyms are used instead of
    the hardcoded defaults; given a tenant has no custom synonyms, then the hardcoded
    defaults are used as a fallback (preserving current demo-tenant behavior)."
  - Test: seed a `tenant_glossary` row (new table — see implementation) for a test
    tenant with a synonym the hardcoded map doesn't have, assert `QueryRewriter` for
    that tenant picks it up; assert an unconfigured tenant still gets the current
    hardcoded defaults (no regression).
  - Implementation: add a `tenant_glossary` table (tenant_id, metric_synonyms JSONB,
    table_synonyms JSONB), a migration for it, a loader that `rewrite_query_node` calls
    per-tenant before instantiating `QueryRewriter(metric_synonyms=..., table_synonyms=...)`
    instead of the current no-argument `QueryRewriter()`.
- **FEAT-1**: Implement Proactive Question Suggestions (currently hardcoded `[]` at two
  call sites: `graph.py:514`, `rest.py:117`).
  - Spec: "Given a completed result with a chart_type and schema context, when
    rendering, then 2-3 contextually relevant follow-up questions are generated and
    returned in `proactive_questions`, non-empty for at least the common query shapes
    (single dimension breakdown, time-series, single-stat)."
  - Test: for a fixed result shape (e.g., revenue by customer_segment), assert
    `proactive_questions` is non-empty, each suggestion is a well-formed question string,
    and no suggestion duplicates the original query.
  - Implementation: your choice of (a) a dedicated LLM call (cheap model, short prompt,
    given the result shape + schema context) similar in shape to `ClaudeStoryteller`, or
    (b) a deterministic rule-based generator keyed off `chart_type`/`detected_dimensions`
    (cheaper, more predictable, easier to test — recommended for a first cut, with the
    LLM version as a fast-follow if quality isn't good enough). Populate
    `proactive_questions` at both call sites from the same shared function — do not
    duplicate the generation logic.

### Phase 2 — P1 concurrency & correctness (survive real concurrent pilot load)

- **PERF-1**: Fix the WebSocket pipeline event bus busy-poll.
  - Spec: "Given a pipeline event is published for a session, when a client is
    connected to `/ws/pipeline` for that session, then the event is delivered without
    a fixed polling delay, and the connection consumes no CPU while idle."
  - Test: assert `PipelineEventBus` is backed by `asyncio.Queue`; an integration test
    that publishes an event and asserts it's received by the WS test client without a
    `time.sleep`/polling wait baked into the test (i.e., an `await`-based receive).
  - Implementation: `app/services/events.py` → `asyncio.Queue` instead of `queue.Queue`;
    `app/api/ws_pipeline.py` → `await queue.get()` instead of the `get_nowait()` +
    `asyncio.sleep(0.01)` loop.
- **PERF-2**: Fix blocking Redis calls in `RedisSessionStore`.
  - Spec: "Given the session store is backed by Redis, when a session is read or
    written, then the call does not block the FastAPI event loop's other coroutines."
  - Test: integration test with two concurrent simulated requests — one that would
    normally be slow on Redis (mock a delay), one fast — assert the fast one is not
    blocked behind the slow one's Redis round-trip.
  - Implementation: switch `app/core/session.py`'s `RedisSessionStore` to
    `redis.asyncio.Redis`, `await` all client calls, update the `RedisClientProtocol`
    to an async protocol.
- **PROD-1** (from Part F): Wire real rate limiting into the live app.
  - Spec: "Given a user has made N requests to `/api/query` within a rolling window,
    when they exceed the configured limit, then subsequent requests are rejected with a
    429 and a `retry_after` hint, until the window resets."
  - Test: hammer `/api/query` past the limit in a test, assert 429 + retry-after; assert
    a different user is unaffected; assert the limit resets after the window.
  - Implementation: port `staging_lib/pipeline/rate_limiter.py`'s logic, but back it
    with Redis (not in-memory — the original code's own comment says this is required
    for multi-instance correctness) so it works correctly across multiple backend
    processes. Apply per-`user_id` at `/api/query` and `/ws/audio` connection time.
- **ARCH-2**: Wire `MetricRegistry` into the live SQL-generation prompt, or remove it.
  - Spec (if wiring in): "Given a certified metric definition exists for a term the user
    mentioned, when SQL is generated, then the certified formula is included in the
    prompt context and the generated SQL's aggregate expression matches the certified
    formula, not a guessed one."
  - Test: seed a metric definition with a specific, distinctive formula; assert it
    appears in the constructed prompt/schema context passed to `generate_sql`.
  - If removing instead: delete `app/rag/metric_registry.py`, `backend/data/metrics.yaml`,
    and correct the README's "semantic Metric Registry" claim. Pick wiring-in unless
    there's a reason not to — the PRD explicitly calls this "critical for preventing LLM
    metric hallucination."
- **ARCH-3**: Fix the RAG confidence scale mismatch.
  - Spec: "Given retrieval results from both the vector and BM25 branches, when
    computing `rag_score` for confidence scoring, then the score is derived from the
    normalized RRF fusion score, not the source-specific raw similarity value."
  - Test: construct a case where the top RRF-ranked result came from the BM25 branch
    with an out-of-[0,1]-range `ts_rank` value; assert `rag_score` is still within
    [0,1] and reflects the RRF fusion score.
  - Implementation: in `app/rag/pgvector.py`, compute `rag_score` from
    `scores[sorted_refs[0]]` (the fused RRF score), normalized appropriately, not
    `final_chunks[0].similarity`.
- **ARCH-4**: Resolve the dead `llm_self_confidence` term.
  - Choose one: (a) have `ClaudeAdapter.generate_sql()` request structured output
    including a self-reported confidence (e.g., via a tool-use schema or a trailing JSON
    block) and populate it, or (b) remove the `llm` weight from
    `compute_confidence`'s `DEFAULT_WEIGHTS` and document that confidence is currently
    a two-factor (RAG + validation) formula. Write the spec and test for whichever you
    choose; do not leave the current silent-collapse behavior undocumented either way.
- **MODEL-1**: Resolve the Sonnet→Haiku model deviation.
  - Not a pure code task: run `tests/golden_queries.yaml` (already exists) against both
    models, compare accuracy against the PRD's 85% first-attempt-accuracy target, and
    write a short ADR (`docs/adr/0001-sql-generation-model-choice.md`) documenting cost,
    latency, and accuracy numbers and the decision. If Haiku's accuracy is materially
    below target, switch back to Sonnet or a hybrid (Haiku first attempt, Sonnet on
    retry) and add a regression test pinning the model choice so it can't silently drift
    again.
- **SEC-3**: Add `system`/user prompt separation across all three Claude adapter methods
  (`generate_sql`, `generate_clarification`, `summarize`). Spec: "Given a call to any
  LLM adapter method, when the prompt is constructed, then static instructions are in
  the `system` parameter and untrusted content (schema, history, user input) is clearly
  delimited in the user turn." Test: assert `client.messages.create` is called with a
  non-empty `system` kwarg for all three methods.
- **SEC-4**: Add `SNOWFLAKE_DSN` presence check to `Settings.validate_startup()` when
  `WAREHOUSE_PROVIDER=snowflake`, matching the existing pattern for STT/TTS/LLM/RAG
  providers. Test: assert startup raises if `WAREHOUSE_PROVIDER=snowflake` and no DSN
  is configured (per-tenant DSNs from SEC-2 may supersede this — adjust the check
  accordingly once SEC-2 lands).
- **CODE-1**: Delete the dead `_complete_turn_background` method in `pipeline.py`.
- **ARCH-5**: Replace the textual duplication-detection heuristic with a real
  cardinality check, or explicitly document it as an accepted MVP simplification in
  `docs/prd.md` (pick one — don't leave it silently under-delivering against the PRD's
  own language).
- **TEST-3**: Add tests for `useVoxQuerySession.ts` (901 lines, zero direct tests today).
  Cover at minimum: session create/delete lifecycle, the 3-socket coordination
  (audio/pipeline/tts) using mocked WebSockets, and the clarification-resume path.
- **FEAT-2**: Implement clarification timeout/expiry.
  - Spec: "Given a clarification has been pending for longer than the configured
    timeout, when the user finally responds (or a new query is submitted), then the
    stale clarification is rejected with `clarification_expired`, not silently
    processed."
  - Test: create a pending clarification, advance time past the timeout, submit a
    resolution, assert `ApiError(ErrorCode.clarification_expired)` is raised.
  - Implementation: add `ClarificationResolutionType.timeout` to the enum (matching the
    DB's existing `CHECK` constraint), add a timeout field/check to `ClarificationState`,
    check it in `resolve_clarification()`.
- **ARCH-6**: Resolve the frontend/backend contract drift on `confidence_reasons` /
  `data_sources`.
  - Choose one: (a) implement these fields on the backend (`ResultTrust` gains
    `confidence_reasons: list[str]` populated from the actual ambiguity
    signals/validation outcome, and `data_sources: list[str]` populated from the
    generated SQL's referenced tables — you already have `formatDataSources()`'s regex
    logic as a reference for what tables look like, but do it properly server-side from
    the parsed SQL via `sqlglot`, not regex), or (b) remove the dead frontend code paths
    referencing fields that will never exist. Prefer (a) — it's a real trust-panel
    quality improvement and the frontend is already built for it.

### Phase 3 — P2 hygiene (batch these; low risk, do them together)

- SQL-1 (broaden `sql_policy.py` to accept `UNION`/`INTERSECT`/`EXCEPT` of all-`Select`
  leaves)
- CONF-1 (`threshold is not None` fix in `compute_confidence`)
- AUDIT-1 + AUDIT-2 (simplify `PostgresAuditStore` to a same-loop `asyncio.Task`, remove
  the busy-wait in `start()`)
- OBS-1 (add a lightweight secret-scrub regex to `telemetry._safe_dumps`)
- DOC-1 (fix the stale `DeepgramSttProvider` docstring and remove the now-dead
  `except NotImplementedError` handler in `ws_audio.py`)
- CODE-2 (replace `from app.main import app` deferred imports in route handlers with
  `Request`-based `request.app.state` access, repo-wide across `rest.py`,
  `telemetry.py`, all three `ws_*.py`)
- ROBUST-1 (make `migrations_runner.py`'s `MIGRATIONS_DIR` explicit/configurable, raise
  loudly if missing when a Postgres DSN is set)
- STRUCT-3, STRUCT-4 (rename `docs/dbschema/DB Info` and `DBScema_Sqls.docx`; document
  the `api/` route-file naming convention)
- PROD-2 (from Part F): add a scheduled job to re-run `scripts/sync_schema.py`
  periodically; log/report what changed on each run so drift is at least visible even
  before full automation is trusted.

### Phase 4 — Explicitly out of scope for this coding agent

Do not attempt these — they require infrastructure, human review, or external services
this agent doesn't have access to. Flag them back to the human as open items:

- Security penetration test / third-party audit
- Load/performance testing against the PRD's latency NFRs
- Secrets manager migration (KMS/Vault) — SEC-1's encryption key custody in particular
- Backup/DR policy and restore testing for Postgres
- SOC 2 / compliance track
- Accessibility audit tooling (axe-core) integration
- Admin console UI (F.3) — this is a real product surface, not a bug fix; scope as a
  separate project
- Feedback-loop closure (F.2) — turning `quality_flag=low` turns into a systematic
  review/improvement cycle is a process + tooling initiative, not a single PR

---

## Reporting format

For each item, produce output in this shape before moving to the next:

```
### <ITEM-ID>: <short title>

**Behavior spec:**
<Given/When/Then>

**Test (before implementation) — FAILING:**
<test code + failure output>

**Implementation:**
<diff or new file content>

**Test (after implementation) — PASSING:**
<test output>

**Full suite verification:**
<pass/fail counts, before vs after>

**Status:** done | blocked (reason)
```

At the end of each phase, run the full backend + frontend suites one more time and
report the totals, plus confirm CI (once Phase 0 lands it) is green on the branch.
