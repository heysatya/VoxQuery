# VoxQuery Voice Subsystem — Gate 5/6/7 Architecture Plan (v3, Merged)

**Branch:** `voice-subsystem` · **Produced:** 2026-07-05 · **Mode:** Planning only — no files modified, created, or deleted in the repository during this pass.

**Provenance:** This is a merged, re-verified synthesis of two independently generated planning passes (v1: Claude/Sonnet-5-produced, v2: Sonnet-4.6-produced) plus a fresh, from-scratch re-verification of every factual claim performed immediately before this document was written. Where the two source plans disagreed, this document states which one was correct, why, and shows the exact command/output that settled it. Where both were right but one was sharper, this document adopts the sharper version and says so.

**A note on confidence:** Every factual claim about the repository's current state in this document (file contents, line numbers, hashes, git status) was re-checked seconds before being written and is traceable to a command shown below — treat those as verified. Architectural recommendations (which async pattern to use, which driver, where exactly to hook a call) remain engineering judgment calls, not provable facts, and are labeled as such throughout. No plan can be "guaranteed perfect" against future implementation surprises; this one is guaranteed to be internally consistent with the repository as it exists right now.

---

## 0. Verification Ledger

Every check below was executed immediately before writing this document, in this session, against the actual cloned repository (`git clone --branch voice-subsystem https://github.com/heysatya/VoxQuery.git`).

| # | Check | Command | Result |
|---|---|---|---|
Working-tree cleanliness must be re-verified by the implementation agent immediately before work begins. A clean fresh clone may differ from the user’s local working tree.

Required pre-work cleanup:
- Run `git status --short --branch`.
- If `frontend/next-env.d.ts` is modified only by Next dev mode, do not commit it.
- If `tmp-smoke-logs/` exists, do not commit it. Delete it or add it to `.gitignore` if appropriate.
- Do not stage or inspect secret-looking files.
- Treat the source roadmap/spec files as authoritative over any stale status claim in this planning document.

| 6 | Secret-looking files | `find . -not -path './.git/*' \( -iname '*.env*' -o -iname '*secret*' -o -iname '*credential*' -o -iname '*.pem' -o -iname '*.key' -o -iname 'id_rsa*' \)` | Only `./frontend/.env.example`, `./backend/.env.example` (placeholder templates) |
| 7 | HEAD commit | `git log -5 --oneline --decorate` / `git rev-parse HEAD` | `17812ecc04a48d2753c5a56850fc8e66f538331f` — `docs(gate4): add closure report and live smoke test evidence` |
| 8 | Migration directory contents | `find db -type f` | `db/demo_warehouse/001_ecommerce_schema.sql`, `db/migrations/001_voice_subsystem.sql` — exactly two files, no others |
| 9 | `001_voice_subsystem.sql` integrity | `sha256sum db/migrations/001_voice_subsystem.sql` | `0f4151fbf8239d3b1322c86b17dbc75d0b8a6bef22ca8a7f36f451b13c8e5167` — contains `tenants`, `users`, `conversations`, `user_snowflake_roles`, `tenant_connections`, `turns`, `clarifications`, matching engineering-spec.md §7.2 |
| 10 | `backend/migrations/` existence | `ls -la backend/migrations` | `No such file or directory` — **this path does not exist anywhere in the repo** |
| 11 | `session_id` column in `turns` DDL | `grep -n "session_id" db/migrations/001_voice_subsystem.sql` | No match — confirmed absent |
| 12 | `Settings.supabase_database_url` field | Full read of `backend/app/config.py` | Field does not exist yet |
| 13 | `.env.example` Postgres var name | `grep -n "SUPABASE" backend/.env.example` | Line 14: `SUPABASE_DATABASE_URL=` |
| 14 | `/health` handler current behavior | `grep -n -A6 'async def health' backend/app/main.py` | Hardcodes `"postgres": "not_configured"` (line 114) |
| 15 | Existing test assertion on `/health` | `grep -n -B3 "postgres" backend/tests/test_rest_flow.py` | Line 212: `assert response.json()["postgres"] == "not_configured"` |
| 16 | `TurnRecord` fields | Full read of `backend/app/models/contracts.py` | Has both `session_id: UUID` (in-memory model) and `full_result: ResultPayload \| None` (raw rows) — `session_id` is **not** in the `turns` DDL (check #11), confirming it is intentionally excluded from the durable audit table |
| 17 | Postgres/asyncpg dependency | `grep -A15 "^dependencies" backend/pyproject.toml` | No `asyncpg`, `psycopg`, or `sqlalchemy` present — must be added |
| 18 | `_complete_turn` hook point | `grep -n "sessions.append_turn\|ResultReadyEvent(\|turn.completed = True" backend/app/services/pipeline.py` | Lines 318, 322, 334 — confirmed unchanged from initial review |
| 19 | Escaped-clarification branch | `grep -n "resolution_type == ClarificationResolutionType.escaped\|self.turns.pop" backend/app/services/pipeline.py` | Lines 98, 100 — confirmed: turn is popped, never completed, never written |
| 20 | Feedback endpoint | Full read of `submit_feedback` in `backend/app/api/rest.py` | Confirmed exact structure: duplicate-guard first, then `mark_low_quality`, then `feedback_submitted = True`, `quality_flag = "low"` |
| 21 | `gate-4-closure.md` Gate 5 label | `grep -n "Gate 5" docs/voice-subsystem/gate-4-closure.md` | Line 35: *"...can safely progress to Gate 5 (Natural Language Processing & Agent Hand-off)"* — does not match `implementation-roadmap.md`'s Gate 5 definition (Supabase/Postgres Audit Writes) |
| 22 | `/health` `degraded` threshold spec wording | `grep -n -B2 -A2 "100ms\|degraded" docs/voice-subsystem/interface-contracts.md` | Line 361: *"`degraded` means the dependency is reachable but slow (> 100ms ping)"* — the 100ms figure is spec-defined, not invented |

SUPABASE-SPECIFIC VALIDATION:
Before implementing database code, consult the Supabase and Supabase Postgres best-practices skills (see [skills.sh/supabase/agent-skills/supabase](skills.sh/supabase/agent-skills/supabase) and [skills.sh/supabase/agent-skills/supabase-postgres-best-practices](skills.sh/supabase/agent-skills/supabase-postgres-best-practices)) only for targeted validation of:
- current Supabase connection-string expectations,
- migration discipline,
- connection pooling/lifecycle,
- transaction boundaries,
- RLS/security implications,
- secret handling,
- health-check behavior,
- and Postgres performance basics.

Do not use those skills to expand Gate 5 scope. VoxQuery’s implementation-roadmap.md and engineering-spec.md remain authoritative.
---

## 1. Repository State

| Property | Verified value |
|---|---|
| Branch | `voice-subsystem`, tracking `origin/voice-subsystem`, up to date |
| HEAD commit | `17812ec` — `docs(gate4): add closure report and live smoke test evidence` (full hash `17812ecc04a48d2753c5a56850fc8e66f538331f`) |
| Working tree | Must be re-verified immediately before implementation. Do not trust stale clean-tree claims. |
| `frontend/next-env.d.ts` | If modified only by Next dev mode, do not commit it. |
| `tmp-smoke-logs/` | If present, do not commit it; delete it or add it to `.gitignore` if appropriate. |
| Secret-looking files | None. Only `frontend/.env.example` and `backend/.env.example` exist, both placeholder templates, both intentionally tracked. Not opened beyond confirming they are templates. |
| Gate 4 closure doc | Exists at `docs/voice-subsystem/gate-4-closure.md`, 35 lines, contains live Deepgram smoke-test evidence (mic permission granted, WS opened, `stt.transcript.final` with `provider: "deepgram"`, real confidence float `0.8579915333333333`, clean `close_code: 1000`). |

**On the Gate 5 mislabeling in `gate-4-closure.md`:** the document's closing line names Gate 5 as *"Natural Language Processing & Agent Hand-off,"* which does not match `implementation-roadmap.md`'s canonical definition of Gate 5 (Supabase/Postgres Audit Writes) or this task's stated known-project-status. `implementation-roadmap.md` is treated as authoritative throughout this document. This is a one-line documentation inconsistency, not a scope question — see Open Question 4 (§8) for the recommended fix.

**Repository facts material to Gates 5–7**, confirmed by direct inspection (ledger #8–20), superseding assumptions either source plan may have made from spec-reading alone:

- **No Postgres/Supabase driver dependency exists** in `backend/pyproject.toml` (ledger #17). Must be added in Gate 5.
- **`db/migrations/001_voice_subsystem.sql` already exists and already matches Engineering Spec §7.2 field-for-field** (ledger #9) — `tenants`, `users`, `conversations`, `user_snowflake_roles`, `tenant_connections`, `turns`, `clarifications`, with correct columns, FKs, and CHECK constraints. It is not yet applied by any code path.
- **`backend/migrations/` does not exist anywhere in this repository** (ledger #10). Any plan or handoff prompt that references this path is factually wrong about the current repo and must be corrected before use — it would otherwise cause an implementation agent to create a second, conflicting migration tree.
- **The demo warehouse schema is already physically and semantically separate**: `db/demo_warehouse/001_ecommerce_schema.sql` carries an explicit header comment stating it is separate from "VoxQuery application metadata migrations." Gate 5 must preserve this separation, not invent it.
- **`.env.example` already names the env var `SUPABASE_DATABASE_URL`** (ledger #13), matching Engineering Spec §13. This resolves the env-var-naming decision directly from repo convention — no ambiguity here.
- **`/health` hardcodes `"postgres": "not_configured"`** (ledger #14), and an existing test (`test_rest_flow.py` line 212) asserts exactly this value (ledger #15). Gate 5 must replace the hardcoded string with a real check while keeping this value correct when Postgres is absent.
- **`TurnRecord` has a `session_id: UUID` field, but the `turns` Postgres table intentionally has no `session_id` column** (ledger #11, #16). This is not an oversight in the spec — `conversation_id` is the durable grouping key; `session_id` is explicitly ephemeral (cleared on browser refresh per Engineering Spec §5.3). Do not add `session_id` to the `turns` table; doing so would contradict the spec's explicit design and imply a durability the field doesn't have.
- **`TurnRecord.full_result: ResultPayload | None`** holds raw warehouse rows; **`TurnRecord.result_json: ResultShape | None`** is the shape-only counterpart. Gate 5 must persist only the latter to Postgres — this is the single most load-bearing rule in the entire plan (§3.12).
- **The turn-completion write point is `PipelineOrchestrator._complete_turn`** in `backend/app/services/pipeline.py`, specifically after line 322 (`self.sessions.append_turn(...)`) and around line 334 (`ResultReadyEvent` publish) — confirmed by direct line-number grep (ledger #18), not assumed.
- **The escaped-clarification path pops the turn and never calls `_complete_turn`** — confirmed at lines 98/100 (ledger #19). No audit row of any kind (turn or clarification) can legitimately exist for an escaped clarification, because `clarifications.turn_id` has a `NOT NULL REFERENCES turns(id)` constraint and no `turns` row is ever created for that path.
- **The feedback write point is `POST /api/feedback`** in `backend/app/api/rest.py`, confirmed via full read (ledger #20): duplicate-guard check happens first, then in-memory state updates. No Postgres call exists today.
- **`WarehouseConnector` (`app/warehouse/connector.py`) and `LlmAdapter` (`app/llm/adapter.py`)** are correctly implemented as single-method ABCs already. `services/providers.py`'s fakes (`FakeSchemaRetriever`, `FakeSqlGenerator`, `FakeWarehouseConnector`, `FakeChartSelector`, `FakeStoryteller`) do **not** inherit from these ABCs and are a separate, parallel set of stand-ins actually wired into `PipelineOrchestrator.__init__` today — a real, pre-existing inconsistency flagged in §5, not introduced by this plan.

---

## 2. Gate Dependency Map

### Why Postgres `turns` fields must support Langfuse trace/score correlation

Gate 6's acceptance criteria require exactly one Langfuse trace per turn and a score event on thumbs-down that references the correct trace. The join key across systems is `turn_id`: it is already `turns.id` in the verified DDL (ledger #9), and it is already threaded through every pipeline event and the REST layer (`ResultReadyEvent.turn_id`, `ClarificationRequestEvent.turn_id`, `FeedbackRequest.turn_id`, `GET /api/result/{turn_id}`). If Gate 5 persists `turns.id` as anything other than the exact same UUID used as `TurnRecord.turn_id` throughout the pipeline — it already is — Gate 6 has no reliable join key and would be forced into fuzzy time-based correlation. **Gate 5 must not change the meaning or generation of `turn_id`,** only persist it faithfully.

The same logic extends to `conversation_id`, `tenant_id`, and `user_id` — all three are already columns in the verified `turns` DDL. `session_id` is the one canonical pipeline field that should **not** appear as a `turns` column, and this needs to be stated as an explicit design decision rather than left to be rediscovered later: the Engineering Spec's `turns` table (§7.2) never lists it, `conversation_id` already serves as the durable grouping key across a multi-session conversation, and `session_id` is explicitly ephemeral by design (Engineering Spec §5.3: cleared on browser refresh). Gate 6 should still tag Langfuse traces with `session_id` as *metadata* (Langfuse traces are not subject to the same "frozen schema" constraint as a relational table, and having it available in Langfuse costs nothing) — but it must not be added to the Postgres `turns` table, because doing so would contradict the spec's explicit durability model and could mislead a future reader into treating a Postgres `turns.session_id` value as durable when the session itself is not.

### Why `clarifications` must preserve prompt, choice, and resolution type for later analysis

Engineering Spec §7.2 states the `clarifications` table "enables post-pilot analysis of which ambiguity types most frequently required clarification and which options were selected" — an activity that overlaps with Gate 6's Langfuse alert on >50% clarification rate (Engineering Spec §11), which needs a durable per-tenant denominator once Redis sessions have rotated out. If Gate 5 stores `resolution_type` as a free-form string instead of the canonical `option_selected | escaped | timeout` enum already defined in `contracts.py` (`ClarificationResolutionType`), or omits `prompt_sent` (the exact question text — `dominant_signal` alone doesn't tell you what was asked), the later analysis cannot distinguish "user picked an option" from "user rage-quit the clarification" from "user ignored it." Gate 5 must write all three fields exactly as specified, even though nothing yet consumes them.

### Why raw row exclusion must be enforced before Snowflake integration

Today, "raw rows" come from stubbed fake connectors returning three hardcoded arrays (verified: `services/providers.py`'s `FakeWarehouseConnector` and `warehouse/snowflake.py`'s `FakeSnowflakeConnector` both return static `[["Enterprise", 1240000], ...]`-style data). The security constraint ("Raw Snowflake result rows never cross LLM boundary," Engineering Spec §10; "Never store raw warehouse rows in Postgres audit tables," this task's invariants) costs nothing to satisfy today because there is no real data to leak. It costs everything once Gate 7 wires a real Snowflake connector returning real customer revenue. If Gate 5's audit-write code is built on an implicit assumption ("just persist `turn.result_json`, whatever that currently means") rather than an explicit, tested, defense-in-depth rule, that assumption is invisible until Gate 7 turns it into a live-data leak instead of a code-review comment. Gate 5 must therefore prove this boundary correct now, while the stakes are zero (§3.12 specifies exactly how).

### Why provider boundaries must be preserved before real RAG/SQL/Snowflake

`WarehouseConnector` and `LlmAdapter` already exist as ABCs with exactly one method each, per Engineering Spec §3's explicit InfoSec/multi-warehouse requirement that no provider-specific code leak outside `llm/claude.py`/`warehouse/snowflake.py`. Gate 5 does not touch these interfaces — it only adds an `AuditStore` interface following the same "abstract interface + no-op/fake implementation + real implementation" pattern already proven by `InMemorySessionStore`/`RedisSessionStore`. This matters for Gate 7 specifically because of a real, verified inconsistency: `PipelineOrchestrator.__init__` currently assigns `self.warehouse = FakeWarehouseConnector()` from `services/providers.py` — a class that does **not** inherit from the `WarehouseConnector` ABC — rather than `warehouse.snowflake.FakeSnowflakeConnector`, which does. There are two unrelated fake warehouse connectors in the codebase today, and only one is wired to the real interface. Gate 7 cannot safely swap in a real Snowflake connector until this is resolved (see §5). Flagging it now, while it's a code-organization note, is cheaper than discovering it mid-Gate-7 when it's blocking a live-data cutover.

### How `turn_id`, `conversation_id`, `tenant_id`, and `user_id` connect audit rows, Langfuse traces, feedback, and future warehouse execution

```
                 turn_id (UUID, generated once as TurnRecord.turn_id)
                     |
     +---------------+--------------------+----------------------+
     |               |                    |                      |
Redis session   Postgres turns.id   Langfuse trace id/tag   REST /api/feedback,
history entry   (Gate 5)            + score event (Gate 6)  /api/result/{turn_id}
(ephemeral,                                                 (already keyed by turn_id
survives TTL                                                 today, verified)
only, not Gate 5)

     conversation_id (Postgres FK, durable)      tenant_id / user_id (Postgres columns,
     groups turns -> one conversation row,       Langfuse tags, Redis key prefix
     drives auto-generated title on turn 1       session:{tenant_id}:{session_id},
                                                  future Snowflake role lookup)

     session_id (TurnRecord field, Langfuse
     metadata only -- deliberately NOT a
     turns column; see dependency-map note above)
```

`tenant_id` and `user_id` are the two fields that make cross-tenant leakage structurally impossible if enforced consistently end to end: Redis already scopes by `tenant_id` in its key (`session:{tenant_id}:{session_id}`, verified in `core/session.py`); Postgres will scope every row by `tenant_id`/`user_id` with FK constraints (already drafted in the verified migration); Gate 6 tags every Langfuse trace with both; Gate 7's Snowflake role passthrough resolves `snowflake_role` from `user_snowflake_roles` scoped by both. No new ID needs to be invented for Gates 5–7.

---

## 3. Gate 5 Architecture Plan

Scope discipline: Gate 5 only. No Langfuse, real RAG, real SQL generation, or Snowflake code in this gate.

### 3.1 Migration location and naming — VERIFIED PATH, CORRECTING A CROSS-PLAN ERROR

**Location: `db/migrations/`.** This is not a judgment call — it is the only migration directory that exists in this repository (ledger #8, #10). `backend/migrations/` **does not exist** and must not be used or created; doing so would produce a second, parallel, non-canonical migration tree alongside the real one, and any handoff prompt telling an agent to write to `backend/migrations/001_app_metadata.sql` is describing a repository that does not match this one.

`db/migrations/001_voice_subsystem.sql` already exists (sha256 `0f4151fb...`, ledger #9) and already contains complete, correct DDL for all seven tables — `tenants`, `users`, `conversations`, `user_snowflake_roles`, `tenant_connections`, `turns`, `clarifications` — matching Engineering Spec §7.2 field-for-field, including every column this task's canonical-fields list requires (`turn_id`→`id`, `conversation_id`, `tenant_id`, `user_id`, `input_modality`, `raw_transcript`, `deepgram_confidence_raw`, `generated_sql`, `result_json`, `chart_type`, `chart_rationale`, `confidence_tier`, `composite_score`, `clarification_triggered`, `quality_flag`, `source`, `latency_ms`, `created_at`). For reference, the verified DDL is reproduced here in full so the implementation agent does not need to re-derive it:

```sql
-- db/migrations/001_voice_subsystem.sql (VERIFIED EXISTING CONTENT — sha256 0f4151fb...)
CREATE TABLE IF NOT EXISTS tenants (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  email TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK (role IN ('viewer', 'admin')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversations (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES users(id),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  title TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_snowflake_roles (
  user_id UUID PRIMARY KEY REFERENCES users(id),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  snowflake_role TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tenant_connections (
  tenant_id UUID PRIMARY KEY REFERENCES tenants(id),
  snowflake_dsn TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS turns (
  id UUID PRIMARY KEY,
  conversation_id UUID NOT NULL REFERENCES conversations(id),
  user_id UUID NOT NULL REFERENCES users(id),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  user_input TEXT NOT NULL,
  raw_transcript TEXT,
  deepgram_confidence_raw DOUBLE PRECISION,
  generated_sql TEXT NOT NULL,
  result_json JSONB NOT NULL,
  chart_type TEXT NOT NULL,
  chart_rationale TEXT NOT NULL,
  confidence_tier TEXT NOT NULL,
  composite_score DOUBLE PRECISION NOT NULL,
  clarification_triggered BOOLEAN NOT NULL DEFAULT false,
  quality_flag TEXT NOT NULL DEFAULT 'ok' CHECK (quality_flag IN ('ok', 'low')),
  source TEXT NOT NULL DEFAULT 'user' CHECK (source IN ('user', 'scheduled')),
  input_modality TEXT NOT NULL CHECK (input_modality IN ('voice', 'text')),
  latency_ms INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clarifications (
  id UUID PRIMARY KEY,
  turn_id UUID NOT NULL REFERENCES turns(id),
  prompt_sent TEXT NOT NULL,
  user_choice TEXT,
  resolution_type TEXT NOT NULL CHECK (resolution_type IN ('option_selected', 'escaped', 'timeout')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
The migration runner should bootstrap its own `schema_migrations` table before scanning migrations:

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
Scan `db/migrations/*.sql`, apply migrations not already recorded, and mark each successful migration as applied., and must never touch `db/demo_warehouse/`. 

### 3.2 App metadata tables to create

None beyond what 001_voice_subsystem.sql already defines. Gate 5 should not add a bookkeeping migration solely to create schema_migrations; bootstrap that table inside the migration runner. db/migrations/001_voice_subsystem.sql is the canonical app metadata schema and should remain unchanged unless implementation discovers a concrete mismatch against engineering-spec.md.

Tenant, user, user Snowflake role, and conversation rows have no dedicated provisioning flow today. The recommended default is lazy upsert inside the completed-turn audit transaction, using AuditIdentity plus TurnRecord. This transaction must upsert tenants, users, user_snowflake_roles, and conversations before inserting turns.

### 3.3 Environment variable

Use **`SUPABASE_DATABASE_URL`** — confirmed as the existing convention at `backend/.env.example` line 14 (ledger #13) and matching Engineering Spec §13. Add to `Settings` in `backend/app/config.py`:

```python
supabase_database_url: str | None = Field(default=None, alias="SUPABASE_DATABASE_URL")
```

No `validate_startup()` hard-require rule analogous to Redis's (`SESSION_STORE=redis` requires `UPSTASH_REDIS_URL`) should be added — Gate 5's acceptance criteria imply audit writes may be absent (no-op) rather than mandatory. If a later gate wants to make Postgres mandatory in production, that is an explicit separate decision (see Open Question 1, §8).

### 3.4 Audit store design — no-op / real split

Mirror the existing `InMemorySessionStore`/`RedisSessionStore` split (`core/session.py`) and the `WarehouseConnector` ABC exactly. Recommended module layout:

```
app/audit/store.py       # AuditStore ABC/Protocol + build_audit_store(settings) factory
app/audit/noop.py        # NoopAuditStore — every method a safe no-op
app/audit/postgres.py    # PostgresAuditStore — real asyncpg pool
```

(A single `app/services/audit.py` module containing all three is equally acceptable if the implementing agent prefers fewer files — this is a naming/organization choice, not an architectural one.)

```python
class AuditStore(Protocol):
    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def health_status(self) -> str: ...

    def record_turn(
        self,
        *,
        turn: TurnRecord,
        identity: AuditIdentity,
        clarification: AuditClarification | None = None,
    ) -> None: ...

    def update_quality_flag(self, turn_id: UUID, flag: str) -> None: ...

@dataclass(frozen=True)
class AuditIdentity:
    user_id: UUID
    tenant_id: UUID
    email: str
    role: str
    snowflake_role: str
    tenant_name: str | None = None


@dataclass(frozen=True)
class AuditClarification:
    prompt_sent: str
    user_choice: str | None
    resolution_type: Literal["option_selected", "timeout"]
```
`record_turn` and `update_quality_flag` are synchronous enqueue methods, not async database calls. They must return immediately, never raise, and must not use `asyncio.create_task` from the per-turn pipeline loop.

Reason: the current pipeline runs background work through `asyncio.run(...)` inside short-lived daemon threads. Creating loose tasks inside that event loop can cancel audit writes when the coroutine exits. Also, an `asyncpg` pool cannot safely be shared across unrelated event loops.

The real Postgres implementation must own a process-lifetime audit worker/dispatcher. The worker owns the database connection pool and executes queued audit jobs. The pipeline and REST routes only enqueue jobs.

`AuditIdentity` is required because `TurnRecord` does not contain `email`, `role`, or `snowflake_role`, but the durable `users` and `user_snowflake_roles` rows need those values. The implementation may pass this object through pipeline methods or store it in a private dict keyed by `turn_id`; do not invent placeholder email/role values when real `AuthClaims` already has them.

For `tenant_name`, use a deterministic fallback such as `tenant-{tenant_id}` until a real tenant provisioning flow exists.

`NoopAuditStore` selected whenever `settings.supabase_database_url` is `None` — no separate `AUDIT_STORE=memory|postgres` toggle is needed, unlike `SESSION_STORE`, which has two real user-facing backends. Audit writes have exactly one real backend and one absence-of-backend state.

`build_audit_store(settings) -> AuditStore`, called once in `main.py`:

```python
app.state.audit = build_audit_store(settings=settings)
```

### 3.5 Postgres audit store behavior when configured

- **Driver: `asyncpg`** (recommended default over `psycopg[async]`) — natively async, no synchronous fallback to reason about, the most common Supabase+FastAPI pairing, and the same driver Gate 7 will want for pgvector queries (Engineering Spec §3, `pgvector` listed as the vector store). `psycopg[binary]` async mode is an acceptable alternative only if the implementing agent has an existing reason to prefer it.
- Connection pool created at `app.state.audit` construction time (small pool, e.g. min=1/max=4 — one pilot tenant does not need more), closed on FastAPI shutdown.
- `record_turn` is one transactional audit job, not one SQL statement.

In one transaction, it must:
1. Upsert `tenants`.
2. Upsert `users`.
3. Upsert `user_snowflake_roles`.
4. Upsert `conversations`.
5. Insert the `turns` row.
6. If clarification data is present, insert the `clarifications` row after the turn insert in the same transaction.

`tenant_connections` is not written in Gate 5 because no Snowflake DSN provisioning flow exists yet.

Every database operation must be parameterized. No DSN, SQL credentials, access tokens, or secret values may be logged.

- **All three methods must never raise.** Catch every exception, log via `app.services.telemetry.emit(..., tier=1)` (tier 1 = "trust" — an audit write failure is a data-completeness incident), and return normally. This matches `services/telemetry.py`'s own documented contract ("This function never raises... the exception is silently swallowed").
- `health_status()`: run a lightweight query (`SELECT 1` / `fetchval`) with a **short timeout**. Return `"ok"` on success, `"degraded"` on any exception or on a response slower than the spec's own stated threshold. Interface Contracts §3.6 explicitly defines `degraded` as "reachable but slow (> 100ms ping)" (ledger #22) — this number is not invented for this plan, it is the spec's own figure, and the same threshold `RedisSessionStore`-equivalent logic should use for consistency across both dependencies.

### 3.6 Health endpoint behavior

Because the Postgres implementation uses an async database driver and/or a dedicated audit worker, app startup/shutdown must be explicit.

Requirements:
- Initialize the audit store during FastAPI lifespan/startup.
- Close the audit store during shutdown.
- `/health` must call/await `app.state.audit.health_status()`.
- Noop store returns `"not_configured"`.
- Postgres store returns `"ok"` only when a lightweight ping succeeds within 100ms.
- It returns `"degraded"` on timeout, worker unavailable, pool unavailable, or database exception.
- `/health` still returns HTTP 200.

### 3.7 Async/non-blocking write strategy — DECISIVE CHOICE

`PipelineOrchestrator` currently runs background work through `asyncio.run(...)` inside short-lived daemon threads. Therefore Gate 5 must not create loose audit tasks inside that per-turn event loop.

Use synchronous enqueue calls only:

```python
self.audit.record_turn(turn=turn, identity=identity, clarification=clarification)
```
For feedback only:
```python
audit.update_quality_flag(request.turn_id, "low")
```
These calls enqueue work only. They must not perform network I/O inline, must return immediately, must never raise, and must not use asyncio.create_task from the pipeline thread.
The real Postgres implementation must own a process-lifetime audit worker/dispatcher. That worker owns the async database pool and executes queued jobs.

### 3.8 How completed turns are persisted

Hook point: `PipelineOrchestrator._complete_turn`, immediately after the existing `self.sessions.append_turn(...)` call and before/around the `ResultReadyEvent` publish:

```python
self.sessions.append_turn(session, turn_id=turn.turn_id, ...)  
self.audit.record_turn(turn=turn, identity=identity, clarification=clarification)
await self.events.publish(session.session_id, ResultReadyEvent(...))  
```
Do not update quality_flag here. Feedback updates belong only in POST /api/feedback.
The escaped-clarification branch pops the turn and never reaches _complete_turn; Gate 5 must not add any audit call to that branch.

### 3.9 How clarification option selection / timeout / escape are persisted

Do not write clarifications as independent jobs. A clarification row has an FK to `turns(id)`, so it must be inserted only as part of the completed-turn audit transaction.

For option-selected:
- Capture `state.question`, `selection`, and `resolution_type="option_selected"` before clearing `session.clarification_state`.
- Pass this as `AuditClarification` into `_complete_turn_background` / `_complete_turn`.

For timeout:
- Capture `state.question`, `user_choice=None`, and `resolution_type="timeout"` before clearing the pending state.
- Pass this as `AuditClarification` into `_complete_turn`.

For escape:
- Write no turn row.
- Write no clarification row.
- Keep the current behavior: pipeline halts and the turn is popped.

### 3.10 How feedback updates `quality_flag`

Hook point: `POST /api/feedback` after the existing duplicate guard and after `turn.quality_flag = "low"`.

```python
self.audit.update_quality_flag(request.turn_id, "low")
```
Use a new get_audit() FastAPI dependency mirroring get_sessions() / get_pipeline(). Do not call record_turn from feedback. Do not change the existing feedback_duplicate 409 guard.

### 3.11 The raw-row exclusion rule — the single most important invariant in Gate 5

**Rule:** the audit store must read only `turn.result_json` (`ResultShape`: `columns`, `chart_type`, `row_count`, `aggregate_summary`) and must never read, serialize, or reference `turn.full_result` (`ResultPayload`, which carries the actual `rows`) anywhere in the audit module.

Enforce this with **two independent layers**, not one:

1. **Structural (primary):** build the INSERT's parameters via an explicit, named, column-by-column mapping — never `turn.model_dump()` passed through wholesale, which would silently start including `full_result` if `TurnRecord` grows more raw-data-bearing fields later. This is the enforcement that actually matters; it is correct by construction, not by runtime luck.
2. **Runtime guard (defense in depth):** immediately before executing the INSERT, assert the serialized payload does not contain a `rows` key:
   ```python
   result_json_value = turn.result_json.model_dump(mode="json") if turn.result_json else None
   if result_json_value is not None and "rows" in result_json_value:
       raise ValueError("INVARIANT VIOLATION: raw rows must not reach the audit store")
   ```
   **Use an explicit `if/raise`, not a bare `assert`.** A bare `assert` is stripped entirely when Python runs with the `-O` optimization flag (`python -O`, or `PYTHONOPTIMIZE=1`), which some production deployment configurations set — silently disabling this exact safety check in the one environment where it matters most. An explicit `if/raise` has no such failure mode and costs nothing extra. Because `record_turn` must also never raise into its caller (3.5), catch this specific `ValueError` at the outer boundary of `record_turn`, log it at the highest telemetry tier as a trust-invariant violation, and skip the write rather than crashing the pipeline — a caught-and-logged invariant violation on a stubbed turn is a bug to fix immediately; it must never become a production outage.

Test this with a sentinel value (§3.12) so the guard's presence is provable, not just plausible.

### 3.12 Test strategy

- `backend/tests/test_audit_noop.py` — `NoopAuditStore` methods return immediately, never raise, enqueue no external work, and `health_status()` returns `"not_configured"`.
- `backend/tests/test_audit_postgres.py` — `PostgresAuditStore` tested with fakes/mocks only, never live Supabase credentials. Required cases:
  - `record_turn` enqueues exactly one completed-turn audit job.
  - Worker transaction upserts tenant, user, user_snowflake_role, conversation, then inserts turn, then optional clarification.
  - `update_quality_flag` enqueues exactly one quality update job.
  - Sentinel test proves `turn.full_result` and any `rows` key are never persisted.
  - Queue-full, worker-failure, and database-failure cases log tier-1 telemetry and never break caller flow.
  - `health_status()` returns `"ok"` / `"degraded"` correctly.
- `backend/tests/test_rest_flow.py` — keep `postgres: "not_configured"` passing with `SUPABASE_DATABASE_URL` unset; add a test that successful `POST /api/feedback` enqueues `update_quality_flag` exactly once.
- `backend/tests/test_pipeline_gate5.py` — assert `record_turn` is enqueued exactly once per completed turn; option-selected and timeout pass `AuditClarification`; escape enqueues no turn and no clarification.
- No unit test may require live Supabase credentials.

### 3.13 Gate 5 closure evidence required

Following the shape of `gate-4-closure.md` (verified: status/date/commit-hash/executive-summary/evidence/verification-highlights/conclusion):

- `pytest` passes fully, including all new audit tests, with **zero** live Supabase credentials present — state this explicitly (e.g. "`SUPABASE_DATABASE_URL` unset during this test run").
- The exact migration file(s) applied and their filenames (`001_voice_subsystem.sql` unchanged, or note any deviation and why).
- **A real Supabase smoke test is optional.** If run, show captured evidence in the same style as Gate 4's captured JSON telemetry lines (e.g. an `audit.turn.write` event with `outcome: "ok"`, latency, and no DSN anywhere in the log line). If not run, the closure doc must **explicitly say so** ("Real Supabase smoke: not performed — no credentials available in this environment") rather than omit the section.
- Explicit confirmation (by the sentinel test in 3.12, cited by name) that `record_turn` never persists `turn.full_result` / any `rows` key.
- Explicit confirmation that `/health`'s `postgres` field behaves as `not_configured` / `ok` / `degraded` correctly, with `degraded` tested via a mocked pool that raises or delays past 100ms.

---

## 4. Gate 6 Architecture Preview

Planning preview only. No Langfuse code, dependency, or wiring during Gate 5.

### Correlation to canonical IDs

Every Langfuse root trace should carry `turn_id` as its own trace identifier (Langfuse supports a custom `id` on trace creation as of common SDK versions — confirm the exact current SDK API at Gate 6 implementation time rather than assuming, since this plan predates that implementation and SDK APIs change). Setting `trace.id = str(turn_id)` means a Postgres `turns` row and its Langfuse trace share the same UUID, so the two systems can be joined without a separate mapping table. Tag/metadata fields on the trace should include `session_id`, `conversation_id`, `tenant_id`, `user_id`, and `input_modality` — all already available on `TurnRecord` at the moment a turn starts. As noted in §2, `session_id` belongs in Langfuse metadata even though it is deliberately excluded from the `turns` table — Langfuse traces are not subject to the same frozen-schema constraint as a relational table, so there is no cost to including it there.

### Where root trace creation should happen

At the start of `PipelineOrchestrator._run_turn_background` (immediately after its existing `await asyncio.sleep(0.05)`) or in `submit_query` right after the `TurnRecord` is constructed — either is acceptable; the requirement is only that it happen before any RAG/SQL/confidence work begins, so every subsequent span attaches to an already-open trace rather than requiring a two-phase buffer-then-create approach. The trace should be flushed once `_complete_turn` finishes publishing `ResultReadyEvent`.

### Where required spans should be emitted in the current pipeline

Mapped to verified code locations, not hypothetical modules:

| Required span | Current code anchor (verified) |
|---|---|
| `stt_capture` | `app/api/ws_audio.py` (Gate 4's Deepgram relay) and/or the point in `submit_query` where `request.raw_transcript`/`request.stt_confidence` populate the new `TurnRecord`. Inputs/outputs per Engineering Spec §11 are mostly already present as fields; `edit_distance_ratio` is not currently computed anywhere and needs a small new calculation (e.g. `difflib`) comparing `raw_transcript` to `submitted_text` — a Gate 6 addition, not Gate 5's job, but Gate 5 must ensure `raw_transcript` is durably persisted (it already is, via the verified `turns.raw_transcript` column). |
| `memory_retrieval` | `core/session.py`'s `context_block()` method — already computes `truncated`, `turns_dropped`, `token_count`. The implementing agent should confirm/introduce the exact call site inside `pipeline.py` as its own explicit step at Gate 6 time. |
| `history_injection` | Wherever `SessionContextBlock` is actually passed into the (currently fake) SQL generator — today `FakeSqlGenerator.generate` does not consume session context at all. This span cannot carry real `total_prompt_tokens` until Gate 7 wires a real LLM adapter that receives the context block; Gate 6 can still emit a stub-accurate span using the token count `core/session.py` already computes. |
| `ambiguity_detection` | `core/ambiguity.py`'s `detect_ambiguity()`, called from `pipeline.py`'s `_run_until_confidence_or_result` (verified around line 226). Already returns `signals_detected`, `signals_suppressed`, `dominant_signal` as `AmbiguityDetectionResult` — a near-direct mapping. |
| `confidence_computation` | `core/confidence.py`'s `compute_confidence()`, called from the same method (verified around line 232). Already returns `composite_score`, `confidence_tier`, `clarification_triggered`, `formula_weights` as `ConfidenceResult` — matches the required span shape almost exactly. |

### How `stt_capture` should connect to Gate 4 telemetry and `raw_transcript` / `deepgram_confidence_raw`

Gate 4 already emits structured telemetry (`stt.transcript.final` with `provider`, `confidence`, `latency_ms`, verified in `gate-4-closure.md`'s captured evidence) via `app.services.telemetry.emit()`. Gate 6 should not replace this stream — it is a separate, already-working, orthogonal observability channel (stdout JSON lines). The `stt_capture` Langfuse span is a *pipeline-trace-scoped* view of the same underlying data, populated by reading the already-populated `TurnRecord.raw_transcript`/`TurnRecord.deepgram_confidence_raw` fields, not by re-deriving them from Deepgram a second time.

### How feedback should emit a score event

At the same `POST /api/feedback` call site where Gate 5 adds `update_quality_flag` (§3.10), Gate 6 adds a Langfuse score-API call attaching to the trace identified by `turn_id`, per Engineering Spec §11's shape:

```python
langfuse.score(
    trace_id=str(turn_id),
    name="user_feedback",
    value=-1,
    metadata={
        "turn_id": str(turn_id),
        "confidence_score": turn.composite_score,
        "confidence_tier": turn.confidence_tier,
        "clarification_triggered": turn.clarification_triggered,
        "option_selected": ...,  # from Gate 5's clarifications row or in-memory resolved_entities
    },
)
```

`composite_score`/`confidence_tier`/`clarification_triggered` are already on `TurnRecord`, so no Postgres re-read is needed at score-event time — the in-memory `TurnRecord` is sufficient. `option_selected` requires a lookup against the resolved entity or the Gate 5 `clarifications` row for that turn.

### How Langfuse failures remain non-blocking

Same pattern as Gate 5's `AuditStore` (§3.5/3.11): wrap every Langfuse SDK call so it never raises into the pipeline or the feedback endpoint. On exception, emit a structured log event (e.g. `langfuse.error`) at telemetry tier 2 and continue. This mirrors `services/telemetry.py`'s own "never raises" contract — do not assume the Langfuse SDK's internal batching/flush behavior is sufficient on its own; wrap defensively regardless.

### Gate 5 fields needed to avoid Gate 6 rework

All required correlation and calibration fields — `turn_id`, `conversation_id`, `tenant_id`, `user_id`, `input_modality`, `raw_transcript`, `deepgram_confidence_raw`, `confidence_tier`, `composite_score`, `clarification_triggered`, `latency_ms` — are already columns in the verified `turns` DDL and will already be persisted by Gate 5's `record_turn`. No additional Gate 5 schema work is needed to support Gate 6, provided Gate 5 does not drop or rename any of them.

---

## 5. Gate 7 Architecture Preview

Planning preview only. No RAG, SQL generation, or Snowflake implementation during Gate 5.

### Current stub/provider interfaces that should be replaced or extended

A real, verified inconsistency exists today and should be resolved as an explicit, isolated pre-Gate-7 cleanup step (not bundled into either Gate 5 or Gate 7's actual deliverable):

- `services/providers.py`'s `FakeSchemaRetriever`, `FakeSqlGenerator`, `FakeWarehouseConnector`, `FakeChartSelector`, `FakeStoryteller` are plain classes with **no shared abstract base**, unlike `WarehouseConnector` (`warehouse/connector.py`) and `LlmAdapter` (`llm/adapter.py`), which already exist as proper single-method ABCs. `PipelineOrchestrator.__init__` currently assigns `self.warehouse = FakeWarehouseConnector()` from `providers.py` — **not** `warehouse.snowflake.FakeSnowflakeConnector`, which is the one that actually implements `WarehouseConnector`. There are two unrelated fake warehouse connectors in the codebase; only one is wired to the real interface.
- Similarly, `providers.FakeSqlGenerator.generate(submitted_text, resolved_metric=...)` returns a `SqlGeneration` dataclass with a different shape than `llm.adapter.LlmAdapter.generate_sql(...)`'s `SqlGenerationResult` — `PipelineOrchestrator` uses the former, not the ABC.
- **Before Gate 7 can safely swap in real providers**, `PipelineOrchestrator` should be constructor-injected with the actual ABCs (`WarehouseConnector`, `LlmAdapter`, and a new `SchemaRetriever` ABC — not yet present anywhere in the codebase), and `providers.py`'s duplicate fakes should either be retired in favor of the ABC-conformant ones or updated to inherit from them. This is flagged now specifically so it is not discovered mid-Gate-7 while real-provider code is also being written.

### How schema retrieval should stay behind a retriever interface

Introduce `app/rag/retriever.py` (or `core/retriever.py`) with a `SchemaRetriever` ABC/Protocol:

```python
class SchemaRetriever(Protocol):
    async def retrieve(self, submitted_text: str, tenant_id: UUID) -> tuple[list[SchemaChunk], float]: ...
```

matching `providers.FakeSchemaRetriever`'s existing signature closely enough that swapping implementations is mechanical (adding `tenant_id` for multi-tenant scoping is the one deliberate change). The real implementation does pgvector cosine-similarity retrieval per PRD §4.4/Engineering Spec §14 ("Fetch schema metadata from Snowflake. Chunk. Embed... Store in pgvector"), scoped by `tenant_id` so schema embeddings never cross tenant boundaries.

### How SQL generation should stay behind a model-agnostic adapter

`llm/adapter.py`'s `LlmAdapter` ABC already exists and is already correctly model-agnostic per Engineering Spec §3's hard constraint. Gate 7's job is to (a) make `PipelineOrchestrator` actually depend on `LlmAdapter` instead of `providers.FakeSqlGenerator` (the cleanup above), and (b) implement `llm/claude.py`'s real `ClaudeAdapter(LlmAdapter)`. No orchestration code should reference `claude.py` or any Anthropic-specific type. The real implementation adds `schema_chunks` and `session_context_block` as inputs without changing the interface contract from the pipeline's perspective.

### How SQL validation should happen before warehouse execution

Per Engineering Spec §2/§10, `sqlglot` AST validation (reject non-`SELECT` root node) runs before any Snowflake connection opens. `generation.validation_passed` is already a boolean threaded through `SqlGeneration`/`compute_confidence` today, currently hardcoded `True` by the fake generator. Gate 7 must perform real `sqlglot` parsing — inside the real `LlmAdapter` implementation, or in a small adjacent `sql_validation.py` invoked right after generation and before `WarehouseConnector.execute_readonly` — using the pipeline's already-correct call order (validate at the `sql_validation` `PipelineStage`, then execute). Per Engineering Spec §14 Week 2 item 8, one retry with an error-correction prompt is allowed on validation failure before surfacing `sql_generation_failed`.

### How Snowflake connector should stay behind a warehouse interface

`warehouse/connector.py`'s `WarehouseConnector` ABC and `warehouse/snowflake.py`'s `FakeSnowflakeConnector` already establish the pattern (verified: `FakeSnowflakeConnector(WarehouseConnector)`, one abstract method `execute_readonly(sql, *, snowflake_role)`). Gate 7 adds a real `SnowflakeConnector(WarehouseConnector)` in the same module, with no Snowflake-specific code anywhere else in the codebase — already an enforced convention per Engineering Spec §3.

### How read-only enforcement should happen before opening the warehouse connection

Two-layered per PRD line 50 and Engineering Spec §10: (1) `sqlglot` validation of generated SQL happens first (above); (2) the Snowflake connection itself opens using the user's existing read-only `snowflake_role` (already on `AuthClaims`/`VoiceSession`, cached via `user_snowflake_roles` in the verified Gate 5 schema) — never an elevated service-account role ("VoxQuery has no shadow permission layer"). The real `execute_readonly` must not open a connection at all until validation has already passed, and must apply the 10,000-row `LIMIT` hard cap if not already present in the generated SQL, wrapped in the spec's 30-second timeout.

### How result shapes should flow to chart selection/storytelling without raw rows crossing LLM/session/audit/observability boundaries

This is the single security invariant threaded through Gates 5, 6, and 7 simultaneously. `WarehouseConnector.execute_readonly` already returns `tuple[ResultPayload, ResultShape]` — correctly pre-split. Gate 7 must preserve this split exactly:

```
Snowflake result
    -> ResultPayload (rows live here -- internal to the warehouse connector call only)
    -> ResultShape (extracted: columns, chart_type, row_count, aggregate_summary)
        -> sessions.append_turn(result_shape=shape)   [Redis -- no rows, already true today]
        -> audit.record_turn(turn)                     [Postgres turns.result_json -- no rows, Gate 5 §3.11]
        -> Langfuse span outputs                       [shape fields only, Gate 6 §4]
        -> ResultReadyEvent.result_json                [no rows, already true today]
    -> ResultPayload lives on TurnRecord.full_result (in-memory only)
        -> returned ONLY by GET /api/result/{turn_id}  [the one legitimate crossing point]
```

Chart selection and storytelling should operate on `ResultShape` plus server-computed aggregate statistics (`aggregate_summary` already exists for exactly this purpose) rather than `ResultPayload.rows`, since Engineering Spec §9 explicitly lists "raw Snowflake result rows" as **never injected** into any LLM prompt. `FakeStoryteller.summarize(result_shape, user_query)`'s existing signature already enforces this at the type level — the real storytelling implementation must preserve that exact signature rather than widening it to accept raw rows.

### What Gate 5/Gate 6 choices are prerequisites for safe Gate 7 implementation

- Gate 5's raw-row exclusion enforcement (§3.11) must be proven correct and tested (via the sentinel test) before Gate 7 introduces a real Snowflake connector returning real customer data — otherwise Gate 7 is the first time the "never persist raw rows" rule is exercised under real-data stakes.
- Gate 6's non-blocking-failure pattern (Langfuse errors never break the user flow) should exist before Gate 7, because real LLM/Snowflake calls are slower and more failure-prone than today's stubs, making a coincidence of a Langfuse hiccup and a real pipeline hiccup more likely — Gate 7 should not be the first time that interaction is tested.
- The `providers.py`/`llm/adapter.py`/`warehouse/connector.py` duplication cleanup flagged above should happen as its own small, isolated change immediately before Gate 7's real-provider work begins, so the actual Gate 7 deliverable is not tangled with an unrelated refactor in the same change.

---

## 6. Risks And Controls

| Risk | Likelihood | Impact | Control |
|---|---|---|---|
| Schema drift between Redis `SessionHistoryTurn` and Postgres `turns` | Medium | High | Both write points sit next to each other in `_complete_turn` (verified lines 322/new-audit-call) — a single code path updates both, rather than two call sites that could drift out of sync. |
| Raw warehouse row leakage into Postgres/Langfuse/session/LLM context | Low today (stubs) -> Medium at Gate 7 (real rows) | Critical | Two independent layers: explicit column mapping (structural) + `if "rows" in payload: raise` runtime guard (not a bare `assert`, per §3.11) + a dedicated sentinel-value test. Repeated at each new boundary in Gates 6/7 previews rather than assumed "handled elsewhere." |
| Audit write failure breaking user flow | Medium (network blip) | Should be zero | Pipeline and REST code only enqueue audit jobs; the process-lifetime audit worker owns database I/O, catches/logs failures at tier 1, and never propagates them to user-facing flow. No raw `asyncio.create_task` audit writes are allowed inside per-turn `asyncio.run(...)` loops. |
| Feedback duplicate behavior regressing | Low | Medium | The existing `turn.feedback_submitted` 409 guard in `rest.py` (verified) is untouched by Gate 5 — the Postgres call is added strictly after it fires successfully. The Postgres `UPDATE` is additionally idempotent on its own. |
| Langfuse failure breaking user flow | Medium (SDK outage) | Should be zero | Same never-raise wrapping pattern as the audit store, explicitly required as a Gate 6 preview item, not left implicit. |
| Provider-specific LLM/Snowflake details leaking outside adapters | Low during Gates 5–6 (stubs only) -> Medium at Gate 7 | High (InfoSec/PRD requirement) | `llm/claude.py` and `warehouse/snowflake.py` remain the only allowed locations for provider-specific code (already enforced convention, Engineering Spec §3). The `providers.py` duplication cleanup (§5) is flagged as a pre-Gate-7 prerequisite specifically so this isn't silently violated by an untyped fake that never gets replaced. Recommend a code-review rule: any Anthropic or Snowflake-specific import found outside these two files blocks merge. |
| Secret leakage in logs/tests/docs | Low | Critical | `services/telemetry.py`'s `emit()` has no auto-redaction ("Callers are responsible for never passing secrets... The logger serialises whatever it receives") — `AuditStore` implementations must never pass `SUPABASE_DATABASE_URL` (or any DSN) into any `emit()` call, only status strings and non-sensitive identifiers. `main.py`'s existing `AccessTokenRedactionFilter` covers WS `token` query params only; it is not extended to a Postgres-DSN case because the DSN should never reach a log call in the first place if the above rule is followed. |
| Supabase unavailable or slow health behavior | Low | Low (non-blocking) | `health_status()`'s short-timeout check mirrors `RedisSessionStore.health_status()`'s existing try/`ping()`/except pattern; Interface Contracts §3.6 (verified) already defines `degraded` as non-fatal, returning HTTP 200 either way. |
| Tests requiring live Supabase credentials | High if unguarded | Medium (CI breakage) | Every Gate 5 unit test uses a fake/mocked driver (§3.12); any live-credential test is `@pytest.mark.skipif`-guarded and separately reported in closure evidence, never assumed to have run. |

---

## 7. Refined Gate 5 Implementation Handoff Prompt

Complete, copy-paste-ready. Corrects the migration-path error identified in the Verification Ledger (§0, item 10) relative to any prior draft. Not executed in this pass — planning only.

~~~text
You are implementing Gate 5 of the VoxQuery Voice Subsystem on branch `voice-subsystem`.

SCOPE: Gate 5 (Supabase/Postgres Audit Writes) ONLY.
Do NOT implement Gate 6 (Langfuse Observability).
Do NOT implement Gate 7 (Real RAG / SQL / Snowflake Integration).
Do NOT add any Langfuse dependency, RAG/embedding code, real SQL generation, or Snowflake
connection code in this change.

PRE-WORK VERIFICATION (do these checks yourself; do not trust any prior report of repo
state, including this one — re-run them fresh, since time may have passed):
1. `git status --short --branch` and `git log -5 --oneline --decorate`. Confirm branch,
   clean tree, and last commit.
2. `git diff HEAD -- frontend/next-env.d.ts`. If non-empty, revert it before committing
   anything — do not commit dev-server artifacts.
3. `ls tmp-smoke-logs` (or equivalent). If it exists, do not commit it; delete it or add
   it to `.gitignore`.
4. Confirm no secret-looking files (`.env`, `.env.local`, `*.pem`, `*.key`, credential
   dumps) are present or staged. Do not open the contents of any file that looks
   secret-like; confirm it is not staged and stop.
5. `find db -type f` and `ls backend/migrations 2>&1`. As of this writing,
   `db/migrations/001_voice_subsystem.sql` already contains the full app-metadata
   schema, and `backend/migrations/` DOES NOT EXIST. If your own check disagrees with
   this, trust your own check over this document and proceed accordingly — but do NOT
   create a new migration tree under `backend/migrations/` without first confirming
   `db/migrations/` is genuinely absent or wrong; the two paths must not coexist.
6. Do not commit any real Supabase/Postgres credentials anywhere in the repo, in test
   fixtures, or in documentation examples.

SOURCE DOCS TO READ FIRST (in this order):
- docs/voice-subsystem/implementation-roadmap.md (Gate 5 acceptance criteria)
- docs/voice-subsystem/engineering-spec.md — Section 6 (Phases 7-8), Section 7.2
  (Postgres tables — frozen schema reference), Section 10 (Security Constraints),
  Section 13 (Environment Variables)
- docs/voice-subsystem/interface-contracts.md — Section 3.6 (/health contract)
- docs/voice-subsystem/gate-4-closure.md (for the shape of your own closure report;
  note its final sentence mislabels Gate 5 as "Natural Language Processing & Agent
  Hand-off" — this is a known documentation error; implementation-roadmap.md is
  authoritative and Gate 5 is Supabase/Postgres Audit Writes)

VERIFIED REPOSITORY FACTS AT TIME OF WRITING (re-check all of these yourself — do not
assume they still hold):
- `db/migrations/001_voice_subsystem.sql` contains `tenants`, `users`, `conversations`,
  `user_snowflake_roles`, `tenant_connections`, `turns`, `clarifications`, matching
  engineering-spec.md Section 7.2. Do not recreate these tables elsewhere. Add new
  migrations as `db/migrations/002_...sql`, `003_...sql`, etc.
- `db/demo_warehouse/001_ecommerce_schema.sql` is the separate demo warehouse schema.
  Never add an app-metadata table here.
- `backend/app/config.py`'s `Settings` has no Postgres/Supabase field yet.
- `backend/.env.example` lists `SUPABASE_DATABASE_URL` as the expected env var name.
  Use this exact name.
- `backend/app/main.py`'s `/health` handler hardcodes `"postgres": "not_configured"`,
  and `backend/tests/test_rest_flow.py` line ~212 asserts this value. Your change must
  make this value come from a real health check while keeping the assertion true when
  Postgres is not configured.
- `backend/app/models/contracts.py`'s `TurnRecord` has all fields needed for `turns`,
  plus a `full_result: ResultPayload | None` field holding raw rows that must NEVER be
  persisted to Postgres, plus a `session_id: UUID` field that must NOT be added to the
  `turns` table (the spec intentionally omits it there — conversation_id is the durable
  key). The Postgres-safe counterpart of the result is `turn.result_json: ResultShape
  | None` — persist this one.
- `backend/app/services/pipeline.py`'s `PipelineOrchestrator._complete_turn` is where a
  turn is marked complete and appended to Redis history via `self.sessions.append_turn`.
  This is your turn-write hook point.
- The escaped-clarification path in `resolve_clarification` never calls `_complete_turn`
  and pops the turn from `self.turns` — do not write ANY audit row (turn or
  clarification) for an escaped clarification; the `clarifications.turn_id` FK has
  nothing to reference in that case.
- `backend/app/api/rest.py`'s `POST /api/feedback` sets `turn.quality_flag = "low"` in
  memory after a duplicate-feedback guard — add your Postgres update after this guard
  fires successfully, without altering the guard logic itself.

EXACT ACCEPTANCE CRITERIA (from implementation-roadmap.md):
1. An app metadata migration is applied separately from the demo warehouse schema.
2. Turns are written to Postgres asynchronously (non-blocking relative to the
   user-facing request/response cycle).
3. Clarifications are written to Postgres asynchronously (option-selected and timeout
   only — never for escape).
4. Feedback (thumbs-down) updates the `quality_flag` column in Postgres.
5. Raw warehouse result rows (`turn.full_result` / `ResultPayload.rows`) are never
   stored in any Postgres app metadata table.

MIGRATION REQUIREMENTS:
- Write a minimal migration runner that bootstraps `schema_migrations`, scans `db/migrations/*.sql`, applies unapplied migrations idempotently, and records successful versions.
- Do not create `backend/migrations/`.
- Do not touch `db/demo_warehouse/`.
- Do not add a bookkeeping migration solely for `schema_migrations`.
- Preserve `db/migrations/001_voice_subsystem.sql` unless a concrete spec mismatch is found.
- All existing `turns` and `clarifications` columns are required in the write path.

AUDIT STORE REQUIREMENTS:
- Create `AuditStore` with:
  - `async start() -> None`
  - `async close() -> None`
  - `async health_status() -> str`
  - `record_turn(*, turn: TurnRecord, identity: AuditIdentity, clarification: AuditClarification | None = None) -> None`
  - `update_quality_flag(turn_id: UUID, flag: str) -> None`
- `record_turn` and `update_quality_flag` are synchronous enqueue methods. They must return immediately, never raise, perform no network I/O inline, and must not use `asyncio.create_task` from the pipeline loop.
- Implement `AuditIdentity` with `user_id`, `tenant_id`, `email`, `role`, `snowflake_role`, and optional `tenant_name`.
- Implement `AuditClarification` with `prompt_sent`, `user_choice`, and `resolution_type` limited to `"option_selected"` / `"timeout"`.
- Implement `NoopAuditStore`; `health_status()` returns `"not_configured"`.
- Implement `PostgresAuditStore` with a process-lifetime worker/dispatcher that owns the async database pool.
- The completed-turn worker transaction must upsert tenant, user, user_snowflake_role, conversation, insert turn, and then insert optional clarification.
- `tenant_connections` is not written in Gate 5.
- Never persist `turn.full_result` or any raw `rows` key.

PIPELINE / REST INTEGRATION REQUIREMENTS:
- Thread `AuditStore` into `PipelineOrchestrator`.
- Ensure `AuthClaims` data is available to build `AuditIdentity` for completed-turn audit writes.
- In `_complete_turn`, enqueue `record_turn(...)` after `self.sessions.append_turn(...)`.
- For option-selected and timeout clarifications, pass `AuditClarification` into the completed-turn path.
- For escape, enqueue nothing.
- In `POST /api/feedback`, enqueue only `audit.update_quality_flag(request.turn_id, "low")` after the duplicate guard and in-memory `turn.quality_flag = "low"` update.
- Do not call `record_turn` from feedback.

HEALTH ENDPOINT REQUIREMENTS:
- Initialize audit store during FastAPI lifespan/startup.
- Close audit store during shutdown.
- `/health` must await `app.state.audit.health_status()`.
- Noop store returns `"not_configured"`.
- Postgres store returns `"ok"` only if a lightweight ping succeeds within 100ms.
- It returns `"degraded"` on timeout, worker unavailable, pool unavailable, or database exception.
- `/health` still returns HTTP 200.

TESTS REQUIRED:
- `backend/tests/test_audit_noop.py`
- `backend/tests/test_audit_postgres.py`
- Extend `backend/tests/test_rest_flow.py`
- Add `backend/tests/test_pipeline_gate5.py`
- Prove no raw `asyncio.create_task` audit writes exist inside the per-turn `asyncio.run(...)` pipeline path.
- Prove `record_turn` enqueues exactly one job and returns immediately.
- Prove the audit worker transaction writes tenant, user, user_snowflake_role, conversation, turn, and optional clarification in FK-safe order.
- Prove option-selected and timeout clarifications are inserted only as part of completed-turn audit jobs.
- Prove escaped clarifications enqueue no turn and no clarification.
- Prove queue-full, worker-failure, and database-failure cases log tier-1 telemetry and do not break pipeline or feedback flow.
- Prove `/health` returns `not_configured`, `ok`, and `degraded` using fakes/mocks only.

Additional required tests:
- Prove that pipeline audit writes are not scheduled with raw `asyncio.create_task` inside the per-turn `asyncio.run(...)` loop.
- Prove that `record_turn` enqueues exactly one job and returns immediately.
- Prove that the audit worker transaction inserts/upserts tenant, user, user_snowflake_role, conversation, turn, and optional clarification in FK-safe order.
- Prove that option-selected and timeout clarifications are inserted only as part of the completed-turn audit job.
- Prove that escaped clarifications enqueue no turn and no clarification.
- Prove that duplicate clarification rows are not created if an audit job is retried.
- Prove that queue-full or worker-failure cases log tier-1 telemetry and do not break the pipeline or feedback endpoint.
- Prove `/health` returns `not_configured`, `ok`, and `degraded` using fakes/mocks only.

VERIFICATION COMMANDS (run from `backend/`):
1. `git status --short` — confirm clean before and after your change except for your
   intended diffs.
2. `python -m pytest -x -v tests/` — must pass with `SUPABASE_DATABASE_URL` unset.
3. `grep -r '"rows"' backend/app/audit/` (or wherever your audit module lives) — must
   return nothing referencing `turn.full_result`'s content.
4. Start the server locally with no Supabase credentials; `curl localhost:8000/health`
   — expect `"postgres": "not_configured"`.
5. Optional, only if you have real credentials: set `SUPABASE_DATABASE_URL`, restart,
   `curl localhost:8000/health` — expect `"postgres": "ok"`; apply the migration with
   `psql $SUPABASE_DATABASE_URL -f db/migrations/001_voice_subsystem.sql`.

DELIVERABLES:
- `db/migrations/001_voice_subsystem.sql` unchanged unless you document a reason otherwise.
- New audit module (`app/audit/` or `app/services/audit.py`).
- Modified `app/config.py`, `app/main.py`, `app/services/pipeline.py`, `app/api/rest.py`.
- New/modified test files as listed above.
- `docs/voice-subsystem/gate-5-closure.md`, in the style of `gate-4-closure.md`
  (status, date, commit hash, executive summary, evidence, verification highlights,
  conclusion), explicitly stating whether a live Supabase smoke test was performed,
  and explicitly confirming (citing the sentinel test) that `record_turn` never
  persists `turn.full_result`.

DO NOT:
- Implement Gate 6 (Langfuse) or Gate 7 (real RAG / SQL generation / Snowflake).
- Create or write to a `backend/migrations/` directory — it does not exist in this
  repository and must not be introduced; use `db/migrations/`.
- Commit dev-server artifacts or any secrets/credentials.
- Introduce a `POSTGRES_URL` env var name — use `SUPABASE_DATABASE_URL`.
- Persist `turn.full_result` / raw warehouse rows to any Postgres table.
- Add a `session_id` column to the `turns` table.
- Rely on a bare `assert` as the only guard against raw-row persistence.
~~~

---

## 8. Open Questions

1. **Should `db/migrations/001_voice_subsystem.sql` be edited directly, or should Gate 5 always add a new file?**
   Why it matters: determines whether "migration applied separately from demo warehouse schema" is satisfied by editing an existing frozen file (already true structurally, §1) or requires a new artifact.
   Recommended default: Do not add a bookkeeping migration solely to create `schema_migrations` unless the implementation genuinely needs a new SQL migration.

The migration runner should bootstrap its own `schema_migrations` table with:

`CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())`

Then it should scan `db/migrations/*.sql`, apply migrations not already recorded, and mark each successful migration as applied.

It must never touch `db/demo_warehouse/`.

`db/migrations/001_voice_subsystem.sql` is the canonical app metadata schema and should remain unchanged unless the implementation discovers a concrete mismatch against the engineering spec.
   Blocking? **No.**

2. **`asyncpg` or `psycopg[async]`?**
   Why it matters: affects the exact connection-pool code shape and the new dependency added to `pyproject.toml`.
   Recommended default: `asyncpg` — lighter weight, common FastAPI pairing, and the same driver family Gate 7 will want for pgvector.
   Blocking? **No** — either satisfies all stated acceptance criteria.

3. **Should `SUPABASE_DATABASE_URL` fail startup in production if absent?**
   Why it matters: silent no-op audit writes in a live pilot could mean audit data required for post-pilot analysis is simply never captured, with no error surfaced.
   Recommended default: do not fail startup (match Redis's graceful-degradation precedent, where `SESSION_STORE=memory` is a default, not an error); instead, log a structured warning at startup if `app_env == "production"` and the URL is absent, so it's visible in Railway logs without blocking the process.
   Blocking? **No** — the no-op default is safe; revisit after piloting if audit completeness turns out to matter more than uptime.

4. **Should `gate-4-closure.md`'s mislabeling of Gate 5 be corrected?**
   Why it matters: a reader of that file alone, without also reading `implementation-roadmap.md`, could be misled about what Gate 5 actually is.
   Recommended default: fix the one sentence as part of Gate 5's closure work or as a tiny separate docs commit. Zero effect on Gate 5's actual acceptance criteria, which come from `implementation-roadmap.md`.
   Blocking? **No.**

5. **Lazy provisioning vs. seed migration?**
   Why it matters: `turns.conversation_id` → `conversations.user_id` → `users.tenant_id` → `tenants.id` is a real FK chain.
   Recommended default: lazy transactional provisioning inside the audit worker using `AuditIdentity` and `TurnRecord`: upsert tenant, user, user_snowflake_role, and conversation before inserting the turn. Use a deterministic tenant name fallback such as `tenant-{tenant_id}` until a real tenant provisioning flow exists.
   Blocking? **No**, provided the completed-turn transaction satisfies all FKs before inserting `turns`.

6. **`providers.py`'s duplicate/inconsistent fakes relative to the real ABCs — fix now or at Gate 7?**
   Why it matters: a real, verified inconsistency (§5) that will make Gate 7 harder if left unresolved.
   Recommended default: leave untouched during Gate 5 (out of scope), resolve as an explicit, isolated step immediately before Gate 7's real-provider work begins.
   Blocking? **No** — does not affect any Gate 5 acceptance criterion.

No other blocking questions were identified. Gate 5 can proceed with the defaults above.
