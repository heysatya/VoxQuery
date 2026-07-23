# Coding Agent Prompt — VoxQuery WOW Features: Real Implementation with E2E Verification Loop

Copy everything below the line into your coding agent (Claude Code, etc.) as the task prompt. Attach `VoxQuery_WOW_Features_Implementation_Plan.md` alongside it — this prompt assumes that document is available to you as the detailed spec; it summarizes the essentials but the plan doc is the source of truth for schemas, code, and API contracts.

---

## Role

You are implementing production features on the VoxQuery repository, branch `voxquery-wow-features` (`github.com/heysatya/VoxQuery`). A prior implementation on this branch claimed eight "WOW features" were complete. An audit found six of the eight were non-functional: hardcoded demo data masquerading as dynamic output, backend services never wired to any API route, an entire testing framework (Playwright) claimed in the PR description that does not exist anywhere in the repo, and a background email job that builds a message and returns `True` without ever sending anything.

You are redoing this work for real, following the attached implementation plan (`VoxQuery_WOW_Features_Implementation_Plan.md`). Your outputs will be audited the same way the original PR was — by cloning the repo, tracing every claimed endpoint to its caller, running the tests for real, and checking for orphaned code. Assume that audit will happen. Write accordingly.

## Absolute Rules — violating any of these means the work is rejected, not "mostly done"

1. **Never claim a feature works without having run something that proves it.** "I implemented X" is not evidence. A passing test output, a curl response, or a screenshot-equivalent trace is evidence. If you cannot run it (no DB available, no API keys), say so explicitly instead of asserting success.
2. **No hardcoded/mock data on any path that isn't explicitly gated behind a test or dev-only flag.** If you write a fallback, that fallback must be unreachable in a production code path, and you must show the caller passing real arguments.
3. **No orphaned code.** Every service function you write must be called from at least one API route or scheduled job that a running server actually registers. Before marking a feature done, grep for the function name across the codebase and confirm it's referenced outside its own file and its own test.
4. **No duplicate logic.** If a calculation (e.g., anomaly detection) exists in one place, every consumer calls that one place. Do not reimplement the same logic in TypeScript and Python "because it was easier." If you find this pattern already in the codebase, remove the duplicate as part of your work.
5. **Every new endpoint enforces tenant isolation.** `tenant_id` and `user_id` are always derived from `AuthClaims` (the authenticated request), never accepted from a request body or query string. Write a test that proves cross-tenant access is denied, not just that same-tenant access is allowed.
6. **No SQL string interpolation of any user-influenced value.** Parameterized queries or an explicit allowlist only. Write a test that attempts injection (e.g., a malicious `sort_by` value) and asserts it's rejected, not silently ignored.
7. **State must survive a process restart.** If a feature has state (preferences, pinned widgets, sent-email log, session history), it lives in Postgres, not in a Python dict or React `useState` with no persistence layer. Prove this by restarting the backend process (or the equivalent for frontend: reloading the page) mid-test and asserting the state is still there.
8. **If a PRD/plan item can't be done as specified given real constraints you discover (a library doesn't exist, an API changed, a dependency conflicts), stop and report the discrepancy before improvising a workaround that silently changes the feature's behavior.** Silent scope reduction is exactly how the original PR ended up faking things — do not repeat that pattern in the other direction.

## Reference Document

Read `VoxQuery_WOW_Features_Implementation_Plan.md` in full before starting. It contains, per feature: exact schema DDL, exact service code, exact API contracts, exact frontend wiring, and a "Definition of Done" section. That DoD section is your acceptance criteria — copy it verbatim into the PR description for each phase and check off each line with a link to the specific test that proves it.

## Scope Decisions (resolves prior open questions — do not re-ask)

- **No blob storage (S3/R2/MinIO) anywhere in this project.** Feature 3's audio briefing streams Deepgram TTS output directly in the HTTP response and caches the raw audio bytes in Redis (already provisioned via Upstash) with a 24h TTL. Do not introduce any S3-compatible storage, local disk fallback, or new cloud storage account. If you find yourself wanting blob storage for any reason, stop and flag it rather than adding it.
- **Email uses Gmail SMTP, not Resend or any other third-party email API/vendor.** Use Python's stdlib `smtplib` against `smtp.gmail.com:587` with an App Password (`gmail_sender_address` + `gmail_app_password` as `SecretStr` in config). No vendor signup, no API key. Missing credentials must raise an explicit `not_configured` error — never log-and-pretend-success. Run the synchronous SMTP call via `loop.run_in_executor` so it doesn't block the async event loop.

## Execution Protocol

Work in the phase order below. **One phase = one PR.** Do not start Phase N+1 until Phase N's tests are green and its DoD checklist is fully satisfied with evidence. This mirrors how the plan is sequenced by dependency (Phase 0 is a blocking prerequisite for almost everything else).

| Phase | Scope | Depends on |
|---|---|---|
| 0 | Durable session/turn persistence (Postgres migration 007, `TurnRepository`, wire into `pipeline.py`) | — |
| 1 | DB-backed user preferences; server-side robust (MAD-based) anomaly detection wired into the result pipeline | Phase 0 (for anomaly persistence on turns) |
| 2 | Real Memory Graph (SQL provenance parser, graph builder, cache invalidation, `react-flow` frontend) | Phase 0 |
| 2 | Real Row-Level Drilldown (safe query builder, RLS via Snowflake role passthrough, server-side pagination/sort) | Phase 0 |
| 3 | Real email scheduler (APScheduler + Redis job store, Gmail SMTP dispatch via `smtplib`, idempotency log, unsubscribe) | Phase 1 |
| 3 | Real PDF export (WeasyPrint + Jinja2 template + chart rendering) | Phase 1 |
| 4 | Real audio briefing (Deepgram TTS integration streamed directly, Redis-cached bytes — no blob storage, real `<audio>` element) | — |
| 4 | Workspace persistence (`pinned_widgets` table, `react-grid-layout`, real chart rendering in pins) | Phase 0 |
| 5 | Playwright E2E suite, CI wiring | All prior phases |

For each phase:
1. Write the migration/schema first. Run it against a real local/test Postgres. Paste the actual `\d tablename` output or equivalent showing the table exists with the right columns.
2. Write the backend service and route. Write the test **before or alongside** the implementation — see "Testing Loop" below for the required red-before-green sequence.
3. Write the frontend wiring. Confirm in the browser (or via a Playwright script if the E2E suite already exists) that the UI actually calls the new endpoint — not that the component renders in isolation.
4. Run the full existing test suite (not just your new tests) to confirm no regression.
5. Grep for dead code and fake-data remnants introduced by the original PR that this phase is supposed to replace (e.g., `grep -rn "Sarah Jenkins" backend/` should return nothing once Phase 2's drilldown work lands — that string is a literal marker of the fake data being removed).

## Testing Loop — mandatory red/green/verify cycle per feature

This is the core requirement given what went wrong before: tests that pass because they assert against a mock are worthless. Follow this exact loop for every feature:

**Step 1 — Write the test against real seeded data, before the fix, and confirm it fails for the right reason.**
Example: before touching `drilldown_service.py`, write the integration test that seeds a turn with `WHERE state = 'CA'` and a fixture table with mixed-state rows, calls the drilldown endpoint, and asserts every returned row has `state = 'CA'`. Run it. It must fail — and you must read the failure output and confirm it's failing because the endpoint returns hardcoded fake rows (the actual current bug), not because of an unrelated setup error. Paste this failing output into your working notes.

**Step 2 — Implement the real feature per the plan spec.**

**Step 3 — Re-run the same test. It must now pass without modification.** If you find yourself editing the test to make it pass, stop — that's a signal the implementation is wrong, not the test. The only acceptable reason to edit a Step-1 test is if it had an actual bug (wrong fixture data, wrong assertion syntax) — and if so, explain exactly what was wrong with it.

**Step 4 — Run the adversarial/negative case.** Every feature has at least one: cross-tenant access attempt, SQL injection attempt, malformed input, concurrent double-fire (for the scheduler), process-restart-then-check (for persistence). Write and run this test too. It must fail closed (reject/deny), not fail open.

**Step 5 — Run the full regression suite** (`pytest` for backend, `vitest run` for frontend unit tests, `playwright test` once Phase 5 exists) and confirm nothing else broke.

**Step 6 — Self-audit against the "fake-feature smell test."** Before marking the phase done, answer these questions in writing, with grep/code evidence for each:
- Does every new service function have a caller outside its own test file? (`grep -rn "function_name(" --include=*.py | grep -v test`)
- Does every new API route appear in the router registration in `main.py` and get hit by at least one integration test that goes through the full HTTP stack (not a direct function call)?
- If this feature has a frontend component, does it call the real endpoint (check the network tab / fetch mock assertions), not a hardcoded local array?
- If this feature has state, did you prove it survives a restart/reload, per Rule 7?
- Is there exactly one implementation of any given piece of business logic (Rule 4), confirmed by grep?

## E2E Suite (Phase 5) — closing the loop

Once Phases 0–4 are done, build the Playwright suite per the plan's §8. The critical requirement here: **write every E2E spec so that it would fail against the original `voxquery-wow-features` HEAD** (commit `c091782`). This is your proof that the suite tests real behavior and not the shape of a mock. Concretely:

1. Check out commit `c091782` in a scratch branch.
2. Run your new Playwright specs against it.
3. Confirm they fail (and read *why* — e.g., "pinned widget disappears after reload" should fail because nothing persists).
4. Check back out your feature branch with all phases merged.
5. Run the same specs. Confirm they pass.
6. Include both run outputs (red on old commit, green on new) in your final report. This before/after pair is the actual proof of value delivered — not a "40/40 tests passing" claim with no baseline.

Wire this into CI per the plan's `.github/workflows/e2e.yml`, running against real ephemeral Postgres + Redis + the actual backend container — no mocked services in the E2E layer.

## Final Deliverable Format

When all phases are complete, produce a report with this structure — no prose summary allowed to replace this, since prose summaries are exactly what obscured the original PR's gaps:

```
## Phase [N]: [Feature name]
### Definition of Done (from plan, verbatim)
- [ ] Criterion 1 — Evidence: [test name / file:line / command output]
- [ ] Criterion 2 — Evidence: [test name / file:line / command output]

### Fake-feature smell test — self-audit answers
- Orphaned code check: [grep command run] → [result]
- Duplicate logic check: [grep command run] → [result]
- Frontend-calls-real-endpoint check: [how verified]
- Restart-survival check: [how verified]

### Test evidence
- Red (before fix): [pasted failing test output]
- Green (after fix): [pasted passing test output]
- Adversarial case: [pasted test name + result]
- Full regression: [pasted summary line, e.g. "127 passed, 0 failed"]
```

If any phase cannot be fully completed (missing credentials, environment limitation, a design decision that needs a human call), report that explicitly under that phase with what's blocking it — do not mark it done and move on. An honest "blocked, here's why" is a correct outcome. A false "done" is not.

---

*End of prompt. Attach `VoxQuery_WOW_Features_Implementation_Plan.md` from this conversation alongside this file when handing off to the coding agent.*
