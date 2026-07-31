# VoxQuery Production Deployment and Configuration Guide

This guide deploys VoxQuery with Clerk Organizations, Railway, Vercel, Supabase Postgres/pgvector, Upstash Redis, Snowflake, Deepgram, Claude, and OpenAI embeddings.

## 1. Production Model

VoxQuery uses Clerk Organizations as the tenant model:

- `tenant_id` is the Clerk Organization ID, for example `org_...`.
- `user_id` is the Clerk User ID, for example `user_...`.
- Every authenticated API request in `AUTH_MODE=clerk` must include an active Clerk organization context.
- Snowflake access is resolved per tenant from `tenant_connections`.
- RAG schema retrieval is resolved per tenant from `schema_chunks`.

In production, a signed-in user is not fully usable until their active Clerk org has all of the following in Supabase:

- a `tenants` row
- a decryptable `tenant_connections` row
- at least one `schema_chunks` row
- a `tenant_glossary` row

## 2. Generate the Shared Fernet Key

Generate one Fernet key and use the exact same value everywhere that reads or writes `tenant_connections`.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set this value as `FERNET_KEY` in:

- Railway backend variables
- GitHub Actions secrets, if using scheduled schema sync
- any local shell used to run `backend/scripts/sync_schema.py` or `backend/scripts/backfill_connections.py` against production Supabase

Do not regenerate this key after tenant connections have been written. If the key changes, existing encrypted Snowflake DSNs cannot be decrypted by the backend.

## 3. Supabase Setup

1. Open Supabase Dashboard > SQL Editor.
2. Enable pgvector:

   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

3. Apply `backend/db/migrations/001_*.sql` through `008_*.sql` in order, or deploy the backend with `SUPABASE_DATABASE_URL` set so startup can apply pending migrations automatically.
4. Confirm `schema_migrations` contains every migration file name after the first successful backend boot.

## 4. Railway Backend Setup

1. Create a Railway service from the repository.
2. Set the Railway root directory to `/backend`.
3. Add the backend environment variables:

| Variable | Production value |
| :--- | :--- |
| `APP_ENV` | `production` |
| `AUTH_MODE` | `clerk` |
| `BACKEND_CORS_ORIGINS` | `https://<your-vercel-domain>` |
| `SESSION_STORE` | `redis` |
| `UPSTASH_REDIS_URL` | `rediss://default:...@...upstash.io:6379` |
| `SUPABASE_DATABASE_URL` | Supabase Postgres connection string |
| `CLERK_ISSUER` | Clerk issuer URL |
| `CLERK_JWKS_URL` | Clerk JWKS URL |
| `CLERK_AUDIENCE` | Optional; leave unset unless your Clerk JWT uses an audience |
| `CLERK_SECRET_KEY` | `sk_live_...` |
| `CLERK_WEBHOOK_SECRET` | Set after Clerk webhook creation |
| `LLM_PROVIDER` | `claude` |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key for embeddings |
| `RAG_PROVIDER` | `pgvector` |
| `WAREHOUSE_PROVIDER` | `snowflake` |
| `SNOWFLAKE_DSN` | `snowflake://user:pass@account/db/schema?warehouse=...&role=...` |
| `FERNET_KEY` | The shared Fernet key generated in Step 2 |
| `STT_PROVIDER` | `deepgram` |
| `TTS_PROVIDER` | `deepgram` |
| `DEEPGRAM_API_KEY` | Deepgram API key |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key |
| `LANGFUSE_HOST` | Langfuse host, for example `https://cloud.langfuse.com` |

4. Generate the Railway public domain under Settings > Networking.
5. Keep the generated backend URL for Clerk, Vercel, and sanity checks.

## 5. Clerk Setup

Do this after the Railway backend domain exists.

1. Enable Organizations in Clerk Dashboard.
2. Collect the publishable key, secret key, issuer URL, and JWKS URL.
3. Add a webhook endpoint:

   ```text
   https://<your-railway-backend-domain>/api/webhooks/clerk
   ```

4. Subscribe to:

   ```text
   organization.created
   organization.updated
   organization.deleted
   organizationMembership.created
   organizationMembership.updated
   organizationMembership.deleted
   user.created
   user.updated
   user.deleted
   ```

5. Copy the webhook signing secret into Railway as `CLERK_WEBHOOK_SECRET`.
6. In Clerk Webhooks > Recent attempts, confirm deliveries return 2xx after creating or updating a test organization.

Expected user flow:

1. A user signs in with Clerk.
2. VoxQuery shows Clerk organization selection when no active org exists.
3. The user creates an org or accepts an invite into an existing org.
4. Clerk sends organization and membership webhooks to the backend.
5. VoxQuery uses the active Clerk org ID as `tenant_id`.

## 6. Vercel Frontend Setup

1. Import the repository into Vercel.
2. Set the Vercel root directory to `/frontend`.
3. Add frontend environment variables:

| Variable | Production value |
| :--- | :--- |
| `NEXT_PUBLIC_AUTH_MODE` | `clerk` |
| `NEXT_PUBLIC_API_URL` | `https://<your-railway-backend-domain>` |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | `pk_live_...` |
| `CLERK_SECRET_KEY` | `sk_live_...` |

4. Add the final Vercel URL to Railway `BACKEND_CORS_ORIGINS`.

## 7. Provision Each Clerk Organization

Every Clerk organization must be provisioned with the real Clerk org ID.

1. Copy the Organization ID from Clerk Dashboard, for example `org_abc123`.
2. Run schema sync from an environment that uses the same production values as Railway:

   ```bash
   cd backend
   python scripts/sync_schema.py --tenant-id org_abc123
   ```

Required environment variables for this command:

- `SUPABASE_DATABASE_URL`
- `SNOWFLAKE_DSN`
- `OPENAI_API_KEY`
- `FERNET_KEY`

This command writes or updates:

- `tenants`
- `tenant_connections`
- `tenant_glossary`
- `schema_chunks`

If an org exists but is missing a tenant connection, `backend/scripts/backfill_connections.py` can repair missing `tenant_connections` rows. Run it only with the same production `FERNET_KEY` and `SNOWFLAKE_DSN` used by Railway.

## 8. Tenant Provisioning Diagnostic

Use the diagnostic script before asking a teammate to test the shared deployment:

```bash
cd backend
python scripts/check_tenant_provisioning.py --tenant-id org_abc123
```

A deploy is not ready for that org unless all required checks pass:

- `database_connected`
- `fernet_key_configured`
- `tenant_exists`
- `tenant_connection_exists`
- `tenant_connection_decrypts`
- `schema_chunks_populated`
- `tenant_glossary_exists`

`active_memberships_present` is reported as optional because an org can be provisioned before its first member accepts an invite.

## 9. GitHub Scheduled Schema Sync

The scheduled workflow in `.github/workflows/schema_sync.yml` requires these repository secrets:

- `SNOWFLAKE_DSN`
- `SUPABASE_DATABASE_URL`
- `OPENAI_API_KEY`
- `FERNET_KEY`
- `VOXQUERY_TENANT_ID`, set to the Clerk Organization ID to sync

For multiple production organizations, create separate workflow invocations or extend the workflow to loop over an explicit list of Clerk org IDs. Never rely on the script's default tenant ID for production.

## 10. Post-Deployment Sanity Checks

1. Check backend dependency health:

   ```bash
   curl https://<your-railway-backend-domain>/health
   ```

   Expected shape:

   ```json
   {"status":"ok","redis":"ok","postgres":"ok","version":"local-dev"}
   ```

   This does not prove tenant Snowflake/RAG provisioning. Run the tenant diagnostic for that.

2. Confirm Clerk webhook delivery attempts are 2xx.
3. Run `check_tenant_provisioning.py` for the real Clerk org.
4. Open the Vercel URL, sign in, select the org, and create a session.
5. Ask a Snowflake-backed question such as "Show total revenue for delivered orders."

## 11. Demo Preparation for Snowflake Timeout

To reduce cold-start risk during a demo:

```sql
ALTER WAREHOUSE COMPUTE_WH SET AUTO_SUSPEND = 300;
```

This keeps the Snowflake warehouse warm for five minutes after each query.
