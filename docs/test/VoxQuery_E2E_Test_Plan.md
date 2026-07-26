# VoxQuery: Live End-to-End (E2E) Certification Plan

## 1. Objective and Scope
The goal of this test plan is to validate the VoxQuery platform using **100% live credentials and real data**. No mocks, stubs, test doubles, or synthetic data will be used. Pass or fail are sacrosanct. This plan certifies that the entire pipeline—from natural language input to Snowflake query execution and React visualization—is stable, accurate, fully observable, and performs at production latency.

---

## 2. Exhaustive System Architecture & LangGraph Flow Mapping

This section maps every cog in the VoxQuery wheel. The backend is orchestrated by an asynchronous **LangGraph `StateGraph`** that passes a `PipelineGraphState` dictionary between discrete functional nodes. The frontend communicates with this graph via a persistent WebSocket, receiving real-time state transitions.

### 2.1 The Data Lifecycle Node-by-Node

1. **Input Reception (FastAPI WebSocket -> Deepgram):**
   * The user submits a query (text or voice) via the React frontend.
   * If voice, the frontend streams audio chunks over the WebSocket. The backend forwards these to **Deepgram (Live)**, which returns transcribed text. 
   * A `SessionHistoryTurn` record is initialized in **PostgreSQL**.

2. **Node 1: `input_resolver_node` (Intent & Early Ambiguity):**
   * **Action:** The text enters the graph. **Anthropic Claude 3.5 Sonnet (Live)** acts as a semantic judge, enforcing a strict Pydantic output.
   * **State Update:** It populates the `pre_sql_ambiguity` flag.
   * *What is `pre_sql_ambiguity`?* Programmatically, it is a signal that halts the pipeline before any heavy processing occurs. For the user, it means they receive an instant clarifying question (e.g., "By 'US', do you mean Shipping or Billing?") instead of waiting 15 seconds for the system to hallucinate an incorrect SQL query.
   * **Routing:** A conditional edge checks this flag. If ambiguity exists, it routes directly to `clarification_node`. If clear, it routes to `rag_retrieval_node`.

3. **Node 2: `rewrite_query_node` (Pre-Retrieval Expansion):**
   * **Action:** Intercepts the raw query and queries the `MetricRegistry` to resolve business jargon into structured metric metadata.
   * **State Update:** Generates a `RewrittenQuery` object that explicitly targets required tables.

4. **Node 3: `rag_retrieval_node` (Hybrid Context Injection):**
   * **Action:** The system queries the **Vector Store (Live)** using the `RewrittenQuery`. It utilizes **Reciprocal Rank Fusion (RRF)**, combining dense vector embeddings and sparse BM25 lexical search for high-recall schema retrieval.
   * **State Update:** It pulls exact DDL and semantic definitions from the E-commerce schema and appends them to the graph state.

5. **Node 4: `sql_generation_node` (LLM Synthesis):**
   * **Action:** **Anthropic Claude 3.5 Sonnet (Live)** receives the query, the chat history, and the RAG chunks to synthesize a Snowflake-compatible SQL query.
   * **State Update:** Injects the generated SQL into the state.

6. **Node 5: `ambiguity_check_node` (Policy & Post-Generation Validation):**
   * **Action:** The system runs internal policy checks (e.g., detecting Cartesian joins) and evaluates the LLM's self-reported confidence against the generated SQL.
   * **State Update:** If the SQL violates safety policies or is generated with extremely low confidence, it updates the `ambiguity` field.
   * **Routing:** Routes to `execution_node` if safe. Routes to `clarification_node` if unsafe.

7. **Node 6: `execution_node` (Warehouse Interaction):**
   * **Action:** **Snowflake (Live)** executes the analytical workload using a locked-down, read-only Role-Based Access Control (RBAC) user. 
   * **State Update:** Retrieves raw rows and infers `ResultSemantics` (deciding if the data should be a Bar chart, Line chart, or Stat card).

8. **Node 7: `clarification_node` (Interruption):**
   * **Action:** If routed here from Node 1 or Node 5, the graph generates a human-readable question and halts execution.
   * **State Update:** Emits a `ClarificationRequired` payload over the WebSocket. The graph suspends state until the user answers in the UI.

8. **Telemetry & Rendering (Post-Graph):**
   * **Action:** Once the graph completes, **Langfuse (Live)** logs the entire trace (latency, tokens, specific node executions). **PostgreSQL (Live)** commits the final `SessionHistoryTurn`.
   * **Action:** The React frontend receives the final WebSocket payload and uses **Recharts** to dynamically render the data alongside a "Trust Panel" detailing the exact steps taken.

---

## 3. Test Environment Prerequisites
To execute this plan, the environment must be configured with live keys. **Do not execute if testing against mock data.**
- `ANTHROPIC_API_KEY` (Live)
- `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD` (Live - ReadOnly Role)
- `DEEPGRAM_API_KEY` (Live)
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` (Live)
- `POSTGRES_DSN` (Live - Supabase)
- `CLERK_SECRET_KEY`, `CLERK_WEBHOOK_SECRET` (Live)
- **Target Data:** Kaggle E-commerce dataset loaded into Snowflake.
- **App URL:** `http://localhost:3000` (or staging URL).
- **Webhook Configuration:** The Clerk Dashboard must be configured with a Webhook endpoint pointing to the backend's `/api/webhooks/clerk` URL to subscribe to `user.created` and `organization.created` events.

---

## 4. Strict Agent Execution Protocols (NON-NEGOTIABLE)

> **AGENT INSTRUCTION: YOU MUST FOLLOW THESE PROTOCOLS.**
> 1. **No Hallucinations or Shortcuts:** You must actually perform the actions, wait for the UI to change, and read the DOM. Do not assume an action succeeded because you clicked a button.
> 2. **Pass/Fail is Sacrosanct:** If the Expected UI State does not match the actual state, the test **FAILS**. Do not mark it as passed with a caveat. Document the bug clearly.
> 3. **Non-Blocking Execution (Timeouts):** If a network request hangs or the UI shows a loading spinner for more than 15 seconds, the test **FAILS**. Do not wait indefinitely. Log a timeout error, capture the state, and move to the next test case.
> 4. **Live Data Only:** Verify the data returned looks like real Kaggle E-commerce data (e.g., sensible revenue numbers, actual states), not "lorem ipsum" or dummy fallback data.
> 5. **Evidence Collection:** If a test fails, you must capture the error message from the UI, the console logs (if accessible), and explicitly state what broke.
> 6. **Graceful Exit:** If the backend or frontend servers completely crash and become unresponsive (connection refused), abort the test suite immediately and report a critical system failure. Do not attempt to run remaining tests against a dead server.

---

## 5. Test Cases

### Category A: Core Happy Path & Execution
**Test Case A1: Simple Aggregation**
* **Agent UI Action:** Locate the main chat input. Type: *"What is the total revenue for the last 30 days?"* and press Enter. Wait for the loading indicators to disappear (max 15s timeout).
* **Expected UI State:** 
  1. A `Stat` card (large number) appears in the main feed.
  2. The "Trust Panel" (expandable drawer/accordion) displays "Confidence: High".
* **Flow Walkthrough:** `input_resolver_node` -> `rag_retrieval_node` -> `sql_generation_node` -> `ambiguity_check_node` -> `execution_node`.

**Test Case A2: Time-Series Data Visualization**
* **Agent UI Action:** Type: *"Show me daily order volume for the past week."* and press Enter.
* **Expected UI State:** The UI dynamically renders a **Line Chart** (look for SVG paths or Recharts canvas elements).

**Test Case A3: Snowflake Connection Pool (Latency Validation)**
* **Agent UI Action:** Immediately following A2, type a related follow-up: *"What about the week before that?"* and press Enter. Measure the time to resolution.
* **Expected UI State:** The result should render noticeably faster than the first cold-start query (typically returning within 2-4 seconds instead of 5-7), proving the `SnowflakeConnectionPool` successfully avoided a new TLS handshake.

### Category B: The Clarification Loop (Pre-SQL Ambiguity)
**Test Case B1: Entity Ambiguity Block (`pre_sql_ambiguity`)**
* **Agent UI Action:** Type: *"How many customers do we have in the US?"* and press Enter.
* **Expected UI State:** Within 3 seconds, a Clarification Modal or inline prompt appears asking *"By 'US', do you mean Shipping Country or Billing Country?"* (or similar options).
* **Agent UI Action 2:** Click the button for "Shipping Country".
* **Expected UI State:** The modal disappears, the query resumes, and a final numerical result is displayed.

### Category C: Schema-Aware RAG & Hybrid Retrieval
**Test Case C1: Metric Registry Resolution**
* **Agent UI Action:** Type: *"What is our Net Revenue by region?"* and press Enter.
* **Expected UI State:** The Trust Panel text or generated SQL must explicitly show the correct formula for Net Revenue (as defined in the Metric Registry), verifying `rewrite_query_node` successfully mapped the term.

**Test Case C2: RRF Multi-Hop Schema Injection**
* **Agent UI Action:** Type: *"Show me the conversion rate for active customers vs churned customers."* and press Enter.
* **Expected UI State:** A Bar or Line chart is rendered.
* **Verification:** Check the generated SQL in the Trust Panel. It should accurately join `customers` and `orders`, proving RRF retrieved all necessary DDL chunks.

### Category D: Memory & Multi-Turn Context
**Test Case D1: Pronoun Resolution via History**
* **Agent UI Action:** Type: *"Show me the top 5 product categories by sales."* Wait for the Bar Chart.
* **Agent UI Action 2:** Type: *"Now filter those for just the state of California."* Wait for resolution.
* **Expected UI State:** The Bar Chart updates. The Trust Panel's SQL snippet shows a `WHERE` clause for California applied to the previous context.

### Category E: Deliberate Errors (Safety Tests)
**Test Case E1: Destructive Intent (SQL Injection Guard)**
* **Agent UI Action:** Type: *"Delete all records from the orders table."* and press Enter.
* **Expected UI State:** A Graceful Error component appears stating the agent is read-only. Ensure NO chart or table is rendered.

### Category F: Telemetry Verification
**Test Case F1: Langfuse Thumbs Down Scoring**
* **Agent UI Action:** On any successful chart response, locate the "Thumbs Down" (or Feedback) icon and click it.
* **Expected UI State:** The icon highlights or shows a "Feedback submitted" toast. The UI must not crash.

### Category G: Break Cases & Rough Edges (Graceful Degradation)
**Test Case G1: LLM SQL Hallucination (Invalid Column)**
* **Agent UI Action:** Type: *"Select the florp_bloop metric grouped by zazzle_id from the orders table."* and press Enter.
* **Expected UI State:** The query will fail in Snowflake. The UI must catch this and show a graceful error banner (e.g., "I misunderstood the data structure"), **NOT** a raw JSON trace or Snowflake stack trace.

**Test Case G2: Clarification Modal Abandonment**
* **Agent UI Action:** Type an ambiguous query (*"How many customers in the US?"*). Wait for the clarification options to appear.
* **Agent UI Action 2:** DO NOT click an option. Instead, type a brand new query in the main input: *"What is the total revenue?"* and submit.
* **Expected UI State:** The clarification modal dismisses/expires, and the system processes the *new* query normally.

**Test Case G3: Voice Input Graceful Degradation**
* **Agent UI Action:** Click the "Microphone" icon in the UI. (Assume automated browser denies permissions).
* **Expected UI State:** The UI must show a graceful "Microphone access denied" message and revert to text input seamlessly.

**Test Case G4: Clarification Timeout Expiry**
* **Agent UI Action:** Trigger the Clarification Modal. Wait 30 seconds to simulate a stale session, then attempt to select an option.
* **Expected UI State:** If the backend deletes the stale turn, the UI must catch the 404 and gracefully reset or display a "Session Expired" toast, rather than showing an infinite loading spinner.

### Category H: Admin Console & Role-Based Access Control (RBAC)
**Test Case H1: Unauthorized Access Prevention**
* **Agent UI Action:** As a standard user, attempt to navigate directly to `/admin`.
* **Expected UI State:** The system blocks access (redirect to main chat or 403 Forbidden).

**Test Case H2: Tenant Glossary Visualization & Pre-Seeded Data**
* **Agent UI Action:** Log in as an Admin (or inject `x-fake-role: admin` locally) and navigate to `/admin`. Click on the "Glossary" tab.
* **Expected UI State:** The UI successfully fetches and displays the `tenant_glossary` records. **CRITICAL:** The table MUST NOT be empty. It must display the live default Kaggle E-Commerce synonyms (e.g., "revenue", "orders", "active_customers") proving migration `005` ran successfully.

**Test Case H3: Feedback Loop Review**
* **Agent UI Action:** On the `/admin` page, navigate to the "Feedback" tab.
* **Expected UI State:** Displays the aggregated low-quality feedback submitted in Test Case F1.

### Category I: Production-Readiness Constraints (Rate Limiting)
**Test Case I1: Rate Limiter Throttling**
* **Agent UI Action:** Submit queries rapidly in succession (e.g., 20+ queries within a minute) to trigger the rate limiter.
* **Expected UI State:** The backend responds with HTTP 429. The UI catches this and displays a graceful "Too many requests" warning.

### Category J: World-Class Interactive UI Features
**Test Case J1: Interactive Chart Drill-down**
* **Agent UI Action:** Run a query that generates a chart. Click directly on one of the bars/data points in the visualization.
* **Expected UI State:** The UI automatically dispatches a contextual follow-up query into the chat feed, generating a drill-down analysis.

**Test Case J2: Anomaly Narration Validation**
* **Agent UI Action:** Query a time-series dataset that contains a known massive spike or drop.
* **Expected UI State:** The generated narrative text must explicitly call out the spike (the "anomaly") and suggest a business rationale.

**Test Case J3: Sharing & Export (Permalinks)**
* **Agent UI Action:** Click the "Copy Permalink" (Link icon) on a successful turn. Open a new browser tab and navigate to that copied URL.
* **Expected UI State:** The exact same analytical result, chart, and narrative load immediately from the Postgres history without a re-run of the LLM pipeline.

### Category K: Authentication & Tenant Provisioning (Clerk Organizations)
**Test Case K1: Automated Tenant Provisioning via `organization.created` Webhook**
* **Agent UI Action:** In Clerk Dashboard or via webhook test runner, trigger an `organization.created` event with a new `org_...` ID and name.
* **Expected System State:** The backend receives the verified Svix webhook, inserts the new tenant into `tenants` with `id = org_...`, seeds the default `tenant_glossary`, and seeds `tenant_connections` if credentials exist. No outbound PATCH request is sent to Clerk.

**Test Case K2: Automated Membership Management via `organizationMembership.*` Webhooks**
* **Agent UI Action:** Trigger `organizationMembership.created` with `org_...` ID, `user_...` ID, and role `org:admin`.
* **Expected System State:** `users` row is upserted, and a `tenant_memberships` row is created with `(tenant_id, user_id, role)`. Subsequent updates via `organizationMembership.updated` update `tenant_memberships.role`. Deletion via `organizationMembership.deleted` soft-deletes/removes the membership.

**Test Case K3: Token Org Context Enforcement (Active Org Requirement)**
* **Agent UI Action:** Send an API request with a Clerk JWT that lacks an active organization claim (`payload["o"]` and `payload["org_id"]` are missing).
* **Expected UI/API State:** The request is rejected immediately with HTTP 401 `auth_invalid` ("Active organization required").

**Test Case K4: Active Org Switch Across Tabs**
* **Agent UI Action:** In the frontend, use `<OrganizationSwitcher />` to switch active organization from Org A (`org_1`) to Org B (`org_2`).
* **Expected UI State:** The app refreshes the session context via `getToken()`, sending new requests with Org B's JWT token. API `/api/session` and query endpoints execute strictly isolated against Org B's data (`tenant_id = org_2`).

**Test Case K5: Active Org Scoped Customer Admin Routes**
* **Agent UI Action:** As an org admin of `org_1`, navigate to `/admin` and request `/api/admin/glossary` or `/api/admin/stats`.
* **Expected UI/API State:** The returned glossary and analytics stats are strictly filtered to `claims.tenant_id = org_1`. Attempting to pass or modify another tenant's ID in the request is ignored or rejected.

