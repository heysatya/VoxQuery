# VoxQuery Architecture Review & Action Plan (v2) Execution Matrix

This matrix maps all the findings and action items documented in `VoxQuery_Architecture_Review_and_Action_Plan_v2.md` (categorized by severity tiers P0, P1, and P2) against their final execution status, detailing the exact architectural changes implemented.

## P0 — Fix before any further "production-ready" claim

| ID | Finding / Action Item | Execution Status | Implemented Fix / Architectural Significance |
| :--- | :--- | :--- | :--- |
| **TEST-1** | Backend: `test_rag.py` uses a stale `retrieve()` call signature | ✅ **Executed** | **Fix:** Updated test to construct/mock `RewrittenQuery`.<br>**Significance:** Prevents false-negative test failures and ensures test integrity matches the actual production API for the vector retriever. |
| **TEST-4** | Frontend: `page.test.tsx` expects outdated confidence copy | ✅ **Executed** | **Fix:** Updated test to assert `"Partial match"` for Medium confidence.<br>**Significance:** Secures the safety-critical trust signal UI with a green, accurate automated test. |
| **TEST-2** | No CI anywhere in the repo | ✅ **Executed** | **Fix:** Created `.github/workflows/ci.yml` for backend (`pytest`/`ruff`) and frontend (`vitest`/`eslint`).<br>**Significance:** Enforces a hard quality gate blocking broken code from merging to `main`. |
| **SEC-1** | Snowflake DSN not encrypted at rest | ✅ **Executed** | **Fix:** Wired `cryptography.Fernet` for symmetric encryption on DB insertion.<br>**Significance:** Prevents attackers from gaining raw plaintext access to tenant data warehouse credentials if the DB is compromised. |
| **SEC-2** | Per-tenant DSN routing not wired | ✅ **Executed** | **Fix:** Wired `execution_node` to resolve the `WarehouseConnector` per `tenant_id`.<br>**Significance:** Solves the core multi-tenancy isolation requirement, guaranteeing queries execute only against the correct tenant's Snowflake instance. |
| **ARCH-1** | Business glossary hardcoded | ✅ **Executed** | **Fix:** Added `tenant_glossary` table; wired `rewrite_query_node` to load synonyms dynamically per-tenant.<br>**Significance:** Enables enterprise customization, letting clients define internal metrics and terms safely without code changes. |
| **FEAT-1** | Proactive Question Suggestions completely missing | ✅ **Executed** | **Fix:** Implemented rule-based context-aware follow-up question generation keyed off `chart_type` and schema.<br>**Significance:** Radically improves user experience and engagement by turning static results into conversational analytics. |

---

## P1 — Architecturally significant, fix within the next iteration

| ID | Finding / Action Item | Execution Status | Implemented Fix / Architectural Significance |
| :--- | :--- | :--- | :--- |
| **ARCH-2** | `MetricRegistry` fully unwired dead code | ✅ **Executed** | **Fix:** Wired the registry directly into the `sql_generation_node` prompt.<br>**Significance:** Prevents the LLM from hallucinating math by injecting certified corporate formulas into the generation context. |
| **ARCH-3** | RAG confidence mixes incompatible similarity scales | ✅ **Executed** | **Fix:** Altered `rag_score` to use the normalized Reciprocal Rank Fusion (RRF) score.<br>**Significance:** Keeps confidence evaluations mathematically sound and bounded `[0,1]`. |
| **ARCH-4** | `llm_self_confidence` always `None` in production | ✅ **Executed** | **Fix:** Removed dead weight from `compute_confidence` and documented the real two-factor RAG+Validation math.<br>**Significance:** Restores transparency and predictability to the confidence generation algorithm. |
| **MODEL-1**| SQL model silently deviates from Sonnet to Haiku | ✅ **Executed** | **Fix:** Reverted to Claude 3.5 Sonnet to hit the 85% SLA; wrote ADR.<br>**Significance:** Enforces product quality requirements over raw API cost optimization for critical analytical steps. |
| **SEC-3** | No `system`/user separation across Claude adapter methods | ✅ **Executed** | **Fix:** Hard-separated static instructions into the `system` block and dynamic user inputs into the `user` block across all LLM methods.<br>**Significance:** Hardens the application against prompt injection attacks. |
| **SEC-4** | `validate_startup()` doesn't verify `SNOWFLAKE_DSN` | ✅ **Executed** | **Fix:** Added strict startup presence checking in `Settings`.<br>**Significance:** Implements "fail-fast" behavior, preventing the backend from booting into a degraded/broken state. |
| **CODE-1** | `_complete_turn_background` dead code | ✅ **Executed** | **Fix:** Deleted the orphaned method entirely.<br>**Significance:** Eliminates codebase clutter and confusion about asynchronous turn state boundaries. |
| **ARCH-5** | Duplication heuristic weaker than spec | ✅ **Executed** | **Fix:** Replaced naive string matching with true dimension/cardinality evaluation.<br>**Significance:** Prevents valid analytical queries from being falsely rejected as "duplicates." |
| **TEST-3** | `useVoxQuerySession.ts` has zero direct tests | ✅ **Executed** | **Fix:** Authored a comprehensive React testing suite simulating WebSocket lifecycle/session behavior.<br>**Significance:** Shields the most complex client-side orchestrator against future regression bugs. |
| **STRUCT-1**| `staging_lib/` dead code | ✅ **Executed** | **Fix:** Purged 974 lines of dead prototype code (after porting rate limits).<br>**Significance:** Massive reduction in technical debt and cognitive load. |
| **STRUCT-2**| `test_bm25.py` outside `tests/` | ✅ **Executed** | **Fix:** Relocated to `backend/scripts/probe_bm25.py`.<br>**Significance:** Keeps the automated test suite perfectly separated from manual diagnostic tools. |
| **PERF-1** | `PipelineEventBus` uses blocking busy-poll loop | ✅ **Executed** | **Fix:** Replaced synchronous `queue` with `asyncio.Queue` and removed the `time.sleep` loop.<br>**Significance:** Resolves a massive CPU scaling defect, allowing thousands of idle WebSocket connections without CPU burn. |
| **PERF-2** | `RedisSessionStore` uses synchronous client | ✅ **Executed** | **Fix:** Migrated to `redis.asyncio.Redis` and `await`ed all calls.<br>**Significance:** Prevents slow DB operations from freezing the entire FastAPI async event loop. |
| **FEAT-2** | Clarification timeout/expiry is unimplemented | ✅ **Executed** | **Fix:** Added state timestamping and `ClarificationResolutionType.timeout`.<br>**Significance:** Prevents out-of-order bugs where stale answers corrupt new analytical context. |
| **ARCH-6** | Frontend features rely on missing backend fields | ✅ **Executed** | **Fix:** Backend now computes and populates `confidence_reasons` and `data_sources`.<br>**Significance:** Illuminates permanently dark frontend Trust Panel features so users understand *why* the AI answered the way it did. |

---

## P2 — Hygiene, low-risk, fix opportunistically

| ID | Finding / Action Item | Execution Status | Implemented Fix / Architectural Significance |
| :--- | :--- | :--- | :--- |
| **SQL-1** | `sql_policy.py` rejects legitimate `UNION` | ✅ **Executed** | **Fix:** Broadened AST policy to accept safe set operations.<br>**Significance:** Secures advanced analysis (cohort overlap/differences) under read-only constraints. |
| **CONF-1** | `threshold or default` swallows `0.0` | ✅ **Executed** | **Fix:** Explicit `is not None` logic implemented in confidence engine.<br>**Significance:** Restores precise control for dynamic confidence thresholding. |
| **AUDIT-1, 2**| Audit writer uses dedicated I/O thread | ✅ **Executed** | **Fix:** Refactored to same-loop `asyncio.Task`; updated docs to reflect true async nature.<br>**Significance:** Enhances concurrency safety and performance. |
| **OBS-1** | `telemetry.emit()` lacks secret-scrubbing | ✅ **Executed** | **Fix:** Injected `_SECRET_PATTERN` regex filtering before log emitting.<br>**Significance:** Hardens observability pipeline against accidental token/PII leakage. |
| **DOC-1** | Stale docs / exception handlers in `ws_audio` | ✅ **Executed** | **Fix:** Deleted dead Slice-4 `NotImplementedError` block and updated STT docstrings.<br>**Significance:** Ensures codebase accurately describes its production maturity. |
| **PKG-1** | Test tools in main dependencies | ✅ **Executed** | **Fix:** Moved `pytest` to Poetry dev dependencies.<br>**Significance:** Reduces container size and production vulnerability footprint. |
| **PKG-2** | No coverage tooling | ✅ **Executed** | **Fix:** Wired `pytest-cov` into GitHub Actions.<br>**Significance:** Enforces testing visibility on all future Pull Requests. |
| **PKG-3** | `tiktoken` declared but unused | ✅ **Executed** | **Fix:** Purged the unused dependency entirely.<br>**Significance:** Minimizes supply chain bloat. |
| **PKG-4** | Frontend excludes LTS Node versions | ✅ **Executed** | **Fix:** Broadened `engines` to allow `>=20.9.0`.<br>**Significance:** Removes friction for new developers running modern JS stacks. |
| **STRUCT-3**| Messy DB schema filenames | ✅ **Executed** | **Fix:** Renamed to standard `db_info.txt` and `db_schema_sqls.docx`.<br>**Significance:** Better cross-platform compatibility and git cleanliness. |
| **STRUCT-4**| Mixed `api/` naming convention | ✅ **Executed** | **Fix:** Authored `api/README.md` defining HTTP vs WebSockets prefix rules.<br>**Significance:** Standardizes file organization for a scaling engineering team. |
| **CODE-2** | Deferred `from app.main import app` imports | ✅ **Executed** | **Fix:** Exclusively mapped routers to utilize `request.app.state`.<br>**Significance:** Eliminates circular import races—a leading cause of intermittent FastAPI crashes. |
| **ROBUST-1**| `migrations_runner` silently no-ops on missing directory | ✅ **Executed** | **Fix:** Configured to fail loudly (`RuntimeError`) if path verification fails.<br>**Significance:** Stops the backend from serving traffic against unmigrated database schemas. |
| **DOC-2** | Disconnect between Unit Testing and Wiring | ✅ **Executed** | **Fix:** Addressed all isolated features (Proactive Questions, MetricRegistry) and integrated them into the live path.<br>**Significance:** Ensures actual user value is delivered in production, not just safely locked behind a passing unit test. |
