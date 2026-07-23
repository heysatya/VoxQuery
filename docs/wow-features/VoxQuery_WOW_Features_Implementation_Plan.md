# VoxQuery "WOW Features" — Production Implementation Plan

**Purpose:** Turn the eight demo/mock features on `voxquery-wow-features` (base commit `1dc4ecf`, current HEAD `c091782`) into real, production-grade capabilities. This plan is grounded in the actual codebase — existing models, existing infra (Upstash Redis, Snowflake connection pooling, Deepgram TTS/STT, Clerk auth, asyncpg/Postgres, Docker deployment) — not hypothetical infra. Every gap identified in the code review is closed here with a concrete design, schema, contract, and code.

**Non-negotiable ground rules for every feature below:**
1. No hardcoded/mock data paths in the code that ships to production. Dev/test fixtures must be behind explicit environment flags, never a silent fallback.
2. Every new endpoint enforces tenant isolation (never trust a client-supplied `tenant_id`; always derive from `AuthClaims`).
3. Every new SQL-adjacent code path uses parameterized queries or an allowlist — no string interpolation of user input into SQL, ever.
4. Every feature that produces state (preferences, pins, sent emails) persists to Postgres, not process memory.
5. Every feature ships with tests that would fail if the feature were faked (i.e., tests assert against seeded, realistic data — not the shape of a mock).

---

## Phase 0 (Blocking Foundation): Durable Session & Turn Persistence

**Why this blocks everything:** `PipelineOrchestrator` in `backend/app/services/pipeline.py` currently stores every `TurnRecord` in `self.turns: dict[UUID, TurnRecord]` — pure process memory. It is never written to Postgres. This is why the Memory Graph and Drilldown features had no real data to build on and fell back to hardcoded demo content. `TurnRecord` already has almost everything we need (`generated_sql`, `full_result`, `parent_turn_id`, `chart_type`, `attempts`) — it just isn't durable. Fix this once, and Features 1, 2, and 6 become straightforward.

### 0.1 Schema — `backend/db/migrations/007_turn_persistence.sql`

```sql
-- Durable session + turn history, replacing in-memory PipelineOrchestrator.turns

CREATE TABLE IF NOT EXISTS sessions (
  session_id      UUID PRIMARY KEY,
  tenant_id       UUID NOT NULL REFERENCES tenants(id),
  user_id         UUID NOT NULL REFERENCES users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_active_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS turns (
  turn_id                 UUID PRIMARY KEY,
  session_id              UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  conversation_id         UUID NOT NULL,
  parent_turn_id          UUID REFERENCES turns(turn_id),
  tenant_id               UUID NOT NULL REFERENCES tenants(id),
  user_id                 UUID NOT NULL REFERENCES users(id),
  user_input              TEXT NOT NULL,
  generated_sql           TEXT NOT NULL DEFAULT '',
  source_tables           TEXT[] NOT NULL DEFAULT '{}',      -- parsed once at completion, reused by drilldown
  filter_predicates       JSONB NOT NULL DEFAULT '[]',        -- [{column, operator, value}], parsed once, reused by memory graph + drilldown
  chart_type              TEXT,
  chart_rationale         TEXT DEFAULT '',
  confidence_tier         TEXT,
  composite_score         DOUBLE PRECISION,
  result_json             JSONB,                              -- ResultShape (summary only)
  full_result             JSONB,                              -- ResultPayload (rows + semantic_columns), capped — see 0.3
  anomalies               JSONB NOT NULL DEFAULT '[]',         -- populated by Feature 6, consumed by Features 1 & 3
  proactive_questions     JSONB NOT NULL DEFAULT '[]',
  quality_flag            TEXT NOT NULL DEFAULT 'ok',
  latency_ms              INTEGER NOT NULL DEFAULT 0,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed                BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_turns_session_created ON turns (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_turns_tenant ON turns (tenant_id);
CREATE INDEX IF NOT EXISTS idx_turns_parent ON turns (parent_turn_id);
```

### 0.2 Repository — `backend/app/repositories/turn_repository.py`

```python
"""Durable turn persistence. Replaces PipelineOrchestrator.turns in-memory dict."""
from __future__ import annotations
from uuid import UUID
import json
import asyncpg
from app.models.contracts import TurnRecord, AuthClaims


class TurnRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def save(self, turn: TurnRecord, *, source_tables: list[str], filter_predicates: list[dict]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO turns (
                    turn_id, session_id, conversation_id, parent_turn_id, tenant_id, user_id,
                    user_input, generated_sql, source_tables, filter_predicates,
                    chart_type, chart_rationale, confidence_tier, composite_score,
                    result_json, full_result, anomalies, proactive_questions,
                    quality_flag, latency_ms, created_at, completed
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22)
                ON CONFLICT (turn_id) DO UPDATE SET
                    generated_sql = EXCLUDED.generated_sql,
                    source_tables = EXCLUDED.source_tables,
                    filter_predicates = EXCLUDED.filter_predicates,
                    chart_type = EXCLUDED.chart_type,
                    chart_rationale = EXCLUDED.chart_rationale,
                    confidence_tier = EXCLUDED.confidence_tier,
                    composite_score = EXCLUDED.composite_score,
                    result_json = EXCLUDED.result_json,
                    full_result = EXCLUDED.full_result,
                    anomalies = EXCLUDED.anomalies,
                    proactive_questions = EXCLUDED.proactive_questions,
                    quality_flag = EXCLUDED.quality_flag,
                    latency_ms = EXCLUDED.latency_ms,
                    completed = EXCLUDED.completed
                """,
                turn.turn_id, turn.session_id, turn.conversation_id, turn.parent_turn_id,
                turn.tenant_id, turn.user_id, turn.user_input, turn.generated_sql,
                source_tables, json.dumps(filter_predicates),
                turn.chart_type.value if turn.chart_type else None, turn.chart_rationale,
                turn.confidence_tier.value if turn.confidence_tier else None, turn.composite_score,
                turn.result_json.model_dump_json() if turn.result_json else None,
                turn.full_result.model_dump_json() if turn.full_result else None,
                json.dumps([]),  # anomalies populated by a separate update after Feature 6 runs
                json.dumps(turn.proactive_questions),
                turn.quality_flag.value, turn.latency_ms, turn.created_at, turn.completed,
            )

    async def get_session_turns(self, session_id: UUID, claims: AuthClaims, *, limit: int = 50) -> list[dict]:
        """Tenant-scoped fetch — never trust session_id alone."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM turns
                WHERE session_id = $1 AND tenant_id = $2
                ORDER BY created_at ASC
                LIMIT $3
                """,
                session_id, claims.tenant_id, limit,
            )
        return [dict(r) for r in rows]

    async def get_turn(self, turn_id: UUID, claims: AuthClaims) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM turns WHERE turn_id = $1 AND tenant_id = $2",
                turn_id, claims.tenant_id,
            )
        return dict(row) if row else None

    async def update_anomalies(self, turn_id: UUID, anomalies: list[dict]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE turns SET anomalies = $2 WHERE turn_id = $1",
                turn_id, json.dumps(anomalies),
            )
```

### 0.3 Wiring into the pipeline

In `pipeline.py`, `_run_turn_background` currently ends with `self.turns[turn.turn_id] = turn`. Change to:

```python
source_tables, filter_predicates = parse_sql_provenance(turn.generated_sql)  # see 1.2 — shared parser
await self._turn_repo.save(turn, source_tables=source_tables, filter_predicates=filter_predicates)
self.turns[turn.turn_id] = turn  # keep in-memory cache for hot-path reads within the same process; DB is now source of truth
```

`PipelineOrchestrator.__init__` takes a `TurnRepository` via dependency injection (constructed once in `main.py` from the shared `asyncpg.Pool`, same pattern already used in `api/rest.py`).

**Row cap for `full_result`:** cap stored rows at 500 per turn (`full_result.rows[:500]`) to keep the JSONB column bounded; drilldown re-queries the warehouse live for anything beyond the cached preview, so this cap costs nothing functionally.

**Definition of Done — Phase 0:** turns survive a backend restart; a session opened from a second backend instance/pod sees the same history; `test_turn_repository.py` seeds 5 turns across 2 tenants and asserts cross-tenant fetch returns zero rows.

---

## Feature 1 — Executive Memory Graph (Real)

### 1.1 What "real" means here
The graph must be built from the tenant's actual persisted turns for that session, must update as new turns complete, and must show real entities/metrics/filters parsed from the actual generated SQL and actual `semantic_columns` — not a static demo payload.

### 1.2 Shared SQL provenance parser — `backend/app/services/sql_provenance.py`

Used by both Feature 1 (graph) and Feature 2 (drilldown), computed once per turn and cached in the `turns` table (columns `source_tables`, `filter_predicates`) so we never re-parse SQL on every graph/drilldown request.

```python
"""Parses executed SQL to extract provenance: source tables and filter predicates.
Used to build memory-graph entity/filter nodes and to construct safe drilldown queries.
"""
from __future__ import annotations
import sqlglot
from sqlglot import exp


def parse_sql_provenance(sql: str) -> tuple[list[str], list[dict]]:
    if not sql.strip():
        return [], []
    try:
        tree = sqlglot.parse_one(sql, read="snowflake")
    except sqlglot.errors.ParseError:
        return [], []

    tables = sorted({t.name for t in tree.find_all(exp.Table)})

    predicates: list[dict] = []
    where = tree.find(exp.Where)
    if where:
        for cond in where.find_all(exp.EQ, exp.GT, exp.LT, exp.GTE, exp.LTE, exp.In):
            col = cond.find(exp.Column)
            if col is None:
                continue
            predicates.append({
                "column": col.name,
                "operator": cond.key,  # "eq", "gt", etc.
                "value": cond.expression.sql() if hasattr(cond, "expression") else None,
            })
    return tables, predicates


def extract_metrics(semantic_columns: list[dict]) -> list[str]:
    """Column names classified as metrics by the existing ResultColumnSemantic inference."""
    return [c["name"] for c in semantic_columns if c.get("role") == "metric"]
```

### 1.3 Real graph builder — `backend/app/services/memory_graph.py` (replaces the current file entirely)

```python
from __future__ import annotations
import logging
from uuid import UUID
from app.config import Settings
from app.models.contracts import GraphEdge, GraphNode, MemoryGraphResponse, AuthClaims
from app.repositories.turn_repository import TurnRepository

logger = logging.getLogger("voxquery.services.memory_graph")


async def generate_memory_graph(
    session_id: UUID,
    claims: AuthClaims,
    settings: Settings,
    turn_repo: TurnRepository,
    *,
    turn_limit: int = 50,
) -> MemoryGraphResponse:
    turns = await turn_repo.get_session_turns(session_id, claims, limit=turn_limit)
    if not turns:
        # Empty session — real empty state, not a fake populated graph.
        return MemoryGraphResponse(session_id=session_id, nodes=[], edges=[])

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    turn_id_to_query_node: dict[str, str] = {}

    for idx, turn in enumerate(turns, start=1):
        q_id = f"q_{turn['turn_id']}"
        nodes.append(GraphNode(id=q_id, label=turn["user_input"], type="query", turn_index=idx))
        turn_id_to_query_node[str(turn["turn_id"])] = q_id

        for table in turn["source_tables"] or []:
            e_id = f"e_{table}"
            if not any(n.id == e_id for n in nodes):
                nodes.append(GraphNode(id=e_id, label=f"Entity: {table}", type="entity", turn_index=idx))
            edges.append(GraphEdge(source=q_id, target=e_id, relation="queries"))

        full_result = turn.get("full_result") or {}
        semantic_columns = full_result.get("semantic_columns", []) if isinstance(full_result, dict) else []
        for metric_col in [c["name"] for c in semantic_columns if c.get("role") == "metric"]:
            m_id = f"m_{turn['turn_id']}_{metric_col}"
            nodes.append(GraphNode(id=m_id, label=f"Metric: {metric_col}", type="metric", turn_index=idx))
            edges.append(GraphEdge(source=q_id, target=m_id, relation="computes"))

        for pred in turn["filter_predicates"] or []:
            f_id = f"f_{turn['turn_id']}_{pred['column']}"
            nodes.append(GraphNode(
                id=f_id, label=f"Filter: {pred['column']} {pred['operator']} {pred['value']}",
                type="filter", turn_index=idx,
            ))
            edges.append(GraphEdge(source=q_id, target=f_id, relation="applies"))

        anomalies = turn.get("anomalies") or []
        if anomalies:
            i_id = f"i_{turn['turn_id']}"
            top = anomalies[0]
            nodes.append(GraphNode(
                id=i_id, label=f"Insight: anomaly in {top.get('column', 'result')}",
                type="insight", turn_index=idx,
            ))
            edges.append(GraphEdge(source=q_id, target=i_id, relation="yields"))

        # Real conversational structure: use parent_turn_id, not just linear turn order,
        # so branches from clarification questions render as actual branches.
        parent_id = turn.get("parent_turn_id")
        if parent_id and str(parent_id) in turn_id_to_query_node:
            edges.append(GraphEdge(
                source=turn_id_to_query_node[str(parent_id)], target=q_id, relation="followed_by",
            ))

    return MemoryGraphResponse(session_id=session_id, nodes=nodes, edges=edges)
```

### 1.4 API router change — `backend/app/api/memory_graph.py`

The router must inject the real dependencies and pass `claims` (for tenant scoping) instead of calling the generator with nothing:

```python
@router.get("/api/memory-graph/{session_id}", response_model=MemoryGraphResponse)
async def get_memory_graph(
    session_id: UUID,
    turn_limit: int = 50,
    claims: AuthClaims = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    turn_repo: TurnRepository = Depends(get_turn_repository),  # new provider, wraps the shared pool
) -> MemoryGraphResponse:
    cache_key = f"memgraph:{claims.tenant_id}:{session_id}"
    cached = await redis_get_json(cache_key)  # Upstash Redis, already configured via UPSTASH_REDIS_URL
    if cached:
        return MemoryGraphResponse.model_validate(cached)

    graph = await generate_memory_graph(session_id, claims, settings, turn_repo, turn_limit=turn_limit)
    await redis_set_json(cache_key, graph.model_dump(), ttl_seconds=30)
    return graph
```

Cache invalidation: after `TurnRepository.save()` completes in the pipeline, delete `memgraph:{tenant_id}:{session_id}` so the next graph fetch is fresh. A 30s TTL as a safety net covers any missed invalidation.

### 1.5 Frontend — replace the hand-rolled SVG DAG with `react-flow`

The current `ExecutiveMemoryGraph.tsx` draws nodes manually. For a real product-grade interactive DAG (pan, zoom, drag, minimap — table stakes for anything calling itself a "visual DAG"), use `reactflow` with the `dagre` layout algorithm for automatic hierarchical positioning:

```tsx
// frontend/app/components/memory/ExecutiveMemoryGraph.tsx
import ReactFlow, { Background, Controls, MiniMap, useNodesState, useEdgesState } from "reactflow";
import dagre from "dagre";
import "reactflow/dist/style.css";

const NODE_COLORS: Record<string, string> = {
  query: "#6366F1", entity: "#10B981", metric: "#F59E0B", filter: "#8B5CF6", insight: "#F43F5E",
};

function layoutWithDagre(nodes: GraphNode[], edges: GraphEdge[]) {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 40, ranksep: 80 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, { width: 180, height: 48 }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  return nodes.map((n) => {
    const { x, y } = g.node(n.id);
    return {
      id: n.id,
      position: { x, y },
      data: { label: n.label, type: n.type },
      style: { background: NODE_COLORS[n.type], color: "#fff", borderRadius: 8, fontSize: 11, padding: 8 },
    };
  });
}
```

Node click opens the existing inspector side-panel, populated with real fields now available: `generated_sql` snippet, `chart_type`, `latency_ms`, `confidence_tier` — pulled straight from the API response, no invented copy.

**Real-time updates:** the app already streams pipeline events over SSE/WebSocket per turn (`result_ready` event exists in `contracts.py`). Subscribe the graph component to that same event stream; on `result_ready` for the active session, invalidate the client-side query cache (React Query / SWR) for `/api/memory-graph/{session_id}` and refetch — the graph grows live as the exec keeps talking, no manual refresh button needed (the current "refetch" button becomes a manual override, not the primary mechanism).

**Definition of Done:** two different tenants asking different questions in the same time window get visibly different, session-specific graphs; a `test_memory_graph.py` integration test seeds 4 turns with distinct SQL (one with a `WHERE state = 'CA'`, one with a JOIN) and asserts the resulting graph contains an entity node per joined table and a filter node matching the WHERE clause — not just "len(nodes) >= 4".

---

## Feature 2 — Row-Level Metric Drilldowns (Real)

### 2.1 Design
Never re-guess a query. Every turn already stores `source_tables` and `filter_predicates` (Phase 0 / §1.2). Drilldown reuses those exact filters — this is the only way "drill into the row behind this metric" is actually true to what the user saw, rather than a coincidentally similar new query.

### 2.2 Safe query builder — `backend/app/services/drilldown.py` (replaces the current file)

```python
from __future__ import annotations
import logging
from uuid import UUID
from app.config import Settings
from app.models.contracts import AuthClaims
from app.repositories.turn_repository import TurnRepository
from app.services.snowflake_pool import get_tenant_connection  # existing pooling service from git history
from app.services.sql_provenance import SAFE_OPERATORS

logger = logging.getLogger("voxquery.services.drilldown")

ALLOWED_SORT_DIRECTIONS = {"asc", "desc"}


async def get_row_drilldown(
    turn_id: UUID,
    claims: AuthClaims,
    settings: Settings,
    turn_repo: TurnRepository,
    *,
    row_filter: dict[str, str] | None = None,
    page: int = 1,
    page_size: int = 25,
    sort_by: str | None = None,
    sort_dir: str = "asc",
) -> dict:
    turn = await turn_repo.get_turn(turn_id, claims)
    if turn is None:
        raise ApiError(ErrorCode.not_found, status_code=404, detail="Turn not found for this tenant.")

    if not turn["source_tables"]:
        raise ApiError(ErrorCode.invalid_request, status_code=422,
                        detail="This turn's query has no drillable source table.")

    table = turn["source_tables"][0]  # primary table; multi-table drilldown is a v2 refinement, not needed for v1 parity
    if not TABLE_NAME_RE.fullmatch(table):  # allowlist regex, defends against any parser edge case
        raise ApiError(ErrorCode.invalid_request, status_code=422, detail="Unresolvable source table.")

    known_columns = await get_table_columns(table, claims.tenant_id)  # cached schema introspection, 1h TTL
    if sort_by and sort_by not in known_columns:
        raise ApiError(ErrorCode.invalid_request, status_code=422, detail="Unknown sort column.")
    if sort_dir not in ALLOWED_SORT_DIRECTIONS:
        sort_dir = "asc"

    where_clauses: list[str] = []
    params: list = []
    for pred in turn["filter_predicates"] or []:
        if pred["operator"] in SAFE_OPERATORS and pred["column"] in known_columns:
            where_clauses.append(f'"{pred["column"]}" {SAFE_OPERATORS[pred["operator"]]} %s')
            params.append(pred["value"])
    if row_filter:
        for col, val in row_filter.items():
            if col not in known_columns:
                continue
            where_clauses.append(f'"{col}" = %s')
            params.append(val)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    order_sql = f'ORDER BY "{sort_by}" {sort_dir.upper()}' if sort_by else ""
    offset = (page - 1) * page_size

    query = f'SELECT * FROM "{table}" {where_sql} {order_sql} LIMIT %s OFFSET %s'
    params += [page_size, offset]

    count_query = f'SELECT COUNT(*) AS total FROM "{table}" {where_sql}'

    # Executes using the requesting user's actual warehouse role — real row-level security,
    # not an app-level filter that a compromised frontend could bypass.
    async with get_tenant_connection(claims.tenant_id, claims.snowflake_role) as conn:
        rows = await conn.fetch(query, *params)
        total = (await conn.fetchrow(count_query, *params[:-2]))["total"]

    return {
        "rows": [dict(r) for r in rows],
        "page": page,
        "page_size": page_size,
        "total_rows": total,
        "source_table": table,
        "applied_filters": turn["filter_predicates"],
    }
```

`SAFE_OPERATORS` maps `{"eq": "=", "gt": ">", "lt": "<", "gte": ">=", "lte": "<="}` — this is the complete allowlist; nothing else is ever interpolated into SQL.

### 2.3 API contract — `backend/app/api/rest.py`

```python
class DrilldownRequest(BaseModel):
    row_filter: dict[str, str] | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=200)
    sort_by: str | None = None
    sort_dir: Literal["asc", "desc"] = "asc"


@router.post("/api/drilldown/{turn_id}")
async def get_drilldown(
    turn_id: UUID,
    request: DrilldownRequest,
    claims: AuthClaims = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    turn_repo: TurnRepository = Depends(get_turn_repository),
) -> dict:
    return await get_row_drilldown(turn_id, claims, settings, turn_repo, **request.model_dump())
```

(POST, matching the original PRD intent — the shipped code wrongly used GET with no body, which is why it could never accept a row filter or sort params.)

A separate streaming export endpoint avoids the "CSV only exports the current page" bug in the current modal:

```python
@router.get("/api/drilldown/{turn_id}/export.csv")
async def export_drilldown_csv(turn_id: UUID, claims: AuthClaims = Depends(get_current_user), ...) -> StreamingResponse:
    # Same query builder, page_size effectively unbounded up to a hard cap (e.g. 50,000 rows),
    # streamed via a generator so we don't buffer the whole result in memory.
```

### 2.4 Frontend
`RowDrilldownModal.tsx`: remove the hardcoded `X-Fake-User-Id` / `X-Fake-Tenant-Id` / `X-Fake-Role` headers entirely — they are dead weight copied from test fixtures and have no business in a shipped component; the real `Authorization: Bearer <token>` is sufficient and the backend never reads those headers in production. Add real server-driven pagination controls (Prev/Next wired to `page`), a sortable header row (click column header → PATCH `sort_by`/`sort_dir` and refetch), and a loading skeleton per page change rather than a single top-level spinner.

**Definition of Done:** clicking a table row for a query filtered to `state = 'CA'` returns only CA rows from the real warehouse table, confirmed against a seeded fixture with mixed-state rows; sort-by-injection attempt (`sort_by=amount; DROP TABLE orders--`) is rejected with 422; an RLS integration test using a low-privilege Snowflake role fixture confirms restricted rows are absent from the response.

---

## Feature 3 — Executive Audio Briefing Player (Real)

### 3.1 Design (revised — no blob storage)
Reuse the TTS integration that already exists in this codebase (see `TTS_PROVIDER`/`deepgram_api_key` in `config.py` and the "STT/TTS: fix audio corruption, real mute/pause" commit already in `main`). Browser `SpeechSynthesis` becomes an explicit, clearly-labeled fallback for local dev only — never the default path in staging/production.

**Blob storage (S3/R2) is deliberately out of scope.** It was originally proposed purely as a caching optimization so the same day's narration isn't re-synthesized on every play. That optimization is achievable with **Redis alone** (already provisioned via Upstash) by caching the raw audio bytes, avoiding a new infra dependency and a new vendor account for a v1 feature. Durable blob storage is worth revisiting only if/when Redis caching proves insufficient at real scale (e.g., very large audio files or very long TTLs that bloat the Redis instance) — not a v1 requirement.

### 3.2 Backend — `backend/app/services/briefing_audio.py`

```python
from __future__ import annotations
import hashlib
from fastapi.responses import StreamingResponse
from app.config import Settings
from app.services.tts_client import synthesize_speech  # existing Deepgram TTS wrapper
from app.services.redis_client import redis_get_bytes, redis_set_bytes

AUDIO_CACHE_TTL_SECONDS = 86400  # 24h; same-day briefing narration is immutable once generated


async def get_briefing_audio_bytes(tenant_id, date: str, narrative_text: str, settings: Settings) -> tuple[bytes, str]:
    """Returns (audio_bytes, content_type). No file storage — cached in Redis, served directly."""
    cache_key = f"briefing_audio:{tenant_id}:{date}:{hashlib.sha256(narrative_text.encode()).hexdigest()[:12]}"
    cached = await redis_get_bytes(cache_key)
    if cached:
        return cached, "audio/mpeg"

    if settings.tts_provider == "fake":
        raise ApiError(ErrorCode.not_configured, status_code=501,
                        detail="Server-side TTS is not configured in this environment; use browser fallback.")

    audio_bytes, content_type = await synthesize_speech(narrative_text, voice=settings.briefing_voice)
    await redis_set_bytes(cache_key, audio_bytes, ttl_seconds=AUDIO_CACHE_TTL_SECONDS)
    return audio_bytes, content_type
```

`GET /api/briefing/audio` streams the response directly (`StreamingResponse(iter([audio_bytes]), media_type=content_type)`) with a `X-Audio-Provider: deepgram | browser_fallback` response header — the frontend branches explicitly on that header, it never silently guesses. No signed URLs, no blob keys, no new cloud account. First play of the day pays the TTS synthesis cost; every subsequent play within 24h is a Redis hit.

### 3.3 Frontend — real `<audio>` element, real waveform

```tsx
// Real progress and duration from the actual media element — not a fake timer.
const audioRef = useRef<HTMLAudioElement>(null);
const [progress, setProgress] = useState(0);

useEffect(() => {
  const el = audioRef.current;
  if (!el) return;
  const onTimeUpdate = () => setProgress((el.currentTime / (el.duration || 1)) * 100);
  el.addEventListener("timeupdate", onTimeUpdate);
  return () => el.removeEventListener("timeupdate", onTimeUpdate);
}, []);

const handleSpeedChange = (rate: number) => {
  if (audioRef.current) audioRef.current.playbackRate = rate; // native, supports 0.75/1/1.25/1.5 exactly as speced
};
```

Waveform: precompute peak data server-side once per briefing (e.g., via `audiowaveform` CLI run in the same job that generates the audio) and return a `peaks: number[]` array alongside `audio_url`; render real bars from `peaks`, not `Math.sin`.

**Definition of Done:** the progress bar position matches actual audio playback position within 100ms in a manual test; speed control literally changes audible pitch/rate of the real narration; in an environment with `TTS_PROVIDER=fake`, the UI visibly labels the playback as "Preview voice (browser)" rather than presenting it as the real briefing voice.

---

## Feature 4 — 1-Click Executive PDF Exporter (Real)

### 4.1 Design
Server-rendered PDF from a dedicated template — not `window.print()` on the live dashboard DOM. This guarantees consistent output regardless of the user's screen size, browser, or print driver, and lets the PDF include chart images (impossible with `window.print()` on canvas/SVG-heavy dashboards reliably).

### 4.2 Backend — `backend/app/services/pdf_exporter.py`

Use **WeasyPrint** (pure-Python, no headless-Chrome dependency, straightforward in the existing Docker image) rendering a Jinja2 HTML template, with chart PNGs pre-rendered via `plotly`'s static image export (`kaleido`) from the same `result_json` rows already stored on the turn — so the PDF's numbers are guaranteed to match what the exec saw on screen.

```python
from __future__ import annotations
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
import plotly.graph_objects as go

env = Environment(loader=FileSystemLoader("app/templates/pdf"))


def render_chart_png(chart_type: str, x: list, y: list, title: str) -> bytes:
    fig = go.Figure(go.Bar(x=x, y=y) if chart_type == "bar" else go.Scatter(x=x, y=y))
    fig.update_layout(title=title, template="plotly_white")
    return fig.to_image(format="png", width=800, height=400, scale=2)


async def generate_briefing_pdf(briefing: ExecutiveBriefingResponse, tenant_name: str) -> bytes:
    template = env.get_template("briefing_report.html.j2")
    html_str = template.render(briefing=briefing, tenant_name=tenant_name, generated_at=datetime.now(UTC))
    return HTML(string=html_str, base_url="app/templates/pdf").write_pdf()
```

`app/templates/pdf/briefing_report.html.j2` is a real, self-contained print-optimized HTML document (title page, KPI table, embedded chart `<img>` tags, narrative, appendix of generated SQL for audit trail) — the CSS classes referenced actually exist in this template, unlike the current `pdfExporter.ts`.

### 4.3 API + Frontend

```python
@router.get("/api/briefing/pdf")
async def export_briefing_pdf(claims: AuthClaims = Depends(get_current_user), ...) -> Response:
    pdf_bytes = await generate_briefing_pdf(briefing, tenant_name)
    return Response(content=pdf_bytes, media_type="application/pdf",
                     headers={"Content-Disposition": f'attachment; filename="voxquery-briefing-{date}.pdf"'})
```

```tsx
const exportToPDF = async () => {
  const res = await fetch(`${apiUrl}/api/briefing/pdf`, { headers: { Authorization: `Bearer ${token}` } });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = `voxquery-briefing-${date}.pdf`; a.click();
  URL.revokeObjectURL(url);
};
```

**Definition of Done:** the downloaded file is a real, valid PDF (verified in tests via `pdfplumber.open()` not throwing, and page count > 0); a `pdfplumber` text-extraction test asserts the KPI figures shown in the PDF match the `ExecutiveBriefingResponse` fixture used to generate it, byte-for-byte on the numbers.

---

## Feature 5 — Multi-Widget Grid Workspace (Real)

### 5.1 Schema — add to migration 007

```sql
CREATE TABLE IF NOT EXISTS pinned_widgets (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID NOT NULL REFERENCES tenants(id),
  user_id      UUID NOT NULL REFERENCES users(id),
  turn_id      UUID NOT NULL REFERENCES turns(turn_id),
  title        TEXT NOT NULL,
  layout_x     INTEGER NOT NULL DEFAULT 0,
  layout_y     INTEGER NOT NULL DEFAULT 0,
  layout_w     INTEGER NOT NULL DEFAULT 4,
  layout_h     INTEGER NOT NULL DEFAULT 3,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pinned_widgets_user ON pinned_widgets (tenant_id, user_id);
```

### 5.2 API — `backend/app/api/workspace.py`

```
GET    /api/workspace/widgets                 -> list current user's pins with joined turn data (chart_type, result rows)
POST   /api/workspace/widgets   {turn_id, title}
DELETE /api/workspace/widgets/{id}
PATCH  /api/workspace/widgets/{id}   {layout_x, layout_y, layout_w, layout_h}   -- debounced from the frontend, one call per drag/resize gesture end, not per pixel
```

Every route filters by `claims.tenant_id AND claims.user_id` — pins are private per user by default (a `shared: bool` column is a clean v2 extension for team dashboards, not required for parity).

### 5.3 Frontend — `react-grid-layout` with real chart rendering

```tsx
import GridLayout from "react-grid-layout";

<GridLayout className="layout" layout={widgets.map(toLayoutItem)} cols={12} rowHeight={60} width={1200}
  onLayoutChange={(layout) => debouncedPersistLayout(layout)}>
  {widgets.map((w) => (
    <div key={w.id}>
      <DataGlassPanel result={w.turnResult} compact />  {/* reuse the real chart component, not a row-count summary */}
    </div>
  ))}
</GridLayout>
```

`GET /api/workspace/widgets` returns the joined `turns.full_result` and `turns.chart_type` for each pin so `DataGlassPanel` renders the actual chart, matching what the executive originally pinned.

**Definition of Done:** pin a widget, refresh the browser, the widget and its exact grid position survive; a second browser tab for the same user shows the same layout after refetch; deleting a widget in tab A and refetching in tab B reflects the deletion (no client-only state).

---

## Feature 6 — Statistical Outlier Anomaly Detection (Real)

### 6.1 Design corrections
Two real bugs in the current implementation to fix, not just "wire up":
1. **Non-robust statistic.** Classic z-score (`(x - mean) / stddev`) is famously distorted by the very outliers it's trying to find — one extreme value inflates both `mean` and `stddev`, which can mask genuine anomalies. Use the **modified z-score** based on **median absolute deviation (MAD)**, the standard robust alternative (Iglewicz & Hoaglin, threshold 3.5 is the conventional default — not the mismatched 1.5/2.5σ currently floating between the PRD text and the code).
2. **No time-awareness.** Flat z-score across a time series flags legitimate seasonal spikes (e.g., predictable December revenue jump) as anomalies. If the result has a `role="time"` semantic column, detrend first.

### 6.2 Single source of truth — `backend/app/services/anomaly_detector.py`

```python
from __future__ import annotations
import statistics


def detect_outliers_mad(values: list[float], threshold: float = 3.5) -> list[dict]:
    """Modified z-score via median absolute deviation. Robust to the outliers it's detecting,
    unlike mean/stddev z-score."""
    if len(values) < 3:
        return []
    median = statistics.median(values)
    abs_deviations = [abs(v - median) for v in values]
    mad = statistics.median(abs_deviations)
    if mad == 0:
        return []
    results = []
    for idx, v in enumerate(values):
        modified_z = 0.6745 * (v - median) / mad
        if abs(modified_z) > threshold:
            results.append({
                "row_index": idx, "value": v, "modified_z_score": round(modified_z, 2),
                "severity": "critical" if abs(modified_z) > 5 else "warning",
            })
    return results


def detect_outliers_timeseries(values: list[float], window: int = 7, threshold: float = 3.5) -> list[dict]:
    """Rolling-median baseline detrending before MAD scoring, so seasonal/trend patterns
    aren't flagged as anomalies. window is in data-point units (e.g. 7 for daily data = weekly baseline)."""
    if len(values) < window * 2:
        return detect_outliers_mad(values, threshold)
    residuals = []
    for i, v in enumerate(values):
        lo = max(0, i - window)
        baseline = statistics.median(values[lo:i]) if i > 0 else v
        residuals.append(v - baseline)
    return detect_outliers_mad(residuals, threshold)
```

### 6.3 Compute once, serve to three consumers

Anomaly detection runs **once**, server-side, at the point a turn's result is finalized in `pipeline.py` — immediately before the turn is persisted (§0.2). The result is written to `turns.anomalies` and attached to the `result_ready` SSE event payload as a new field:

```python
class ResultReadyEvent(BaseModel):
    ...
    anomalies: list[dict] = Field(default_factory=list)  # new field
```

This single computation now feeds:
- **The chart itself** (frontend renders the glow using `anomalies` from the API response — delete the entire duplicate TypeScript z-score block in `DataGlassPanel.tsx`, ~20 lines removed).
- **The Memory Graph** insight nodes (§1.3, already reads `turn["anomalies"]`).
- **The Executive Briefing** `anomalies` section (`briefing.py` already has an `anomalies: list[BriefingAnomaly]` field — populate it from real per-tenant KPI anomaly detection instead of the current hardcoded "14% return rate increase" string in `briefing.py` line 91, which is exactly the same class of fake data this whole plan is eliminating).

**Definition of Done:** a `test_anomaly_detector.py` with a synthetic 90-day series containing a real December seasonal bump asserts `detect_outliers_timeseries` does NOT flag December, while a synthetic single-day spike unrelated to seasonality IS flagged; the frontend chart and the memory graph insight node for the same turn show the same anomaly (no divergence possible, since both read the same stored field).

---

## Feature 7 — Email Briefing Push Dispatcher (Real)

This is the most work, because "real" means an actually-running scheduler and an actual email send, not a function that returns `True`.

### 7.1 Schema additions — migration 007

```sql
ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS timezone TEXT NOT NULL DEFAULT 'UTC';

CREATE TABLE IF NOT EXISTS briefing_send_log (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id),
  tenant_id   UUID NOT NULL REFERENCES tenants(id),
  send_date   DATE NOT NULL,
  status      TEXT NOT NULL DEFAULT 'sent',   -- 'sent' | 'failed'
  error       TEXT,
  sent_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, send_date)                  -- idempotency: one send per user per day, enforced at the DB level
);
```

### 7.2 Real preferences persistence — `backend/app/services/preferences.py` (replaces the in-memory dict entirely)

```python
async def get_user_preferences(user_id: UUID, pool: asyncpg.Pool) -> UserPreferences:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM user_preferences WHERE user_id = $1", user_id)
    if row is None:
        return UserPreferences(user_id=user_id, email_briefing_enabled=False, email=None,
                                delivery_time="08:00", timezone="UTC")
    return UserPreferences(**dict(row))


async def update_user_preferences(user_id: UUID, pool: asyncpg.Pool, **fields) -> UserPreferences:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO user_preferences (user_id, email_briefing_enabled, email, delivery_time, timezone)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id) DO UPDATE SET
                email_briefing_enabled = EXCLUDED.email_briefing_enabled,
                email = EXCLUDED.email,
                delivery_time = EXCLUDED.delivery_time,
                timezone = EXCLUDED.timezone
            RETURNING *
            """,
            user_id, fields["email_briefing_enabled"], fields.get("email"),
            fields.get("delivery_time", "08:00"), fields.get("timezone", "UTC"),
        )
    return UserPreferences(**dict(row))
```

This is the single easiest, highest-leverage fix in the entire plan — a real migration (`006_v2_features.sql`) already created the table; it was simply never used.

### 7.3 Real email send — `backend/app/services/briefing_dispatcher.py` (Gmail SMTP, no third-party email vendor)

Uses Python's stdlib `smtplib`/`email` against Gmail's SMTP relay with an **App Password** (Google Account → Security → 2-Step Verification → App Passwords) — no new vendor account, no API key, no monthly send limit that matters at this scale (Gmail: 500/day on a personal account, 2,000/day on Workspace). This is real sending, not a mock — the only tradeoff versus a dedicated transactional-email provider is the absence of delivery analytics and a somewhat higher risk of spam-folder placement at scale, which is an acceptable tradeoff for this stage and explicitly flagged here for revisiting later, not hidden.

Run in a thread pool executor since `smtplib` is synchronous and must not block the async event loop:

```python
import smtplib
import ssl
import asyncio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.config import Settings


def _send_via_gmail_smtp(sender: str, app_password: str, to: str, subject: str, html_content: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.attach(MIMEText(html_content, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls(context=context)
        server.login(sender, app_password)
        server.sendmail(sender, to, msg.as_string())


async def dispatch_briefing_email(user_id: UUID, email: str, briefing: ExecutiveBriefingResponse,
                                    settings: Settings, pool: asyncpg.Pool, tenant_id: UUID) -> bool:
    if not settings.gmail_sender_address or not settings.gmail_app_password:
        raise ApiError(ErrorCode.not_configured, status_code=501,
                        detail="Gmail SMTP credentials are not configured in this environment.")

    html_content = render_briefing_email_html(briefing)  # Jinja2 template, includes unsubscribe link (§7.5)
    subject = f"Your VoxQuery Morning Briefing — {briefing.date}"

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, _send_via_gmail_smtp,
            settings.gmail_sender_address, settings.gmail_app_password, email, subject, html_content,
        )
        await _log_send(pool, user_id, tenant_id, status="sent")
        logger.info("briefing_email_sent user_id=%s", user_id)
        return True
    except Exception as exc:
        await _log_send(pool, user_id, tenant_id, status="failed", error=str(exc))
        logger.error("briefing_email_failed user_id=%s error=%s", user_id, exc)
        return False


async def _log_send(pool, user_id, tenant_id, *, status: str, error: str | None = None) -> None:
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO briefing_send_log (user_id, tenant_id, send_date, status, error) "
                "VALUES ($1, $2, CURRENT_DATE, $3, $4)",
                user_id, tenant_id, status, error,
            )
        except asyncpg.UniqueViolationError:
            pass  # already sent today — idempotency guard, not an error
```

New required config in `config.py`: `gmail_sender_address: str | None`, `gmail_app_password: str | None` (mark this field `SecretStr`, not plain `str`, so it never accidentally lands in logs or error messages), with a startup validation check mirroring the existing `stt_provider`/`deepgram_api_key` pattern already in the file (fail fast if `email_briefing_enabled` is reachable but Gmail credentials are unset — this must raise, not silently log-and-continue, per the plan's non-negotiable Rule against silent fake-success paths).

**Retry policy note:** unlike a provider API, Gmail SMTP has no built-in retry/queue semantics. If `server.sendmail` raises (e.g., transient network failure), the existing exponential-backoff retry (3 attempts) called from the scheduler around `dispatch_briefing_email` still applies — just wrapping a synchronous SMTP call instead of an HTTP call.

### 7.4 Real scheduler — APScheduler, in-process, Redis job store

Given the backend already runs as a long-lived Dockerized service (not serverless — confirmed by `backend/Dockerfile`) and already has Upstash Redis configured, use **APScheduler** with a Redis job store rather than introducing a new infra dependency like Celery+RabbitMQ:

```python
# backend/app/services/briefing_scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.redis import RedisJobStore
from zoneinfo import ZoneInfo
from datetime import datetime

scheduler = AsyncIOScheduler(jobstores={"default": RedisJobStore(jobs_key="voxquery:briefing_jobs")})


def start_briefing_scheduler(pool, settings):
    scheduler.add_job(check_and_dispatch_due_briefings, "interval", minutes=1,
                       args=[pool, settings], id="briefing_minute_check", replace_existing=True)
    scheduler.start()


async def check_and_dispatch_due_briefings(pool, settings):
    async with pool.acquire() as conn:
        due_users = await conn.fetch(
            """
            SELECT up.user_id, up.email, up.delivery_time, up.timezone, u.tenant_id
            FROM user_preferences up
            JOIN users u ON u.id = up.user_id
            WHERE up.email_briefing_enabled = true
              AND NOT EXISTS (
                  SELECT 1 FROM briefing_send_log bsl
                  WHERE bsl.user_id = up.user_id AND bsl.send_date = CURRENT_DATE
              )
            """
        )
    for row in due_users:
        tz = ZoneInfo(row["timezone"])
        local_now = datetime.now(tz)
        target_hour, target_minute = map(int, row["delivery_time"].split(":"))
        if local_now.hour == target_hour and local_now.minute == target_minute:
            briefing = await generate_morning_briefing(row["tenant_id"], settings, user_name="Executive")
            await dispatch_briefing_email(row["user_id"], row["email"], briefing, settings, pool, row["tenant_id"])
```

Started once in `main.py`'s FastAPI `lifespan` context, alongside the existing pool setup — one process, one scheduler instance, no separate worker deployment needed for v1. (If the backend later scales horizontally to multiple replicas, add a Redis-based distributed lock — `redis.set(key, val, nx=True, ex=55)` — around the minute-check job so only one replica dispatches; flagged here explicitly so it isn't a silent gap at scale.)

### 7.5 Manual trigger + unsubscribe endpoints

```python
@router.post("/api/briefing/send-now")
async def send_briefing_now(claims: AuthClaims = Depends(get_current_user), ...) -> StatusResponse:
    prefs = await get_user_preferences(claims.user_id, pool)
    if not prefs.email:
        raise ApiError(ErrorCode.invalid_request, status_code=422, detail="No email on file.")
    briefing = await generate_morning_briefing(claims.tenant_id, settings, user_name="Executive")
    success = await dispatch_briefing_email(claims.user_id, prefs.email, briefing, settings, pool, claims.tenant_id)
    return StatusResponse(status="sent" if success else "failed")


@router.get("/api/briefing/unsubscribe")
async def unsubscribe(token: str, pool=Depends(get_pool)) -> HTMLResponse:
    user_id = verify_unsubscribe_token(token)  # itsdangerous signed token, embedded in every email
    await update_user_preferences(user_id, pool, email_briefing_enabled=False)
    return HTMLResponse("<html><body>You've been unsubscribed from VoxQuery briefings.</body></html>")
```

**Definition of Done:** setting `delivery_time=08:00, timezone=America/New_York` for a test user and freezing system time to 08:00 ET triggers exactly one send, confirmed via a `briefing_send_log` row; running the scheduler check twice in the same minute (simulating a process restart) produces zero duplicate emails, confirmed by the unique constraint; the unsubscribe link in a sent email, when hit, flips `email_briefing_enabled` to false and a subsequent scheduler pass does not re-select that user.

---

## Feature 8 — Integration & E2E Testing Suite (Real)

The current branch's PRD claims this exists; none of the referenced files exist in the repo. Build it for real.

### 8.1 Add the dependency and config

```bash
cd frontend && npm install -D @playwright/test && npx playwright install --with-deps chromium
```

`frontend/playwright.config.ts`:

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
  },
  use: { baseURL: "http://localhost:3000", trace: "on-first-retry" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
```

`frontend/vitest.config.ts` — genuinely exclude the e2e directory (the current file does not do this despite the PR claiming it does):

```ts
export default defineConfig({
  test: { environment: "jsdom", globals: true, setupFiles: ["./vitest.setup.ts"], exclude: ["e2e/**", "node_modules/**"] },
});
```

### 8.2 Real spec file — `frontend/e2e/wow-features.spec.ts`

Each test seeds real backend fixtures via a test-only API (`/api/test/seed`, enabled only when `ENVIRONMENT=test`) rather than clicking through the live voice pipeline for setup, then asserts real, feature-specific outcomes:

```ts
import { test, expect } from "@playwright/test";
import { seedSessionWithTurns, seedTenantUser } from "./fixtures";

test("pinned widget survives a full page reload", async ({ page }) => {
  const { turnId } = await seedSessionWithTurns({ turnCount: 1 });
  await page.goto("/");
  await page.getByTitle("Pin to Workspace").click();
  await expect(page.getByText("Pinned Widget")).toBeVisible();
  await page.reload();
  await expect(page.getByText("Pinned Widget")).toBeVisible(); // fails today — nothing persists
});

test("drilldown modal shows rows matching the turn's actual filter", async ({ page }) => {
  const { turnId } = await seedSessionWithTurns({ filter: { state: "CA" } });
  await page.goto("/");
  await page.getByTitle("Drilldown Raw Data").click();
  const rows = page.locator("[data-testid=drilldown-row]");
  await expect(rows.first()).toBeVisible();
  await expect(page.locator("[data-testid=drilldown-row-state]").first()).toHaveText("CA"); // fails today — hardcoded fake rows ignore any filter
});

test("PDF export downloads a real, non-empty PDF", async ({ page }) => {
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByTitle("Export to PDF").click(),
  ]);
  const path = await download.path();
  expect(path).toBeTruthy();
});

test("memory graph reflects a newly completed turn without manual refresh", async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder("Ask VoxQuery...").fill("Show total revenue by region");
  await page.getByRole("button", { name: "Submit" }).click();
  await expect(page.getByText(/Show total revenue by region/)).toBeVisible({ timeout: 15000 }); // graph node appears live
});
```

### 8.3 CI wiring — `.github/workflows/e2e.yml`

```yaml
jobs:
  e2e:
    runs-on: ubuntu-latest
    services:
      postgres: { image: postgres:16, env: { POSTGRES_PASSWORD: test }, ports: ["5432:5432"] }
      redis: { image: redis:7, ports: ["6379:6379"] }
    steps:
      - uses: actions/checkout@v4
      - run: docker compose -f docker-compose.test.yml up -d backend
      - run: cd frontend && npm ci && npx playwright install --with-deps chromium
      - run: cd frontend && npx playwright test
      - uses: actions/upload-artifact@v4
        if: failure()
        with: { name: playwright-report, path: frontend/playwright-report/ }
```

**Definition of Done:** `npx playwright test` runs locally and in CI against a real ephemeral Postgres + Redis + backend stack (not mocks), and — critically — every one of the four specs above should be written to **fail against the current `voxquery-wow-features` HEAD** before any of Phases 0–7 land, proving the suite actually exercises real behavior rather than rubber-stamping mocks. That "red before green" step is itself part of the acceptance criteria.

---

## Cross-Cutting Infrastructure Checklist

| Requirement | Source | Action |
|---|---|---|
| Postgres migration runner | existing `db/migrations/00X_*.sql` pattern | Add `007_wow_features_v2.sql` combining all schema changes above |
| Redis | already configured (`UPSTASH_REDIS_URL`) | Reuse for graph cache, TTS cache, scheduler job store |
| Snowflake connection pooling | already exists per git history | Reuse for drilldown; no new DB client needed |
| Deepgram TTS | already configured (`TTS_PROVIDER`, `deepgram_api_key`) | Reuse for audio briefing; add `briefing_voice` setting |
| ~~Blob storage (S3/R2)~~ | **descoped** | Not used. Audio is streamed directly from Deepgram TTS and cached as raw bytes in Redis (§3.2) — no new cloud storage account needed. Revisit only if Redis caching proves insufficient at real scale. |
| Gmail SMTP (email) | **new, no vendor account** | Add `gmail_sender_address`, `gmail_app_password` (`SecretStr`) to `config.py`; requires a Google Account App Password (Security → 2-Step Verification → App Passwords), not a new service signup. Limits: 500 sends/day (personal) / 2,000/day (Workspace) — ample for this scale. No delivery analytics; revisit a dedicated provider (e.g. Resend/SES) if send volume or deliverability requirements grow. |
| WeasyPrint + system deps (Pango/Cairo) | **new** | Add `RUN apt-get install -y libpango-1.0-0 libpangocairo-1.0-0` to `backend/Dockerfile` |
| `sqlglot` | **new** | Add to `pyproject.toml`; used for SQL provenance parsing (§1.2) — pure Python, no system deps |
| `react-flow`, `dagre`, `react-grid-layout` | **new** | Add to `frontend/package.json` |
| `@playwright/test` | **new** | Add as devDependency; requires `npx playwright install` in CI image |
| APScheduler | **new** | Add to `pyproject.toml`; started in FastAPI `lifespan`, not a separate deployment |
| Distributed lock for scheduler (multi-replica safety) | flagged in §7.4 | Implement before horizontally scaling the backend past 1 replica |

## Security & Multi-Tenancy Checklist (apply to every new endpoint)

- [ ] `tenant_id` is always derived from `AuthClaims`, never accepted from the client body/query string.
- [ ] Every new table has a `tenant_id` column and every query filters on it.
- [ ] Drilldown SQL uses parameterized queries exclusively; `sort_by`/table names go through an allowlist derived from live schema introspection, never raw string concatenation.
- [ ] Snowflake drilldown queries execute under the requesting user's actual `snowflake_role` (already present in `AuthClaims`) so warehouse-side RLS is the real enforcement boundary, not an app-level filter.
- [ ] Unsubscribe tokens are signed (`itsdangerous`) and single-purpose (can only disable email, cannot be replayed to modify other preferences).
- [ ] `X-Fake-*` headers are stripped from any component that ships to production; confirmed by a lint rule or a pre-commit grep check (`grep -r "X-Fake" frontend/app --include=*.tsx | grep -v test` should return nothing).

## Rollout Sequencing

1. **Phase 0** (blocking): turn/session Postgres persistence.
2. **Phase 1** (quick, high-leverage, mostly independent): DB-backed preferences (§7.2); server-side robust anomaly detection (§6) — unlocks better versions of Features 1, 3, and 7's briefing anomalies for free.
3. **Phase 2** (depends on Phase 0): real Memory Graph (§1); real Drilldown (§2).
4. **Phase 3**: real email scheduler + Gmail SMTP dispatch (§7.3–7.5); real PDF export (§4).
5. **Phase 4**: real audio TTS integration (§3); Workspace persistence + `react-grid-layout` (§5).
6. **Phase 5**: Playwright E2E suite (§8), written red-before-green against Phases 0–4, wired into CI.

Each phase should ship behind its own PR with the Definition of Done from its section as the PR's acceptance checklist — not bundled into one PR the way the original branch was, which is part of how six fake features passed review as "done."
