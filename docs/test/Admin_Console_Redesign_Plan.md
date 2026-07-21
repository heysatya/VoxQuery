# VoxQuery Admin Console — World-Class Redesign Plan

## 1. Situation Assessment

### ✅ What Is Already Working (Don't Break)
- **Backend ARCH-1 is FULLY WIRED.** `rewrite_query_node` in `graph.py` (lines 153–174) already reads `tenant_glossary` from the database *per tenant* before instantiating `QueryRewriter(metric_synonyms=..., table_synonyms=...)`. The glossary IS active in the live pipeline — every user query is already run through tenant-specific synonyms. This is correctly implemented.
- **The Admin API** (`GET /api/admin/glossary` and `POST /api/admin/glossary`) works correctly — reads and upserts into `tenant_glossary` table.

### ❌ What Is Broken / Missing

#### A. The Glossary UX is Incomprehensible
The current UI treats the Tenant Glossary as if it's a raw config editor for engineers. Problems:
1. **The entire feature's PURPOSE is invisible.** A new admin has no idea why this exists.
2. **"Metric Synonyms" and "Table Synonyms" are jargon.** Nobody understands the difference without a manual.
3. **"Tenant ID"** is a raw DB UUID / string — admins don't know what to type.
4. **There is zero feedback loop.** After saving, there's no indication that the glossary was activated in the next query.
5. **No example/guidance.** No placeholder examples, no help text, no documentation inline.

#### B. No Visibility Into Glossary Impact
- No way to see which synonyms have been "hit" in actual queries.
- No preview of what the rewrite would look like before saving.
- No activity log ("This glossary was used 47 times in the last 7 days").

#### C. Admin Console Missing Critical Sections
Based on best-in-class data tools (Metabase, Tableau, dbt Cloud, Hex):
- **No Tenant/Workspace Management panel** — can't see or manage which tenants are onboarded
- **No Query Audit Log** — no way to review all queries, not just thumbs-down ones
- **No Schema Sync Status** — can't see if the Snowflake schema index is stale
- **No System Health Panel** — pipeline status, avg latency, error rate

#### D. Feedback Review Panel Is Also Raw
- Raw tenant UUIDs displayed — no human-readable tenant names
- "Investigate" button does nothing
- No filtering, no sorting, no action to resolve/dismiss

---

## 2. Competitive Reference

| Product | Relevant Pattern |
|---|---|
| **dbt Cloud** | Business terms UI: maps "business name" → SQL column, with a searchable term browser and usage count. Plain English labels, not "metric_synonyms". |
| **Looker** | LookML dimension/measure UI: shows field name, description, SQL, and "how often this was used". |
| **Metabase Admin** | Plain-English segment management: "When users say X, use column Y". Zero jargon, every form has a description. |
| **Hex Workspace** | Tenant management: shows last active, # queries, tier — not raw UUIDs. |
| **Grafana** | System health: top-of-page tiles with status indicators before any drill-down. |

---

## 3. Proposed Admin Console Information Architecture

### 3.1 Navigation (Sidebar — Restructured)

```
VoxAdmin
├── 🏠 Overview          [NEW] — Health tiles + recent activity feed
├── 📖 Business Vocabulary [RENAMED + REDESIGNED] — was "Tenant Glossary"
├── 🏢 Workspaces        [NEW] — Tenant list + onboarding status
├── 🔍 Query History     [NEW] — All queries, filterable + sortable
├── 👎 Quality Review    [RENAMED] — was "Feedback Review"
└── 📊 Model Analytics   [PLACEHOLDER → build out]
```

### 3.2 Business Vocabulary (renamed from "Tenant Glossary")

**Concept:** This is the AI's dictionary for your company. Instead of "metric_synonyms" and "table_synonyms", we speak in plain English:

- **"Business Terms"** → things users SAY (e.g., "revenue", "customers")
- **"What it maps to"** → what the AI should ACTUALLY query (e.g., "total_sales", "accounts")
- **"Data type"** → whether it's a *measure* (a number you aggregate) or a *dimension* (a category you filter by) — replaces the technical metric/table distinction

**Layout:**
- Top: "How the AI Understands Your Business" — a plain English explanation card with an animated example (user says "revenue" → AI queries "total_sales")
- Right rail: A **live preview** panel: "What happens when a user says…" input → shows the rewritten query
- Main table: Terms list with: Term | Maps To | Type (Measure/Dimension) | Times Used | Last Hit | Actions

### 3.3 Overview (new)
- 4 status tiles: Queries Today / Avg Latency / Error Rate / Pending Quality Reviews
- Recent Activity feed (last 10 queries across tenants)
- Schema freshness indicator

---

## 4. The Coding Agent Prompt

Below is a copy-paste ready prompt for a coding agent to implement this plan.

---

## 5. Open Questions for Human Review
1. **Tenant Display Names**: The DB has `tenant_id` UUIDs. Do you have a `tenants` table with human-readable names? If so, we should JOIN on it everywhere. If not, we should add a `display_name` column.
2. **Live Preview**: Should the "preview rewrite" feature call the actual backend `/api/rewrite` endpoint (would need a new endpoint), or do a client-side simulation?
3. **Query History**: How long should query history be retained? Is there a data privacy concern with showing full queries in the admin panel?
4. **Schema Sync Status**: Is `scripts/sync_schema.py` run manually or on a schedule? Should the admin panel show its last run time?
