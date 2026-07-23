# VoxQuery Production Deployment & Configuration Guide (Clerk-Native Multi-Tenant)

This guide provides a streamlined, step-by-step procedure for deploying VoxQuery with **Clerk Organization Multi-Tenancy**, **Supabase (PostgreSQL + pgvector)**, **Upstash Redis**, **Snowflake Warehouse**, **Railway (Backend)**, and **Vercel (Frontend)**.

---

## 1. Multi-Tenancy Architecture

VoxQuery uses **Clerk Organizations** as its sole B2B multi-tenant model:
* **Canonical IDs**: `tenant_id` = Clerk Organization ID (`org_...`), `user_id` = Clerk User ID (`user_...`).
* **Active Organization Enforcement**: Every API request in `AUTH_MODE=clerk` requires a Clerk JWT with an active organization context (`payload["o"]["id"]`).
* **Data Isolation**: All turn records, vector embeddings, sessions, glossary rules, and Snowflake connection strings are strictly isolated in Supabase by `tenant_id`.

---

## 2. Step-by-Step Deployment Procedure

### Step 1: Database Setup (Supabase)

1. Open **Supabase Dashboard → SQL Editor** and enable the vector extension:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
2. Execute the migration scripts located in `backend/db/migrations/` in sequence (001 through 008).

> **Note**: VoxQuery's backend automatically executes pending SQL migrations on startup when `SUPABASE_DATABASE_URL` is set.

---

### Step 2: Clerk Authentication Setup

1. **Enable Organizations**: Go to **Clerk Dashboard → Organization Settings** and enable Organizations for your instance.
2. **API Keys**: Collect your **Publishable Key** (`pk_live_...`), **Secret Key** (`sk_live_...`), **Issuer URL** (`https://<your-app>.clerk.accounts.dev`), and **JWKS URL** (`https://<your-app>.clerk.accounts.dev/.well-known/jwks.json`).
3. **Webhooks Setup**:
   * Go to **Clerk Dashboard → Webhooks → Add Endpoint**.
   * **URL**: `https://<your-backend-railway-domain>/api/webhooks/clerk`
   * **Subscribed Events**: Select `organization.created`, `organization.updated`, `organization.deleted`, `organizationMembership.created`, `organizationMembership.updated`, `organizationMembership.deleted`, and `user.created`.
   * Copy the **Signing Secret** (`whsec_...`) to use as `CLERK_WEBHOOK_SECRET`.

---

### Step 3: Railway Deployment (Backend)

1. **Create Railway Service**:
   * Log into **[Railway.app](https://railway.app/)** → **New Project → Deploy from GitHub repo**.
   * Select your repository and set the **Root Directory** to `/backend`.
2. **Configure Environment Variables**:

   | Variable | Recommended Value | Purpose |
   | :--- | :--- | :--- |
   | `APP_ENV` | `production` | Production mode enforcement |
   | `AUTH_MODE` | `clerk` | Verifies Clerk JWT tokens |
   | `BACKEND_CORS_ORIGINS` | `https://<your-vercel-domain>.vercel.app` | Allowed CORS origins |
   | `SESSION_STORE` | `redis` | Upstash Redis session storage |
   | `UPSTASH_REDIS_URL` | `rediss://default:...@...upstash.io:6379` | Upstash Redis connection URL |
   | `SUPABASE_DATABASE_URL` | `postgresql://postgres:...@...supabase.com:6543/postgres` | Supabase Postgres URL |
   | `CLERK_ISSUER` | `https://<your-app>.clerk.accounts.dev` | Clerk Issuer URL |
   | `CLERK_JWKS_URL` | `https://<your-app>.clerk.accounts.dev/.well-known/jwks.json` | Clerk JWKS verification URL |
   | `CLERK_SECRET_KEY` | `sk_live_...` | Clerk Secret Key |
   | `CLERK_WEBHOOK_SECRET` | `whsec_...` | Svix Webhook Signing Secret |
   | `LLM_PROVIDER` | `claude` | LLM Provider (`claude`) |
   | `ANTHROPIC_API_KEY` | `sk-ant-...` | Anthropic Claude API Key |
   | `OPENAI_API_KEY` | `sk-proj-...` | OpenAI API Key (for vector embeddings) |
   | `RAG_PROVIDER` | `pgvector` | Supabase pgvector RAG retriever |
   | `WAREHOUSE_PROVIDER` | `snowflake` | Snowflake Data Warehouse connector |
   | `SNOWFLAKE_DSN` | `snowflake://user:pass@acc/db/schema?warehouse=wh&role=role` | Default Snowflake DSN |
   | `FERNET_KEY` | `<generated_fernet_key_base64>` | Key for encrypting tenant connection DSNs |
   | `STT_PROVIDER` | `deepgram` | Speech-to-Text provider |
   | `TTS_PROVIDER` | `deepgram` | Text-to-Speech provider |
   | `DEEPGRAM_API_KEY` | `your_deepgram_api_key` | Deepgram API Key |
   | `LANGFUSE_PUBLIC_KEY` | `pk-lf-...` | Langfuse public key |
   | `LANGFUSE_SECRET_KEY` | `sk-lf-...` | Langfuse secret key |
   | `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Langfuse host URL |

3. **Generate Domain**: Under Railway **Settings → Networking**, click **Generate Domain** (e.g., `https://voxquery-backend.up.railway.app`).

---

### Step 4: Vercel Deployment (Frontend)

1. **Import Vercel Project**:
   * Log into **[Vercel](https://vercel.com/)** → **Add New → Project**.
   * Import your repository and set the **Root Directory** to `frontend`.
2. **Configure Environment Variables**:

   | Variable | Value | Purpose |
   | :--- | :--- | :--- |
   | `NEXT_PUBLIC_AUTH_MODE` | `clerk` | Enables Clerk Auth in Next.js UI |
   | `NEXT_PUBLIC_API_URL` | `https://<your-railway-backend-domain>` | Backend FastAPI base URL |
   | `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | `pk_live_...` | Clerk Frontend Publishable Key |
   | `CLERK_SECRET_KEY` | `sk_live_...` | Clerk Secret Key for Next.js SSR |

3. **Deploy & Link CORS**: Add your generated Vercel production URL (e.g. `https://voxquery.vercel.app`) to `BACKEND_CORS_ORIGINS` in Railway settings.

---

### Step 5: Provision Organization & Sync Snowflake Schema

Whenever a new Clerk Organization is onboarded:

1. Copy the **Organization ID** (`org_...`) from Clerk Dashboard.
2. From your local terminal or deployment pipeline, run:
   ```bash
   cd backend
   python scripts/sync_schema.py --tenant-id org_...
   ```
   *This extracts Snowflake table/column metadata, generates OpenAI embeddings, and indexes `schema_chunks` in Supabase for that organization.*

---

## 3. Post-Deployment Sanity Checks

1. **Health Endpoint**:
   ```bash
   curl https://<your-backend-railway-domain>/health
   # Expected Output: {"status": "ok", "redis": "ok", "postgres": "ok"}
   ```
2. **Frontend Sign-In & Org Switcher**:
   * Open `https://<your-vercel-domain>.vercel.app`.
   * Sign in with a Clerk user. Select an active organization using the `<OrganizationSwitcher />`.
3. **Run Query**: Ask *"Show total revenue for delivered orders"* to verify end-to-end multi-tenant routing against Snowflake.
