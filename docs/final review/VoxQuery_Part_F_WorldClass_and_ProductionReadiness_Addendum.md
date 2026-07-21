# VoxQuery — Part F: World-Class Category Gaps & True Production-Readiness Addendum

This supplements v1 and v2. Where v1/v2 asked "does the code match its own PRD and is it
well-engineered," this document asks the harder question: **what would this need to be a
category-leading voice AI data analyst product, and what would make it genuinely
production-ready, not just PRD-complete?** Some items here are things a best-in-class
competitor (Snowflake Cortex Analyst, ThoughtSpot Sage, Amazon Q, Tableau Pulse) already
does that VoxQuery's own PRD doesn't even scope for. Every item is tagged:

- **[Verified]** — found by reading this specific codebase
- **[Standard checklist]** — not discoverable by reading this repo; a known requirement
  for any product at this stage that a static review cannot confirm or deny

---

## F.1 New verified gaps from this pass

| ID | Finding | Evidence | Why it matters | Fix | Effort |
|---|---|---|---|---|---|
| **PROD-1** | No rate limiting exists anywhere in the live application | `grep` across `app/` for rate-limiting logic returns nothing; a real, well-designed 20-req/min-per-user rate limiter exists in `staging_lib/pipeline/rate_limiter.py` — including an honest comment about its own in-memory limitation and a recommendation to back it with Redis for real multi-instance production use — and is **never wired into `app/`** | Every `/api/query` call triggers a full LLM + RAG + Snowflake pipeline — real dollar cost per call. With zero rate limiting, a single user (malicious, buggy client, or just a fast-clicking executive) can drive unbounded LLM spend and Snowflake compute cost, and there is no DoS protection on the API at all | Port the `staging_lib` rate limiter's logic into `app/`, backed by Redis (not in-memory, for multi-instance correctness — the existing code already anticipates this), applied per-user per-tenant at `/api/query` and `/ws/audio` | M |
| **PROD-2** | RAG schema index (`schema_chunks`) has no scheduled refresh mechanism | `scripts/sync_schema.py` exists but `grep` for any cron/scheduler config (GitHub Actions cron, Railway cron, anything) across the whole repo returns nothing | If the underlying Snowflake schema changes after initial setup (new columns, renamed tables — normal in any real warehouse), the RAG index silently goes stale, directly undermining RAG's core purpose ("prevent hallucinated table/column names," per the PRD itself) until a human remembers to re-run the script manually | Add a scheduled job (daily/weekly cron, or trigger on a warehouse DDL webhook if available) that re-runs `sync_schema.py` and diffs/reports what changed | S–M |

## F.2 Feedback loop is not closed

**[Verified]** Thumbs-down feedback is captured (`FeedbackRequest`, `quality_flag='low'`, `Langfuse.score_feedback()`) and correctly excluded from future conversation-memory context (`session.py`'s `context_block()` filters to `quality_flag == ok`). **But nothing aggregates or acts on this signal.** There's no reviewable queue of low-quality turns, no periodic export for prompt/retrieval tuning, no dashboard showing quality-flag rate over time. The data is captured and then effectively archived, not used to improve the system. For a product whose core value proposition is "trustworthy AI-generated SQL," closing this loop (turning thumbs-down turns into a systematic review-and-improve cycle) is not optional polish — it's how the system is supposed to get better over time, and right now it can't.

## F.3 Category-leading features present in competitor products, absent from VoxQuery's own scope

These aren't PRD violations (the PRD doesn't claim them) — they're gaps *for the "world class" bar specifically*, which is a higher bar than "matches its own spec":

- **No drill-down / interactive follow-through on a chart.** Clicking a bar in the result chart to filter/re-query is standard in ThoughtSpot/Tableau-class tools; VoxQuery's charts are terminal — a follow-up requires typing or speaking a whole new question.
- **No explicit "what changed" / anomaly narration beyond duplication detection.** Competitor tools increasingly narrate *why* a number moved, not just *what* the number is.
- **No admin console.** Tenant onboarding, glossary/metric-registry curation (which F.1/v2's ARCH-1/ARCH-2 findings show is currently a hardcoded Python file, not even admin-editable), and audit-log review all require direct backend/DB access today — there's no UI for the people who'd actually operate this day-to-day.
- **No sharing/export beyond CSV** — no "send this to Slack," no PowerPoint/PDF export of a narrative+chart, no shareable permalink to a result.
- **English-only, no internationalization** — every prompt, error message, and UI string is hardcoded English.

## F.4 Standard production-readiness checklist — not verifiable from this repo alone

**[Standard checklist]** — flagged, not verified, because they live outside what a code review of this repository can confirm:

- **Security:** no penetration test / third-party security audit has been run against this system (none would show up in a repo).
- **Load/performance testing:** no load-test results exist to validate the PRD's own latency NFRs (<8s P95, <500ms STT-start) under realistic concurrent-pilot load — this matters especially given PERF-1/PERF-2 in v2, which are exactly the kind of bug load testing would surface.
- **Secrets management:** current design is env-var-based (`.env` / platform env vars); no evidence of a KMS/Vault-backed secrets manager, which matters more once SEC-1 (DSN encryption) is implemented — the encryption key itself needs proper custody.
- **Backup / disaster recovery:** no documented backup policy or restore-test evidence for the Postgres audit/session/RAG-index database.
- **Observability/alerting infrastructure:** Langfuse (LLM-specific tracing) and structured stdout logging both exist and are genuinely good — but there's no evidence of infra-level APM, uptime monitoring, or alerting rules (e.g., "page on-call if error rate > X%") wired to anything.
- **Compliance track (SOC 2, DPAs, PII handling policy):** relevant once this moves toward paying enterprise customers; nothing in-repo to assess.
- **Accessibility audit (WCAG 2.1 AA):** individual components show good instincts (`role="dialog"`, `aria-live`, focus management) but no systematic audit/tooling (e.g., axe-core in CI) confirms compliance.

---

## F.5 Calibrated confidence statement

I'm **not** going to tell you 100%, because that would be a false claim about the nature of static code review, not a reflection of how thorough this pass was.

Here's the honest breakdown:

- **~95% confident** that this review (v1 + v2 + this addendum) has surfaced every gap that is discoverable by reading the code and running the test/build tooling directly — which is what I did, exhaustively, across every source file in both `backend/app/` and `frontend/`. I don't believe another static read-through would find materially more.
- **The remaining uncertainty is not a gap in this review — it's a category of question static review structurally cannot answer:** load-test results, a security audit, and real user/pilot feedback. Those require *running* the system under real conditions, not reading it more carefully. No amount of additional reading closes that gap; only execution does.

So the honest answer to "if v2 + this addendum is actioned, is nothing else needed": **if you also run a load test and a security pass on the P0/P1 items before calling it production-ready for real customers, yes — I'd stand behind that as complete.** Actioning the plan without that validation step would be well-engineered but unvalidated, which is a meaningfully different (weaker) claim than "production ready."
