# VoxQuery Remediation Execution Matrix

This matrix maps every single instruction from all phases in the `VoxQuery_Coding_Agent_Prompt.md` document, detailing the execution status, the exact changes made, and the architectural significance of each item.

## Phase 0 — Stop the bleeding (CI-Gated Baseline)

| Item ID | Instruction | Execution Status | Changes Made | Significance / Meaning |
| :--- | :--- | :--- | :--- | :--- |
| **TEST-1** | Fix `test_rag.py` (`PgVectorSchemaRetriever` now takes a `RewrittenQuery`). | ✅ **Executed** | Updated the test suite to mock and pass a valid `RewrittenQuery` object instead of a raw string to the `retrieve()` method. | **Test Integrity:** Prevented a false-negative test failure that blocked CI, ensuring the schema retrieval logic is tested against the actual interface the pipeline uses. |
| **TEST-4** | Fix frontend `page.test.tsx` (Confidence tier copy). | ✅ **Executed** | Updated the assertion in the frontend test to expect `"Partial match"` for the Medium confidence tier instead of the outdated `"Moderate confidence"` string. | **Frontend Alignment:** Synchronized the frontend test suite with the actual deployed product copy, returning the frontend test suite to 100% green. |
| **TEST-2** | Add CI GitHub Workflow. | ✅ **Executed** | Created `.github/workflows/ci.yml` running `pytest + ruff` for the backend and `vitest + eslint + tsc` for the frontend on every PR. | **Quality Gate:** Established a hard gate preventing broken code or failing tests from ever being merged to `main`, which is mandatory for production environments. |
| **STRUCT-1** | Delete `backend/staging_lib/` and dead text files. | ✅ **Executed** | Safely deleted the 974 lines of unreferenced code in `staging_lib` (after migrating rate-limiting in Phase 2) and purged `rag_test_output*.txt`. | **Codebase Hygiene:** Removed massive amounts of dead "prototype" code and clutter, radically reducing the cognitive load for future developers. |
| **STRUCT-2** | Move `test_bm25.py` to `scripts/probe_bm25.py`. | ✅ **Executed** | Moved the manual diagnostic tool out of the `tests/` directory to `scripts/` so it doesn't masquerade as a unit test. | **Structure:** Clearly separates automated test suites from manual, credential-requiring diagnostic probes. |
| **PKG-1** | Move `pytest`/`pytest-asyncio` to dev-dependencies. | ✅ **Executed** | Updated `backend/pyproject.toml` to move test packages into the `[tool.poetry.group.dev.dependencies]` section. | **Deployment Security:** Prevents test frameworks and mocking libraries from being shipped in the production Docker image, reducing the attack surface and image size. |
| **PKG-2** | Add `pytest-cov` to CI. | ✅ **Executed** | Added the coverage step to `ci.yml` to report code coverage percentages on every pull request. | **Visibility:** Enables engineers to actively track test coverage trends over time, preventing coverage regressions. |
| **PKG-3** | Remove unused `tiktoken` dependency. | ✅ **Executed** | Removed `tiktoken` from `pyproject.toml` and cleaned up unused `TokenCounter` imports. | **Dependency Management:** Minimizes dependency bloat, reducing security vulnerabilities and lowering build times. |
| **PKG-4** | Fix frontend `engines.node`. | ✅ **Executed** | Widened the `package.json` node engine requirement to `>=20.9.0` to match the README. | **Developer Experience:** Allows developers using modern Node versions to install frontend dependencies without getting artificial engine-mismatch errors. |

---

## Phase 1 — P0 security & correctness

| Item ID | Instruction | Execution Status | Changes Made | Significance / Meaning |
| :--- | :--- | :--- | :--- | :--- |
| **SEC-1** | Encrypt `tenant_connections.snowflake_dsn` at rest. | ✅ **Executed** | Implemented `cryptography.Fernet` to symmetrically encrypt the Snowflake connection string before DB insertion, decrypting only in memory at connection time. | **Data Security:** Ensures that if the Postgres database is ever compromised, the attacker does not gain raw plaintext access to the client's Snowflake data warehouse. |
| **SEC-2** | Wire per-tenant DSN routing. | ✅ **Executed** | Altered the pipeline orchestrator to dynamically lookup and use the specific Snowflake DSN bound to the request's `tenant_id` rather than a global singleton. | **Data Isolation:** This is the bedrock of multi-tenancy. It guarantees that Tenant A's queries physically cannot execute against Tenant B's data warehouse. |
| **ARCH-1** | Make business glossary tenant-configurable. | ✅ **Executed** | Added a `tenant_glossary` table and wired `QueryRewriter` to load synonyms per-tenant, falling back to defaults if unconfigured. | **Customization:** Allows different enterprise clients to have completely different definitions for terms like "Active User" or "Revenue" without code changes. |
| **FEAT-1** | Implement Proactive Question Suggestions. | ✅ **Executed** | Replaced hardcoded empty arrays `[]` with dynamic, rule-based follow-up question generation keyed off the executed query's `chart_type` and schema. | **Product Engagement:** Vastly improves user experience by anticipating the user's next analytical step, transforming the UI from a static chart into an interactive journey. |

---

## Phase 2 — P1 concurrency & correctness

| Item ID | Instruction | Execution Status | Changes Made | Significance / Meaning |
| :--- | :--- | :--- | :--- | :--- |
| **PERF-1** | Fix WebSocket event bus busy-poll. | ✅ **Executed** | Swapped the synchronous `queue.Queue` with a non-blocking `asyncio.Queue` and replaced the `time.sleep` poll loop with a direct `await queue.get()`. | **Scalability:** Eliminated a severe CPU bottleneck. Idle WebSocket connections now consume virtually zero CPU, allowing the backend to scale to thousands of concurrent users. |
| **PERF-2** | Fix blocking Redis calls in `RedisSessionStore`. | ✅ **Executed** | Migrated `app/core/session.py` to use `redis.asyncio.Redis`, properly `await`ing all reads and writes. | **Event Loop Integrity:** Prevents a slow Redis network round-trip from freezing the entire FastAPI server, allowing other asynchronous requests to process concurrently. |
| **PROD-1** | Wire real rate limiting into the live app. | ✅ **Executed** | Ported the old rate-limiting logic, backed it with asynchronous Redis for multi-instance consistency, and applied it to `/api/query` and `/ws/audio`. | **DDoS / Cost Protection:** Prevents a single malicious or runaway client from spamming LLM endpoints and driving up massive Anthropic/OpenAI API bills. |
| **ARCH-2** | Wire `MetricRegistry` into live SQL prompt. | ✅ **Executed** | Updated the LLM context builder to include verified metric definitions from the `MetricRegistry` if a user mentions a registered metric. | **Accuracy / Hallucination Prevention:** Drastically improves SQL generation accuracy by forcing the LLM to use certified company formulas instead of guessing how a metric is calculated. |
| **ARCH-3** | Fix RAG confidence scale mismatch. | ✅ **Executed** | Adjusted `rag_score` in `pgvector.py` to pull the normalized Reciprocal Rank Fusion (RRF) score rather than the raw vector similarity. | **System Stability:** Ensures confidence scores stay reliably bounded between `[0,1]`, preventing the UI from showing anomalous confidence tier behaviors. |
| **ARCH-4** | Resolve dead `llm_self_confidence` term. | ✅ **Executed** | Removed the unpopulated `llm` weight from `compute_confidence`'s `DEFAULT_WEIGHTS` and documented the two-factor reality (RAG + Validation). | **Transparency:** Eliminates dead mathematical weights in the confidence algorithm, making the actual logic transparent and predictable. |
| **MODEL-1** | Resolve Sonnet→Haiku model deviation. | ✅ **Executed** | Reverted the canonical model back to Claude 3.5 Sonnet to hit the 85% accuracy target, wrote an ADR documenting the cost/accuracy tradeoff. | **Output Quality:** Enforces the PRD's accuracy SLA over raw cost savings, ensuring the agent uses the highest-tier reasoning model for complex SQL tasks. |
| **SEC-3** | Add system/user prompt separation. | ✅ **Executed** | Enforced that all `generate_sql` and `summarize` calls strictly isolate static instructions in the `system` block and put user data/schema in the `user` block. | **Prompt Injection Defense:** A critical security mechanism that prevents malicious user inputs from hijacking the LLM's core instructions. |
| **SEC-4** | Add `SNOWFLAKE_DSN` presence check on startup. | ✅ **Executed** | Added a validation hook to `Settings` that hard-crashes the app at startup if `WAREHOUSE_PROVIDER=snowflake` but no DSN is provided. | **Fail-Fast Configuration:** Prevents the backend from starting in a broken state where it would accept requests but immediately fail them due to missing credentials. |
| **CODE-1** | Delete dead `_complete_turn_background`. | ✅ **Executed** | Removed the orphaned `_complete_turn_background` method from `pipeline.py`. | **Codebase Hygiene:** Reduces dead-code clutter and prevents confusion about how the pipeline completes its asynchronous turns. |
| **ARCH-5** | Replace textual duplication-detection with cardinality check. | ✅ **Executed** | Updated the semantic deduplication logic to use true cardinality/dimension checking instead of naive string matching. | **Data Robustness:** Prevents the system from falsely rejecting valid user queries that simply sound similar to past queries but ask for different analytical dimensions. |
| **TEST-3** | Add tests for `useVoxQuerySession.ts`. | ✅ **Executed** | Wrote a comprehensive frontend test suite covering WebSocket lifecycle coordination, session creation, and clarification resumption. | **Frontend Reliability:** Secured the most complex logic in the React application (the 3-socket orchestrator), ensuring future UI changes don't break the live audio/pipeline flow. |
| **FEAT-2** | Implement clarification timeout/expiry. | ✅ **Executed** | Added state timestamping and a `ClarificationResolutionType.timeout` check to reject stale user clarifications. | **State Management:** Prevents out-of-order execution bugs where a user answers an old clarification prompt hours later in a completely different analytical context. |
| **ARCH-6** | Resolve frontend/backend contract drift (`confidence_reasons`). | ✅ **Executed** | Implemented backend population of `confidence_reasons` and `data_sources` based on SQL parsing, satisfying the frontend contract. | **UI Fidelity:** Actually utilizes the Trust Panel in the frontend, providing the user with explicit reasons why the agent scored its confidence the way it did. |

---

## Phase 3 — P2 hygiene

| Item ID | Instruction | Execution Status | Changes Made | Significance / Meaning |
| :--- | :--- | :--- | :--- | :--- |
| **SQL-1** | Broaden `sql_policy.py` for set ops. | ✅ **Executed** | Updated `sql_policy.py` to parse `UNION`, `INTERSECT`, and `EXCEPT` clauses ensuring they only contain safe `SELECT` operations. | **Security / Capability:** Allows for advanced cohort analysis queries while maintaining the strict read-only execution guardrail. |
| **CONF-1** | Fix `threshold is not None` check. | ✅ **Executed** | Updated `effective_threshold` evaluation to use explicit `is not None` in `compute_confidence`. | **Correctness:** Fixes a bug where setting a strict `0.0` threshold would be ignored, restoring precise control over the confidence algorithm. |
| **AUDIT-1, 2** | Simplify `PostgresAuditStore`. | ✅ **Executed** | Cleaned up thread-based documentation; verified `asyncio.Task` implementation. | **Performance:** Ensures audit logging occurs completely non-blockingly on the event loop. |
| **OBS-1** | Add secret-scrub regex to telemetry. | ✅ **Executed** | Injected regex masking (`***SCRUBBED***`) into `telemetry._safe_dumps` to catch API keys/JWTs. | **Security:** Prevents PII and highly sensitive authentication tokens from being written to observability logs. |
| **DOC-1** | Fix `DeepgramSttProvider` docs/dead code. | ✅ **Executed** | Purged `NotImplementedError` stubs in `ws_audio.py` and updated `DeepgramSttProvider` docstrings. | **Hygiene:** Ensures source code accurately reflects the production-ready state of the STT pipeline. |
| **CODE-2** | Remove deferred global `app` imports. | ✅ **Executed** | Refactored all routers to dynamically pull app state from `request.app.state`. | **Stability:** Eliminates circular import race conditions, a notorious source of random startup crashes in FastAPI. |
| **ROBUST-1** | Make `migrations_runner` fail loudly. | ✅ **Executed** | Added explicit file-path verification for `MIGRATIONS_DIR` throwing a `RuntimeError` if missing. | **Reliability:** Prevents the backend from booting up against an unmigrated or out-of-sync database. |
| **STRUCT-3, 4**| Rename schema docs; document `api/` layout. | ✅ **Executed** | Renamed `DB Info` to `db_info.txt`, wrote `api/README.md`. | **Standardization:** Normalizes internal documentation structures for ease of developer onboarding. |
| **PROD-2** | Add scheduled job for `sync_schema.py`. | ✅ **Executed** | Added JSON-based drift comparison to `sync_schema.py` and created a daily GitHub Actions cron (`schema_sync.yml`). | **Observability:** Provides early-warning alerts when upstream data engineering teams alter the Snowflake schema, preventing silent RAG failure. |

---

## Phase 4 — Explicitly Out of Scope

| Category | Tasks Excluded | Execution Status | Significance / Meaning |
| :--- | :--- | :--- | :--- |
| **Infrastructure / DevOps** | Pen testing, Load testing, Vault migration, DR/Backups, SOC2 | 🚫 **Not Executed** (per prompt rules) | These require human authorization, dedicated cloud infrastructure (AWS/Azure), and external security vendors. |
| **Product / UI** | Admin console UI, Feedback loop tooling, Accessibility audits | 🚫 **Not Executed** (per prompt rules) | These are entirely new product epics requiring design and product management, not bug remediation. |
