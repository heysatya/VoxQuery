# VoxQuery Production Deployment & Configuration Guide

This guide provides a comprehensive, step-by-step procedure for deploying VoxQuery with **Clerk Authentication**, **Supabase (PostgreSQL + pgvector)**, **Upstash Redis**, **Snowflake Warehouse**, **Langfuse Observability**, **Railway (Backend)**, and **Vercel (Frontend)**.

---

## Table of Contents
1. [Architecture & Multi-Tenancy Principles](#1-architecture--multi-tenancy-principles)
2. [Supabase Database Setup & Migrations](#2-supabase-database-setup--migrations)
   - [Step 2.1: Enable `pgvector` Extension](#step-21-enable-pgvector-extension)
   - [Step 2.2: Apply Database Schema Migrations](#step-22-apply-database-schema-migrations)
   - [Step 2.3: Execute RAG Schema & Vector Indexing](#step-23-execute-rag-schema--vector-indexing)
3. [Clerk Authentication Setup](#3-clerk-authentication-setup)
   - [Step 3.1: API Keys & Issuer Setup](#step-31-api-keys--issuer-setup)
   - [Step 3.2: Configure Session Token Template (JWT Claims)](#step-32-configure-session-token-template-jwt-claims)
   - [Step 3.3: Webhooks Provisioning](#step-33-webhooks-provisioning)
4. [Upstash Redis, Snowflake, Langfuse & Deepgram Setup](#4-upstash-redis-snowflake-langfuse--deepgram-setup)
   - [4.1 Upstash Redis Session Store & Rate Limiter](#41-upstash-redis-session-store--rate-limiter)
   - [4.2 Snowflake Warehouse & Fernet Key Encryption](#42-snowflake-warehouse--fernet-key-encryption)
   - [4.3 Langfuse Observability & LLM Tracing](#43-langfuse-observability--llm-tracing)
   - [4.4 Deepgram Speech-to-Text & Text-to-Speech](#44-deepgram-speech-to-text--text-to-speech)
5. [Railway Deployment (Backend Hosting)](#5-railway-deployment-backend-hosting)
   - [Step 5.1: Create Service & Connect Repository](#step-51-create-service--connect-repository)
   - [Step 5.2: Configure Environment Variables](#step-52-configure-environment-variables)
   - [Step 5.3: Health Check & Network Configuration](#step-53-health-check--network-configuration)
6. [Vercel Deployment (Frontend Hosting)](#6-vercel-deployment-frontend-hosting)
   - [Step 6.1: Import Project & Configure Build Settings](#step-61-import-project--configure-build-settings)
   - [Step 6.2: Configure Environment Variables](#step-62-configure-environment-variables)
   - [Step 6.3: Configure CORS & Domain Linkage](#step-63-configure-cors--domain-linkage)
7. [Full Environment Variables Reference](#7-full-environment-variables-reference)
8. [Post-Deployment Verification & Sanity Checks](#8-post-deployment-verification--sanity-checks)

---

## 1. Architecture & Multi-Tenancy Principles

VoxQuery is built from the ground up to be **strictly multi-tenant and environment-driven**. No customer IDs, tenant IDs, or credentials are hardcoded.

* **Local Sandbox vs. Production**:
  * In local development (`AUTH_MODE=fake`), VoxQuery uses a local sandbox UUID (`00000000-0000-0000-0000-000000000101`) to allow developers to run tests offline without Clerk or Supabase webhooks.
  * In production (`AUTH_MODE=clerk`), **every user/organization gets a unique, dynamically generated UUID** assigned by Clerk webhooks and stored in Supabase (`tenants` and `users` tables).
* **Tenant Isolation**:
  * Every turn record, session, vector search embedding chunk, business glossary rule, and warehouse DSN connection in Supabase is strictly scoped by `tenant_id`.
  * `TenantRoutingWarehouseConnector` dynamically decrypts and routes Snowflake queries at runtime for the requesting tenant.

---

## 2. Supabase Database Setup & Migrations

### Step 2.1: Enable `pgvector` Extension

Open the **Supabase Dashboard → SQL Editor** for your project and run:

```sql
-- Enable vector extension for schema_chunks RAG embeddings
CREATE EXTENSION IF NOT EXISTS vector;
```

---

### Step 2.2: Apply Database Schema Migrations

Execute the following SQL scripts in sequence within the Supabase SQL Editor. The source files are located in [`backend/db/migrations/`](file:///c:/Users/satya/Desktop/AI%20Projects/Voice-Driven%20Data%20Analyst%20-%20VoxQuery/backend/db/migrations/).

#### Migration 1: Core Subsystem Schema ([`001_voice_subsystem.sql`](file:///c:/Users/satya/Desktop/AI%20Projects/Voice-Driven%20Data%20Analyst%20-%20VoxQuery/backend/db/migrations/001_voice_subsystem.sql))

```sql
CREATE TABLE IF NOT EXISTS tenants (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  email TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK (role IN ('viewer', 'admin', 'editor')),
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
```

#### Migration 2: RAG Embeddings Schema ([`002_gate7_rag.sql`](file:///c:/Users/satya/Desktop/AI%20Projects/Voice-Driven%20Data%20Analyst%20-%20VoxQuery/backend/db/migrations/002_gate7_rag.sql))

```sql
CREATE TABLE IF NOT EXISTS schema_chunks (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  table_name TEXT NOT NULL,
  column_name TEXT,
  content TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  entity_type TEXT NOT NULL DEFAULT 'column',
  embedding vector(1536),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS schema_chunks_embedding_idx 
  ON schema_chunks USING hnsw (embedding vector_cosine_ops);
```

#### Migration 3: Business Glossary Schema ([`003_tenant_glossary.sql`](file:///c:/Users/satya/Desktop/AI%20Projects/Voice-Driven%20Data%20Analyst%20-%20VoxQuery/backend/db/migrations/003_tenant_glossary.sql))

```sql
CREATE TABLE IF NOT EXISTS tenant_glossary (
  tenant_id UUID PRIMARY KEY REFERENCES tenants(id),
  metric_synonyms JSONB NOT NULL DEFAULT '{}',
  table_synonyms JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### Migration 4: Admin Console & Hit Tracking ([`004_admin_console_enhancements.sql`](file:///c:/Users/satya/Desktop/AI%20Projects/Voice-Driven%20Data%20Analyst%20-%20VoxQuery/backend/db/migrations/004_admin_console_enhancements.sql))

```sql
ALTER TABLE tenant_glossary 
  ADD COLUMN IF NOT EXISTS synonym_hits JSONB NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS total_hits INTEGER NOT NULL DEFAULT 0;

CREATE OR REPLACE VIEW admin_glossary_view AS
  SELECT 
    tg.tenant_id,
    COALESCE(t.name, tg.tenant_id::text) AS workspace_name,
    tg.metric_synonyms,
    tg.table_synonyms,
    tg.synonym_hits,
    tg.total_hits,
    tg.updated_at
  FROM tenant_glossary tg
  LEFT JOIN tenants t ON t.id = tg.tenant_id;
```

#### Migration 5: Sessions, Turns & Pinned Widgets ([`007_wow_features_v2.sql`](file:///c:/Users/satya/Desktop/AI%20Projects/Voice-Driven%20Data%20Analyst%20-%20VoxQuery/backend/db/migrations/007_wow_features_v2.sql))

```sql
CREATE TABLE IF NOT EXISTS sessions (
  session_id      UUID PRIMARY KEY,
  tenant_id       UUID NOT NULL REFERENCES tenants(id),
  user_id         UUID NOT NULL REFERENCES users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_active_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS turns (
  turn_id                 UUID PRIMARY KEY,
  session_id              UUID REFERENCES sessions(session_id) ON DELETE CASCADE,
  conversation_id         UUID NOT NULL,
  parent_turn_id          UUID REFERENCES turns(turn_id),
  tenant_id               UUID NOT NULL REFERENCES tenants(id),
  user_id                 UUID NOT NULL REFERENCES users(id),
  user_input              TEXT NOT NULL,
  raw_transcript          TEXT,
  deepgram_confidence_raw DOUBLE PRECISION,
  input_modality          TEXT DEFAULT 'text',
  generated_sql           TEXT NOT NULL DEFAULT '',
  source_tables           TEXT[] NOT NULL DEFAULT '{}',
  filter_predicates       JSONB NOT NULL DEFAULT '[]',
  chart_type              TEXT,
  chart_rationale         TEXT DEFAULT '',
  confidence_tier         TEXT,
  composite_score         DOUBLE PRECISION,
  result_json             JSONB,
  full_result             JSONB,
  anomalies               JSONB NOT NULL DEFAULT '[]',
  proactive_questions     JSONB NOT NULL DEFAULT '[]',
  quality_flag            TEXT NOT NULL DEFAULT 'ok',
  latency_ms              INTEGER NOT NULL DEFAULT 0,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed               BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_turns_session_created ON turns (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_turns_tenant ON turns (tenant_id);

CREATE TABLE IF NOT EXISTS pinned_widgets (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id    UUID NOT NULL REFERENCES tenants(id),
  user_id      UUID NOT NULL REFERENCES users(id),
  turn_id      UUID NOT NULL REFERENCES turns(turn_id) ON DELETE CASCADE,
  title        TEXT NOT NULL,
  layout_x     INTEGER NOT NULL DEFAULT 0,
  layout_y     INTEGER NOT NULL DEFAULT 0,
  layout_w     INTEGER NOT NULL DEFAULT 4,
  layout_h     INTEGER NOT NULL DEFAULT 3,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pinned_widgets_user ON pinned_widgets (tenant_id, user_id);
```

---

### Step 2.3: Execute RAG Schema & Vector Indexing

The script `backend/scripts/sync_schema.py` connects to Snowflake, extracts warehouse metadata, generates vector embeddings using OpenAI `text-embedding-3-small`, and populates `schema_chunks` and `tenant_glossary` in Supabase.

* **For Local Development / Sandbox Testing**:
  Run with default sandbox tenant UUID `00000000-0000-0000-0000-000000000101`:
  ```bash
  cd backend
  python scripts/sync_schema.py --tenant-id 00000000-0000-0000-0000-000000000101
  ```

* **For Production / Real Tenant Provisioning**:
  Replace `--tenant-id` with the target workspace tenant's UUID generated by Clerk:
  ```bash
  cd backend
  python scripts/sync_schema.py --tenant-id <TARGET_TENANT_UUID>
  ```

---

## 3. Clerk Authentication Setup

### Step 3.1: API Keys & Issuer Setup

In **Clerk Dashboard → API Keys**:
* Copy **Publishable Key** (`pk_live_...`) and **Secret Key** (`sk_live_...`).
* Note **Issuer URL** (`https://<your-app>.clerk.accounts.dev`) and **JWKS URL** (`https://<your-app>.clerk.accounts.dev/.well-known/jwks.json`).

---

### Step 3.2: Configure Session Token Template (JWT Claims)

In **Clerk Dashboard → Configure → Sessions → Customize Session Token**, add custom metadata claims:

```json
{
  "vox_user_id": "{{user.public_metadata.vox_user_id}}",
  "vox_tenant_id": "{{user.public_metadata.vox_tenant_id}}",
  "role": "{{user.public_metadata.role}}",
  "snowflake_role": "{{user.public_metadata.snowflake_role}}"
}
```

---

### Step 3.3: Webhooks Provisioning

In **Clerk Dashboard → Webhooks → Add Endpoint**:
* **URL**: `https://<your-backend-railway-url>.up.railway.app/api/webhooks/clerk`
* **Subscribed Events**: `user.created`, `organization.created`
* Copy the **Signing Secret** (`whsec_...`) for `CLERK_WEBHOOK_SECRET`.

---

## 4. Upstash Redis, Snowflake, Langfuse & Deepgram Setup

### 4.1 Upstash Redis Session Store & Rate Limiter

1. Create a Redis database in **[Upstash Console](https://console.upstash.com/)**.
2. Copy the **REST / Connection URL** (e.g. `https://[YOUR_REDIS].upstash.io` or `rediss://default:password@...upstash.io:6379`).
3. Set the following backend variables:
   ```env
   SESSION_STORE=redis
   UPSTASH_REDIS_URL=https://[YOUR_REDIS].upstash.io
   ```

### 4.2 Snowflake Warehouse & Fernet Key Encryption

VoxQuery encrypts warehouse credentials stored in Supabase (`tenant_connections.snowflake_dsn`) using Fernet symmetric encryption.

1. **Format Snowflake DSN**:
   ```env
   SNOWFLAKE_DSN=snowflake://<username>:<password>@<account_identifier>/<database>/<schema>?warehouse=<warehouse_name>&role=<role_name>
   ```
2. **Generate Fernet Encryption Key**:
   Run in Python terminal:
   ```python
   from cryptography.fernet import Fernet
   print(Fernet.generate_key().decode())
   # Output example: '8xZ9kL1...='
   ```
3. Set `FERNET_KEY` in `backend/.env`.

### 4.3 Langfuse Observability & LLM Tracing

1. Log into **[Langfuse](https://langfuse.com/)** and create a project.
2. In Project Settings → **API Keys**, generate new keys.
3. Configure backend variables:
   ```env
   LANGFUSE_SECRET_KEY=sk-lf-...
   LANGFUSE_PUBLIC_KEY=pk-lf-...
   LANGFUSE_HOST=https://cloud.langfuse.com
   ```

### 4.4 Deepgram Speech-to-Text & Text-to-Speech

1. Sign up at **[Deepgram](https://deepgram.com/)** and create an API Key.
2. Configure backend variables:
   ```env
   STT_PROVIDER=deepgram
   TTS_PROVIDER=deepgram
   DEEPGRAM_API_KEY=your_deepgram_api_key
   DEEPGRAM_MIP_OPT_OUT=true
   ```

---

## 5. Railway Deployment (Backend Hosting)

### Step 5.1: Create Service & Connect Repository

1. Log into **[Railway.app](https://railway.app/)** and click **New Project → Deploy from GitHub repo**.
2. Select your `VoxQuery` repository.
3. Set the **Root Directory** to `/backend`.
4. Railway will automatically detect [`backend/Dockerfile`](file:///c:/Users/satya/Desktop/AI%20Projects/Voice-Driven%20Data%20Analyst%20-%20VoxQuery/backend/Dockerfile) and build the container using `python:3.12-slim` and `uv`.

### Step 5.2: Configure Environment Variables

In Railway → **Variables**, add all backend variables (refer to Section 7 for the complete list).

### Step 5.3: Health Check & Network Configuration

1. In Railway → **Settings → Networking**:
   * Click **Generate Domain** (e.g. `voxquery-backend-production.up.railway.app`).
2. Under **Healthcheck**:
   * **Healthcheck Path**: `/health`
   * **Timeout**: `10 seconds`

---

## 6. Vercel Deployment (Frontend Hosting)

### Step 6.1: Import Project & Configure Build Settings

1. Log into **[Vercel](https://vercel.com/)** and click **Add New → Project**.
2. Import the `VoxQuery` GitHub repository.
3. Set **Root Directory** to `frontend`.
4. Framework Preset: **Next.js** (automatically detected via [`frontend/vercel.json`](file:///c:/Users/satya/Desktop/AI%20Projects/Voice-Driven%20Data%20Analyst%20-%20VoxQuery/frontend/vercel.json)).

### Step 6.2: Configure Environment Variables

In Vercel → **Environment Variables**, add:

```env
NEXT_PUBLIC_AUTH_MODE=clerk
NEXT_PUBLIC_API_URL=https://voxquery-backend-production.up.railway.app
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_live_...
CLERK_SECRET_KEY=sk_live_...
```

### Step 6.3: Configure CORS & Domain Linkage

Update `BACKEND_CORS_ORIGINS` in Railway settings to include your Vercel domain:
```env
BACKEND_CORS_ORIGINS=https://voxquery.vercel.app,http://localhost:3000
```

---

## 7. Full Environment Variables Reference

### Backend Reference (`backend/.env` / Railway Variables)

| Variable | Recommended Value | Purpose |
| :--- | :--- | :--- |
| `APP_ENV` | `production` | Environment mode |
| `AUTH_MODE` | `clerk` | Auth verifier provider |
| `BACKEND_CORS_ORIGINS` | `https://voxquery.vercel.app` | Allowed CORS origins |
| `SESSION_STORE` | `redis` | Session storage adapter |
| `UPSTASH_REDIS_URL` | `https://[YOUR_REDIS].upstash.io` | Upstash Redis connection |
| `SUPABASE_DATABASE_URL` | `postgresql://postgres:...` | Supabase Postgres connection |
| `CLERK_ISSUER` | `https://[DOM].clerk.accounts.dev` | Clerk JWT Issuer URL |
| `CLERK_JWKS_URL` | `https://[DOM].../jwks.json` | Clerk JWKS verification URL |
| `CLERK_SECRET_KEY` | `sk_live_...` | Clerk Backend Secret Key |
| `CLERK_WEBHOOK_SECRET` | `whsec_...` | Svix Webhook Verification Secret |
| `CLERK_USER_ID_CLAIM` | `vox_user_id` | User claim key in JWT |
| `CLERK_TENANT_ID_CLAIM` | `vox_tenant_id` | Tenant claim key in JWT |
| `CLERK_ROLE_CLAIM` | `role` | Role claim key in JWT |
| `CLERK_SNOWFLAKE_ROLE_CLAIM` | `snowflake_role` | Snowflake role claim key in JWT |
| `LLM_PROVIDER` | `anthropic` | LLM provider (`anthropic` or `openai`) |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Anthropic API key |
| `OPENAI_API_KEY` | `sk-proj-...` | OpenAI API key for embeddings |
| `RAG_PROVIDER` | `supabase` | RAG vector search adapter |
| `WAREHOUSE_PROVIDER` | `snowflake` | Data warehouse adapter |
| `SNOWFLAKE_DSN` | `snowflake://user:pass@acc...` | Default Snowflake connection DSN |
| `FERNET_KEY` | `base64_key...` | Encryption key for tenant connections |
| `STT_PROVIDER` | `deepgram` | Speech-to-Text provider |
| `TTS_PROVIDER` | `deepgram` | Text-to-Speech provider |
| `DEEPGRAM_API_KEY` | `your_deepgram_key` | Deepgram API key |
| `DEEPGRAM_MIP_OPT_OUT` | `true` | Opt-out of Deepgram model training |
| `LANGFUSE_SECRET_KEY` | `sk-lf-...` | Langfuse secret key |
| `LANGFUSE_PUBLIC_KEY` | `pk-lf-...` | Langfuse public key |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Langfuse host URL |

### Frontend Reference (`frontend/.env.local` / Vercel Variables)

| Variable | Recommended Value | Purpose |
| :--- | :--- | :--- |
| `NEXT_PUBLIC_AUTH_MODE` | `clerk` | Enables Clerk Auth Provider |
| `NEXT_PUBLIC_API_URL` | `https://[RAILWAY_APP].up.railway.app` | Backend FastAPI API base URL |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | `pk_live_...` | Clerk Frontend Publishable Key |
| `CLERK_SECRET_KEY` | `sk_live_...` | Clerk Secret Key for Next.js SSR |

---

## 8. Post-Deployment Verification & Sanity Checks

Execute these checks after Railway and Vercel deployments complete:

### 1. Health Endpoint Verification
```bash
curl -i https://voxquery-backend-production.up.railway.app/health
# Expected Output: HTTP 200 OK {"status": "ok"}
```

### 2. Upstash Redis & Auth JWT Test
```bash
curl -i -H "Authorization: Bearer <CLERK_JWT_TOKEN>" https://voxquery-backend-production.up.railway.app/api/turns
# Expected Output: HTTP 200 OK with turns list
```

### 3. Automated Integration Tests
```bash
cd backend
pytest tests/test_auth.py tests/test_session.py tests/test_webhooks.py
```

### 4. Clerk Webhook Trigger Test
In Clerk Dashboard → **Webhooks → Testing**, trigger a `user.created` event. Confirm:
* Response HTTP status `200 OK`.
* Personal tenant workspace entry created in Supabase `tenants` and `users` tables.

---
*VoxQuery Deployment & Configuration Guide Completed.*
