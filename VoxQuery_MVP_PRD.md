

**VoxQuery**

Voice-Driven Data Analyst

*MVP Product Requirements Document*

| Version | 1.0 — MVP |
| :---- | :---- |
| **Status** | Draft — For Stakeholder Review |
| **Date** | May 2026 |
| **Target** | Enterprise (500+ employees) |
| **Warehouse** | Snowflake (v1) |

# **1\. Purpose & Problem Statement**

Voxquery solves a single, well-defined problem: enterprise executives need answers from their data warehouse but have no practical path to get them without involving a data analyst or learning SQL.

| *Primary value proposition: An executive asks a question in plain English, receives a chart and a spoken summary — without touching SQL, a BI tool, or a data analyst. The product removes the human intermediary from ad-hoc analytical questions.* |
| :---- |

The suppressed demand is significant. Snowflake-backed enterprise warehouses are accessed by less than 5% of the workforce — primarily data teams and power users. The remaining 95% (sales leaders, ops directors, finance VPs) have data access in principle but no practical workflow to query it. Voxquery converts that latent demand into active, self-serve insight.

# **2\. MVP Goal & Success Criteria**

The MVP exists to validate one hypothesis: a non-technical executive can ask a question in plain language and receive a correct, useful answer from a live Snowflake warehouse within 60 seconds — with no SQL, no BI training, and no analyst involved.

### **Success criteria for MVP launch**

| Metric | Target | How measured |
| :---- | :---- | :---- |
| Query-to-answer latency (excluding Snowflake cold-start) | < 8 seconds P95 | P50 and P95 measured across pilot sessions, split by pipeline stage in Langfuse |
| Query-to-answer latency (including Snowflake cold-start) | < 60 seconds P90 | P90 across pilot sessions — Snowflake warehouse pre-warming is a deployment recommendation, not a product requirement |
| SQL accuracy rate | \> 85% correct on first attempt | Human review of pilot queries |
| Clarification loop trigger rate | \< 30% of queries | Logged per session |
| Pilot user satisfaction | \>= 4/5 post-session rating | In-product feedback prompt |
| Pilot customer count | 1 signed enterprise pilot | Before public launch |

# **3\. MVP Scope — In vs. Out**

Scope decisions are intentional. Everything marked out-of-scope is a post-MVP feature, not a deprioritised one. These decisions exist to reach a reference customer faster.

### **In scope for MVP**

* Voice input (Deepgram streaming STT) and text input fallback

* Schema-aware RAG over Snowflake metadata and table descriptions

* LLM-based SQL generation (Claude claude-sonnet-4-20250514) with sqlglot validation

* Read-only enforcement (CQRS): only SELECT statements are permitted; INSERT, UPDATE, DELETE, CREATE, ALTER, and DROP are rejected at the sqlglot AST validation layer before any Snowflake connection is opened — this is the command/query segregation boundary

* Snowflake query execution with row-limit enforcement

* Clarification prompt when query intent is ambiguous

* Chart selector — bar, line, table, and stat card — chosen by result shape

* TTS voice summary (OpenAI tts-1) of the query result

* Single-session conversation memory (context within one browser session)

* Proactive question suggestions: after each result renders, surface 2–3 contextually relevant follow-up questions generated from the result shape, schema context, and user role — "tells you what you should be asking"

* Single-tenant Snowflake connection per workspace

* SSO authentication via OAuth (Auth0 or Clerk)

* Web application — Next.js, desktop-first

* Row-level security: VoxQuery passes the authenticated user's Snowflake role to the connector at query execution time — users receive only data their existing Snowflake permissions permit; no shadow permission layer is built inside VoxQuery

### **Out of scope for MVP**

* Multi-warehouse support (BigQuery, Redshift, Postgres) — out of scope for MVP execution, but the warehouse connector must sit behind a WarehouseConnector abstract interface in the backend so Snowflake is a pluggable implementation, not hardcoded

* Cross-session conversation memory and history search

* Scheduled reports or data alerts — out of scope for MVP execution. The post-MVP roadmap includes Morning Briefing Mode (V2): scheduled background queries run nightly against key executive metrics, z-score and week-over-week anomaly detection flags outliers, and the system proactively surfaces a priority-ranked briefing at session open ("Good morning. Three things before your 9 AM: EMEA revenue dropped 23% WoW, conversion rate fell below 30-day avg, pipeline is 118% of target"). The backend pipeline (scheduled queries + anomaly detection) must be designed at MVP so that Morning Briefing is an additive feature, not a rewrite — specifically: (a) query execution must be callable programmatically, not only via user request, and (b) the result store (turns table) must support a source column distinguishing user-initiated vs scheduled runs.


* Mobile native app (iOS / Android)

* Custom chart theming or branded exports

* SOC 2 certification (roadmap post-Series A)

* Self-hosted / VPC deployment option

* Admin dashboard for usage analytics

# **4\. User Stories & Acceptance Criteria**

## **4.1 Voice Input**

| *As an executive, I want to speak my question aloud so I can get an answer without typing SQL or navigating a dashboard.* |
| :---- |

### **Acceptance criteria**

* Microphone permission prompt appears on first use with a clear explanation

* Streaming transcription begins within 500ms of speech detected

* Transcript is displayed in real time as the user speaks

* User can edit the transcript before submitting

* Text input is available as a full fallback — same pipeline, same response

* Works in Chrome, Safari, Edge (latest two major versions)

## **4.2 Clarification Loop**

| *As an executive, when my question is ambiguous, I want to be asked a single clarifying question — not receive a wrong answer or an error.* |
| :---- |

### **Acceptance criteria**

* Clarification is triggered when the SQL generator confidence score falls below threshold

* Exactly one clarifying question is shown — never multiple at once

* Options are presented as tappable buttons, not a free-text field

* Selecting an option immediately resubmits the query with the refined intent

* The clarification exchange is included in conversation context for subsequent turns

* Clarification is skipped if confidence is high — it must not be shown on every query

* After each result, a single-tap thumbs-up / thumbs-down is shown inline; negative feedback logs the turn (input, generated SQL, result) for confidence threshold tuning and is flagged in Langfuse — this is the primary mechanism for calibrating the 0.65 clarification threshold post-launch

## **4.3 Conversation Memory**

| *As an executive, I want to ask follow-up questions that reference my previous query so I can drill into data naturally, the way I'd talk to an analyst.* |
| :---- |

### **Acceptance criteria**

* Subsequent turns within a session carry the prior SQL context

* Follow-ups like “now filter that by Q3” resolve correctly without restating the base question

* Memory is scoped to the current browser session (in-memory store)

* Starting a new conversation clears memory — the user is informed of this

* Memory context is truncated intelligently if it exceeds token limits (last N turns kept)

## **4.4 Schema-Aware RAG**

| *As the system, I must ground every SQL generation request in the actual schema of the customer's Snowflake warehouse to prevent hallucinated table or column names.* |
| :---- |

### **Acceptance criteria**

* Schema is ingested via Snowflake INFORMATION\_SCHEMA on workspace setup

* Table descriptions, column names, data types, and a business glossary are embedded and stored in pgvector; during admin onboarding, the admin explicitly maps executive-facing terms (e.g. "revenue", "bookings", "churn") to actual column names — this glossary is embedded alongside schema chunks and co-retrieved, resolving the vocabulary mismatch between non-technical executives and developer-named columns (Domain-Driven Design vocabulary layer)

* Schema metadata is processed and embedded per table individually, not bulk-ingested as a single document — this preserves retrieval precision when similar column names exist across tables (e.g. orders.total vs invoices.total)

* Admin setup wizard prompts for explicit declaration of inter-table relationships (join paths, business keys) where FK/PK constraints are absent in the schema — these are stored as relationship context chunks and injected into the SQL generation prompt; production warehouses routinely carry constraints "in developers' minds" rather than in the schema definition

* If the customer has an existing Snowflake QUERY_HISTORY, the top-200 most-executed queries filtered by the relevant warehouse roles are ingested at onboarding, embedded, and used as retrieval context alongside schema chunks — this bootstraps multi-table join accuracy for patterns specific to that warehouse

* Top-5 most semantically relevant schema chunks are retrieved per query

* Sample queries (admin-provided) are also embedded and retrieved when relevant

* RAG retrieval completes in under 500ms P90

* Schema is re-indexed on demand via admin trigger (not automatic in MVP)

## **4.5 SQL Generator, Validator & Executor**

| *As the system, I must never execute a SQL query that has not passed validation, and must never allow a query without a row limit on large tables.* |
| :---- |

### **Acceptance criteria**

* SQL is generated by Claude claude-sonnet-4-20250514 using retrieved schema context and conversation history

* Every generated SQL statement passes through sqlglot parse validation before execution

* sqlglot AST inspection rejects any statement whose root node is not a SELECT — DDL (CREATE, ALTER, DROP) and DML (INSERT, UPDATE, DELETE) are blocked before Snowflake connection is opened; rejection returns a structured user-facing error, not a raw exception

* Queries without an explicit LIMIT are automatically capped at 10,000 rows

* Queries referencing non-existent tables or columns are rejected with a user-facing error

* On validation failure, the system retries once with an error correction prompt

* The generated SQL is displayed to the user (collapsed by default, expandable)

* Snowflake query execution timeout is set at 30 seconds

* Post-execution result deduplication: if the result set contains duplicate rows attributable to implicit cross-joins (detectable via row-count anomaly vs expected cardinality), the system flags this to the user and offers to re-run with DISTINCT — it does not silently return inflated numbers

## **4.6 Chart Selector & Output**

| *As an executive, I want the system to automatically choose the right chart type for my result so I don't have to configure visualisations myself.* |
| :---- |

### **Acceptance criteria**

* Result shape analysis determines chart type: time series → line, categorical comparison → bar, single number → stat card, multi-column → table

* When the system auto-selects a chart type, a one-line rationale is shown beneath the chart (e.g. "Showing as line chart — time series detected on date column"); user can override via the existing selector

* Charts render using Recharts with default styling — no custom theme in MVP

* Stat card shows value, label, and percentage change if prior period data is available

* Table view is the fallback for any result shape that does not match the above rules

* Chart type can be manually overridden by the user via a selector

* Result is downloadable as CSV — one click, no configuration

## **4.7 TTS Voice Summary**

| *As an executive, I want to hear a brief spoken summary of the result so I can get the key insight without reading a chart.* |
| :---- |

### **Acceptance criteria**

* A 1-3 sentence spoken summary is generated for every query result

* Audio plays automatically after the chart renders (with a visible mute toggle)

* TTS uses OpenAI tts-1 — alloy voice at MVP, no voice selection

* Audio is generated in parallel with chart rendering to minimise perceived latency

* If TTS generation fails, the text summary is shown silently — no error is surfaced

* STT provider is Deepgram at MVP; if transcription accuracy on domain-specific vocabulary (product names, internal metrics) falls below 90% in pilot, evaluate ElevenLabs STT (higher cost, better domain accuracy) or Microsoft VibeVoice (open-source, self-hostable: https://github.com/microsoft/VibeVoice) as a drop-in replacement — the STT interface must be abstracted to allow this swap without pipeline changes

## **4.8 Query Confidence & Transparency**

| *As an executive, I want to know how confident VoxQuery is in its answer so I can decide whether to act on it immediately or verify with my data team.* |
| :---- |

### **Acceptance criteria**

* Every query result displays a confidence indicator (High / Medium / Low) derived from: RAG retrieval score, sqlglot validation pass/fail on first attempt, and result row count plausibility check

* High confidence (≥ 0.80): result displayed immediately with no friction

* Medium confidence (0.65–0.79): a single-sentence caveat is shown inline: "I'm moderately confident — the query joined tables I'm less familiar with. Review the SQL before actioning."

* Low confidence (< 0.65): clarification loop triggers (existing Section 4.2 behaviour)

* The generated SQL is always visible via an expandable "View SQL" toggle — collapsed by default, one click to expand

* Confidence score and SQL are both logged per turn in the turns table for calibration review in Langfuse

* Confidence UI must not be shown as a numerical percentage — only the three-tier label (High / Medium / Low) is shown to the executive; the raw score is internal only

## **4.9 Data Storytelling Engine**

| *As an executive, I want the spoken summary to tell me the story behind the numbers — not just read them out — so I can make a decision without further analysis.* |
| :---- |

### **Acceptance criteria**

* The TTS summary prompt instructs the LLM to produce a narrative with: (1) the headline number, (2) the primary driver if detectable from the result set, and (3) a directional implication if inferrable ("Revenue grew 15% QoQ, driven by Enterprise which saw a 23% uplift. SMB declined 8% — potentially pricing-sensitive.")

* The narrative must not exceed 3 sentences — enforced by the prompt, not post-processing

* If the result set is a single number (stat card), the summary states the value, its change vs the prior period if available, and whether it is above or below a relevant benchmark if that benchmark was part of the retrieved schema context

* The storytelling prompt is a distinct LLM call from the SQL generation call — it receives only the sanitised result shape (not raw rows) and the user's original question, not the full schema context

* Storytelling LLM call must complete within 2 seconds P95 — it runs in parallel with chart rendering (existing Section 4.7 behaviour)

# **5\. High-Level Architecture**

Three layers: client, backend pipeline, and data layer. The client is thin — it handles audio capture, displays results, and plays audio. All intelligence lives in the backend.

### **Component overview**

| Layer | Component | Responsibility |
| :---- | :---- | :---- |
| Client | Next.js 14 (TypeScript) | Audio capture, transcript display, chart render, TTS playback |
| Client | Recharts | Bar, line, table, stat card visualisation |
| Backend | FastAPI (Python 3.12) | Async API gateway, session management, pipeline orchestration |
| Backend | Deepgram Streaming STT | Real-time speech-to-text transcription |
| Backend | LiveKit (evaluate for v1.1) | Voice agent state management and WebSocket session orchestration — recommended for MVP if voice agent complexity grows; use HTTP/WebSocket endpoints for structured responses at MVP, evaluate LiveKit cutover before pilot scale-up |
| Backend | Claude claude-sonnet-4-20250514 | SQL generation, clarification, summary generation |
| Backend | sqlglot | SQL validation, dialect normalisation, safety enforcement |
| Backend | OpenAI tts-1 | Voice summary generation |
| Data | Postgres 16 \+ pgvector | Users, sessions, turns, schema embeddings |
| Data | Upstash Redis | Session state, rate limiting, query caching |
| Data | Snowflake (customer) | Live warehouse query execution |
| Backend (V2) | Executive Memory Graph | Persistent per-user knowledge store: preferred metrics, typical time ranges, departments overseen, past questions — enables "Last week you asked about EMEA. Want an update?" and learns that "how are we doing" means ARR for a specific CEO. Built over the existing turns + conversations tables at V2 — no additional infra required at MVP. |

| *Architecture principle: the LLM never touches Snowflake directly. All SQL passes through sqlglot validation before execution. This is the trust layer — it catches hallucinated column names, unsafe patterns, and missing row limits. Additionally: raw Snowflake result rows are never passed to the LLM. Only schema metadata, glossary terms, and query intent travel to the LLM API boundary. The LLM generates SQL and narrative summaries — it never sees the actual data values returned by the warehouse. This boundary is the primary confidentiality guarantee for enterprise pilots.* |
| :---- |

# **6\. MVP Data Model**

Six tables cover the full MVP. No premature normalisation — keep it flat and fast to iterate on.

### **Table: tenants**

| Column | Type | Notes |
| :---- | :---- | :---- |
| id | UUID PK | Auto-generated |
| name | TEXT | Organisation name |
| snowflake\_dsn | TEXT | Encrypted Snowflake connection string |
| created\_at | TIMESTAMPTZ | Auto set on insert |

### **Table: users**

| Column | Type | Notes |
| :---- | :---- | :---- |
| id | UUID PK |  |
| tenant\_id | UUID FK | References tenants.id |
| email | TEXT UNIQUE | Identity from SSO provider |
| role | TEXT | viewer | admin |
| created\_at | TIMESTAMPTZ |  |

### **Table: conversations**

| Column | Type | Notes |
| :---- | :---- | :---- |
| id | UUID PK |  |
| user\_id | UUID FK | References users.id |
| title | TEXT | Auto-generated from first query |
| created\_at | TIMESTAMPTZ |  |

### **Table: turns**

| Column | Type | Notes |
| :---- | :---- | :---- |
| id | UUID PK |  |
| conversation\_id | UUID FK | References conversations.id |
| user\_input | TEXT | Raw transcript or typed query |
| generated\_sql | TEXT | Final validated SQL |
| result\_json | JSONB | Raw Snowflake query result |
| chart\_type | TEXT | bar | line | table | stat |
| tts\_url | TEXT | Cached audio URL (S3 / object storage) |
| latency\_ms | INT | End-to-end response time |
| created\_at | TIMESTAMPTZ |  |

### **Table: schema\_chunks**

| Column | Type | Notes |
| :---- | :---- | :---- |
| id | UUID PK |  |
| tenant\_id | UUID FK | References tenants.id |
| content | TEXT | Table or column description chunk |
| embedding | VECTOR(1536) | pgvector — text-embedding-3-small |
| source\_ref | TEXT | e.g. orders.total\_revenue |
| created\_at | TIMESTAMPTZ |  |

### **Table: clarifications**

| Column | Type | Notes |
| :---- | :---- | :---- |
| id | UUID PK |  |
| turn\_id | UUID FK | References turns.id |
| prompt\_sent | TEXT | Clarifying question shown to user |
| user\_choice | TEXT | Option selected by user |
| created\_at | TIMESTAMPTZ |  |

# **7\. Tech Stack**

Optimised for rapid development, low operational overhead, and easy deployment. No Kubernetes at MVP.

| Area | Choice | Rationale |
| :---- | :---- | :---- |
| Frontend | Next.js 14 \+ TypeScript | App Router, SSR, one-click Vercel deploy |
| UI / Charts | Tailwind CSS \+ Recharts | No design system overhead at MVP |
| Backend | Python 3.12 \+ FastAPI | Async, strong AI/ML ecosystem |
| LLM | Claude claude-sonnet-4-20250514 (Anthropic) | Best-in-class SQL generation & schema reasoning |
| STT | Deepgram (streaming) | Lower latency than Whisper API |
| TTS | OpenAI tts-1 (alloy) | Fastest, lowest cost, sufficient quality |
| SQL validation | sqlglot | Pure Python, dialect-aware, no dependencies |
| Embeddings | text-embedding-3-small | Low cost, strong accuracy |
| Primary DB | Postgres 16 (Supabase) | Managed, pgvector included, no DevOps |
| Vector store | pgvector (on Postgres) | No extra infra at MVP — upgrade to Qdrant later |
| Cache / sessions | Upstash Redis | Serverless, pay-per-request |
| Auth | Clerk or Auth0 | SSO out of the box, no custom auth code |
| Hosting (FE) | Vercel | Git-push deploy, global CDN |
| Hosting (BE) | Railway | Managed containers, generous free tier |
| Observability | Langfuse | Purpose-built LLM tracing, open source |
| Warehouse | Snowflake (customer-provided) | snowflake-connector-python |

# **8\. Non-Functional Requirements**

### **Performance**

* End-to-end query latency: \< 60 seconds P90 (including Snowflake execution)

* STT transcription start: \< 500ms from speech detected

* RAG retrieval: \< 500ms P90

* Snowflake query execution target: < 10 seconds P50 on pre-warmed warehouses with row limits applied; cache hits (Redis): < 200ms

* Contextual result caching: identical normalised SQL + tenant_id combinations are cached in Upstash Redis (TTL configurable per tenant, default 5 minutes) — cache hit bypasses Snowflake execution entirely; cache key is a hash of normalised SQL post-sqlglot formatting

* TTS audio playback begins: \< 3 seconds after chart renders

### **Security**

* All data in transit encrypted via TLS 1.3

* Snowflake DSN stored encrypted at rest (AES-256)

* No raw query results cached beyond the current session

* SQL validation layer prevents injection — no raw user input reaches Snowflake

* JWT tokens expire after 8 hours; refresh tokens rotated on use

* Data confidentiality: raw Snowflake query result rows are never transmitted to third-party LLM APIs; only schema metadata, business glossary terms, and sanitised query intent are sent to Claude — result data stays within the customer's execution boundary; this must be enforced at the pipeline orchestration layer and verified during pilot onboarding

* The SQL generation prompt interface must be model-agnostic: no Claude-specific API constructs (e.g. system prompt formatting, tool use schema) are hardcoded outside of a single adapter class — this enables swap-in of a private SLM (e.g. fine-tuned Mistral/LLaMA deployed on-prem) for customers with strict data residency or InfoSec requirements without a pipeline rewrite

### **Reliability**

* Target uptime: 99.5% (SLA commitment post-pilot)

* Snowflake query timeout: 30 seconds — graceful error returned

* TTS failure: silent degradation — text summary shown, no error surfaced

* LLM API failure: retry once, then return a structured error with suggested rephrasing

### **Observability**

* Every query turn logged with latency, SQL generated, chart type, and validation outcome

* LLM calls traced via Langfuse — token counts, prompt versions, latency per stage

* Clarification trigger rate tracked per tenant — alerts if \> 50% of queries for a tenant

# **9\. Query Pipeline — Step by Step**

Every query follows this sequence. The orchestrator manages state and retries between stages.

1. Audio capture (Deepgram WebSocket) or text input received

2. Transcript embedded via text-embedding-3-small

3. Top-5 schema chunks retrieved from pgvector by cosine similarity

4. Claude claude-sonnet-4-20250514 generates SQL with schema context \+ conversation history injected

5. sqlglot validates SQL — on failure, retry once with error correction prompt

5a. AST-level write check: if the statement root is not SELECT, reject immediately with user-facing error — pipeline halts here

6. If confidence \< threshold, clarification prompt sent to client — user selects option — loop restarts from step 4

7. Validated SQL executed against customer's Snowflake warehouse

7a. Result checked against Redis cache (key: hash of normalised SQL + tenant_id); cache hit returns immediately, skipping Snowflake — cache miss proceeds to execution and populates cache on return

8. Result shape analysed → chart type selected (bar / line / table / stat card)

8a. Storytelling call: the LLM is called in parallel with TTS generation using only the result shape (column names, aggregated values) and the original user question — not raw row data — to produce a 1–3 sentence narrative summary. This call and the TTS generation (Step 9) are parallelised; whichever completes first waits for the other before audio plays.

9. TTS summary generated in parallel, streamed to client

10. Chart rendered, audio plays, turn stored in conversation memory and database

# **10\. Risks & Mitigations**

| Risk | Severity | Mitigation |
| :---- | :---- | :---- |
| SQL hallucination delivers wrong numbers to exec | Critical | sqlglot validation \+ confidence scoring \+ always show generated SQL to user |
| Enterprise InfoSec blocks third-party STT/LLM APIs | High | Architect for VPC deployment in roadmap; offer on-prem Whisper as fallback |
| Snowflake query latency exceeds 60s on large tables | High | Query caching, warehouse pre-warming, row limit enforcement, progressive result streaming |
| Poor warehouse metadata quality breaks RAG grounding | High | Admin setup wizard to guide metadata entry; sample query seeding at onboarding |
| Voice modality not used in open office environments | Medium | Text fallback is first-class — voice is one input mode, not a requirement |
| Incumbent (Snowflake, Microsoft) ships native feature | Medium | Speed to reference customer; focus on conversation memory as defensible differentiator |
| Vocabulary mismatch: executive language vs DB column naming breaks RAG grounding | High | Business glossary layer at onboarding (Change 6); admin maps business terms to column names; glossary embedded alongside schema chunks and co-retrieved |
| DB schema lacks FK/PK constraints — join relationships exist only implicitly | High | Admin setup wizard collects explicit relationship declarations at onboarding (Change 8); stored as relationship context injected into SQL generation prompt |
| LLM generates incorrect SQL on 3+ table joins with similar field names across tables | High | Per-table metadata embedding (Change 7); historical query log seeding (Change 9); deduplication detection (Change 11); sqlglot validates join structure |
| Enterprise prospect refuses SaaS model — will not share warehouse credentials with external vendor | High | Single-tenant logical isolation in MVP (separate Postgres schema + encrypted Snowflake DSN per tenant); VPC/self-hosted deployment on roadmap; model-agnostic interface (Change 16) enables on-prem LLM swap |
| Snowflake Cortex, Microsoft Fabric, or Tableau ships native voice-to-SQL before pilot completes | Medium | Speed to reference customer is the primary mitigation; conversation memory and Morning Briefing Mode (V2) are defensible differentiators that incumbents cannot ship quickly; focus pilot on relationship and workflow integration, not feature parity |

# **11\. MVP Milestones**

| Week | Milestone | Deliverable |
| :---- | :---- | :---- |
| 1-2 | Foundation | Auth, Snowflake connection, schema ingestion pipeline, pgvector setup |
| 3-4 | Core pipeline | STT → RAG → SQL gen → sqlglot validation → Snowflake execution working end-to-end |
| 5 | Clarification loop | Confidence scoring, clarification UI, retry flow |
| 6 | Output layer | Chart selector, Recharts render, TTS summary playback |
| 7 | Conversation memory | Multi-turn context, session persistence, history display |
| 8 | Pilot preparation | Observability (Langfuse), error handling, latency optimisation, internal QA |
| 9-10 | Pilot launch | First enterprise pilot customer onboarded; feedback loop begins |

# **12\. Open Questions**

These items require a decision before or during development. Each has a proposed default to avoid blocking work.

| Question | Proposed default | Owner |
| :---- | :---- | :---- |
| Which auth provider — Clerk or Auth0? | Clerk (faster setup, better DX) | Engineering lead |
| How is schema metadata collected at onboarding? | Admin setup wizard with guided flow | Product |
| What is the confidence score threshold for clarification? | 0.65 — tune after 50 pilot queries | ML / Engineering |
| Should generated SQL be visible to users by default? | Collapsed, expandable on click | Product |
| Row limit for Snowflake queries? | 10,000 rows hard cap in MVP | Engineering |
| TTS voice — alloy or nova? | Alloy (neutral, clear) unless pilot requests change | Product |
| STT provider: Deepgram (current) vs ElevenLabs vs Microsoft VibeVoice (OSS)? | Deepgram for MVP; trigger ElevenLabs evaluation if domain vocabulary transcription accuracy < 90% in first 2 pilot weeks | Engineering lead |
| SQL generation: Claude API (current) vs private SLM for InfoSec-sensitive pilots? | Claude API for MVP; model-agnostic adapter (Change 16) enables swap without pipeline rewrite; revisit after first enterprise InfoSec review | Engineering lead |
| Will pilot customer accept SaaS (shared infra) or require single-tenant VPC isolation? | Single-tenant logical isolation in MVP; physical VPC as a fast-follow if pilot deal requires it | Product / Sales |
| Does the pilot customer's Snowflake instance have QUERY_HISTORY accessible for bootstrapping RAG context? | Assume yes; confirm during onboarding call — if not, rely entirely on admin-provided sample queries | Engineering / Customer Success |

# **13\. Post-MVP Roadmap (V2)**

This section documents features that are explicitly out of scope for MVP but must be architected for — meaning MVP decisions must not foreclose these features. V2 scope will be defined in a separate PRD following pilot feedback.

| Feature | V2 Designation | MVP Architecture Constraint |
| :--- | :--- | :--- |
| Morning Briefing Mode | V2.1 — first priority post-pilot | query execution must be callable programmatically (Change 29); turns table needs a `source` column (user \| scheduled) |
| Executive Memory Graph | V2.2 | conversations and turns tables already capture the data; memory graph is an analytics layer over existing tables — no schema change required |
| Cross-session conversation memory | V2.2 | conversations table already persists turns; V2 is a retrieval + summarisation feature over existing data |
| Multi-warehouse support (BigQuery, Redshift) | V2.3 | WarehouseConnector abstract interface required at MVP (Change 4) |
| Row-level security — column-level filtering | V2.3 | Snowflake role passthrough is MVP (Change 1); column masking requires Snowflake Dynamic Data Masking — document as V2 dependency |
| Mobile native app | V2.4 | Next.js PWA wrapper at MVP keeps mobile path open without native dev cost |
| Slack / email output channel | V2.3 | query result format must be serialisable to JSON from day one — do not couple chart rendering to the pipeline response |
| VPC / self-hosted deployment | V2.5 | model-agnostic LLM interface (Change 16) and connector abstraction (Change 4) are the two critical prerequisites |

| *Document owner: Product / Venture CTO. This PRD covers the MVP scope only. Post-pilot scope (multi-warehouse, cross-session memory, SOC 2, VPC deployment) will be captured in a separate V2 PRD following pilot feedback.* |
| :---- |


