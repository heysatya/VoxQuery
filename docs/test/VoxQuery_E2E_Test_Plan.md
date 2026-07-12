# VoxQuery: Live End-to-End (E2E) Test Plan

## 1. Objective and Scope
The goal of this test plan is to validate the VoxQuery platform using **100% live credentials and real data**. No mocks, stubs, or test doubles will be used. This plan is designed to be executed by an automated AI browser agent to certify that the entire data pipeline—from natural language input to Snowflake query execution and React visualization—is stable, accurate, and fully observable.

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

3. **Node 2: `rag_retrieval_node` (Schema Context Injection):**
   * **Action:** The system queries the **Vector Store (Live)** using the user's intent.
   * **State Update:** It pulls exact DDL (Data Definition Language) and semantic definitions from the Kaggle E-commerce schema and appends them to the graph state.

4. **Node 3: `sql_generation_node` (LLM Synthesis):**
   * **Action:** **Anthropic Claude 3.5 Sonnet (Live)** receives the query, the chat history, and the RAG chunks to synthesize a Snowflake-compatible SQL query.
   * **State Update:** Injects the generated SQL into the state.

5. **Node 4: `ambiguity_check_node` (Policy & Post-Generation Validation):**
   * **Action:** The system runs internal policy checks (e.g., detecting Cartesian joins) and evaluates the LLM's self-reported confidence against the generated SQL.
   * **State Update:** If the SQL violates safety policies or is generated with extremely low confidence, it updates the `ambiguity` field.
   * **Routing:** Routes to `execution_node` if safe. Routes to `clarification_node` if unsafe.

6. **Node 5: `execution_node` (Warehouse Interaction):**
   * **Action:** **Snowflake (Live)** executes the analytical workload using a locked-down, read-only Role-Based Access Control (RBAC) user. 
   * **State Update:** Retrieves raw rows and infers `ResultSemantics` (deciding if the data should be a Bar chart, Line chart, or Stat card).

7. **Node 6: `clarification_node` (Interruption):**
   * **Action:** If routed here from Node 1 or Node 4, the graph generates a human-readable question and halts execution.
   * **State Update:** Emits a `ClarificationRequired` payload over the WebSocket. The graph suspends state until the user answers in the UI.

8. **Telemetry & Rendering (Post-Graph):**
   * **Action:** Once the graph completes, **Langfuse (Live)** logs the entire trace (latency, tokens, specific node executions). **PostgreSQL (Live)** commits the final `SessionHistoryTurn`.
   * **Action:** The React frontend receives the final WebSocket payload and uses **Recharts** to dynamically render the data alongside a "Trust Panel" detailing the exact steps taken.

---

## 3. Test Environment Prerequisites
To execute this plan, the environment must be configured with live keys:
- `ANTHROPIC_API_KEY` (Live)
- `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD` (Live - ReadOnly Role)
- `DEEPGRAM_API_KEY` (Live)
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` (Live)
- `POSTGRES_DSN` (Live)
- Target Data: Kaggle E-commerce dataset loaded into Snowflake.
- App URL: `http://localhost:3000` (or staging URL).

---

## 4. Test Cases & Agent Execution Instructions

> **AGENT INSTRUCTION:** For each test case, interact with the UI at the provided URL. Do not halt testing if a single case fails. Log the failure (screenshot + text) and proceed to the next case.

### Category A: Core Happy Path & Execution
**Test Case A1: Simple Aggregation**
* **Agent UI Action:** Locate the main chat input. Type: *"What is the total revenue for the last 30 days?"* and press Enter. Wait for the loading indicators to disappear.
* **Expected UI State:** 
  1. A `Stat` card (large number) appears in the main feed.
  2. The "Trust Panel" (expandable drawer/accordion) displays "Confidence: High".
* **Flow Walkthrough:** `input_resolver_node` -> `rag_retrieval_node` -> `sql_generation_node` -> `ambiguity_check_node` -> `execution_node`.

**Test Case A2: Time-Series Data Visualization**
* **Agent UI Action:** Type: *"Show me daily order volume for the past week."* and press Enter. Wait for resolution.
* **Expected UI State:** The UI dynamically renders a **Line Chart** (look for SVG paths or Recharts canvas elements).

### Category B: The Clarification Loop (Pre-SQL Ambiguity)
**Test Case B1: Entity Ambiguity Block (`pre_sql_ambiguity`)**
* **Agent UI Action:** Type: *"How many customers do we have in the US?"* and press Enter.
* **Expected UI State:** Within 3 seconds, a Clarification Modal or inline prompt appears asking *"By 'US', do you mean Shipping Country or Billing Country?"* (or similar options).
* **Agent UI Action 2:** Click the button for "Shipping Country". Wait for resolution.
* **Expected UI State:** The modal disappears, the query resumes, and a final numerical result is displayed.

### Category C: RAG & Context Integration
**Test Case C1: Domain Jargon Resolution**
* **Agent UI Action:** Type: *"What is our average order value for VIP customers?"* and press Enter.
* **Expected UI State:** A result is rendered. Expand the "Trust Panel". 
* **Verification:** The Trust Panel text must explicitly mention using the schema definition for "VIP customers" or show a SQL snippet featuring `COUNT > 5`.

### Category D: Memory & Multi-Turn Context
**Test Case D1: Pronoun Resolution via History**
* **Agent UI Action:** Type: *"Show me the top 5 product categories by sales."* Wait for the Bar Chart.
* **Agent UI Action 2:** Type: *"Now filter those for just the state of California."* Wait for resolution.
* **Expected UI State:** The Bar Chart updates. The visual categories remain the same, but the numerical values change. The Trust Panel's SQL snippet should show a `WHERE` clause for California applied to the previous context.

### Category E: Deliberate Errors (Safety Tests)
**Test Case E1: Destructive Intent (SQL Injection Guard)**
* **Agent UI Action:** Type: *"Delete all records from the orders table."* and press Enter.
* **Expected UI State:** A Graceful Error component (red/orange banner or card) appears stating the agent is read-only and cannot modify data. Ensure NO chart or table is rendered.

### Category F: Telemetry Verification
**Test Case F1: Langfuse Thumbs Down Scoring**
* **Agent UI Action:** On any successful chart response, locate the "Thumbs Down" (or Feedback) icon and click it.
* **Expected UI State:** The icon highlights or shows a "Feedback submitted" toast. (Note: Backend verification in Langfuse/Postgres is required for full validation, but the UI must not crash).

---

## 5. Category G: Break Cases & Rough Edges (Where things can go wrong)

These test cases specifically target the "cogs breaking" to ensure the system degrades gracefully.

**Test Case G1: LLM SQL Hallucination (Invalid Column)**
* **Agent UI Action:** Type: *"Select the florp_bloop metric grouped by zazzle_id from the orders table."* and press Enter.
* **Expected UI State:** The query will fail in Snowflake. The UI must catch this and show a graceful error banner (e.g., "I misunderstood the data structure"), **NOT** a raw JSON trace or Snowflake stack trace.

**Test Case G2: Clarification Modal Abandonment**
* **Agent UI Action:** Type a known ambiguous query (e.g., *"How many customers in the US?"*). Wait for the clarification options to appear.
* **Agent UI Action 2:** DO NOT click an option. Instead, type a brand new query in the main input: *"What is the total revenue?"* and submit.
* **Expected UI State:** The clarification modal dismisses/expires, and the system processes the *new* query normally, resulting in a Stat card for revenue.

**Test Case G3: Voice Input Graceful Degradation**
* **Note to Agent:** Since automated browsers usually lack microphone access, click the "Microphone" icon in the UI.
* **Expected UI State:** The browser should request microphone permissions (if the agent auto-denies, the UI must show a graceful "Microphone access denied" message and revert to text input seamlessly).
