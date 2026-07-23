-- Migration 008: Clerk-Native Multi-Tenancy (String IDs, Tenant Memberships, Composite Snowflake Roles)

-- Step 1: Remove existing FK constraints referencing tenants.id and users.id
ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_tenant_id_fkey;
ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_user_id_fkey;

ALTER TABLE turns DROP CONSTRAINT IF EXISTS turns_tenant_id_fkey;
ALTER TABLE turns DROP CONSTRAINT IF EXISTS turns_user_id_fkey;

ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_tenant_id_fkey;
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_user_id_fkey;

ALTER TABLE user_snowflake_roles DROP CONSTRAINT IF EXISTS user_snowflake_roles_tenant_id_fkey;
ALTER TABLE user_snowflake_roles DROP CONSTRAINT IF EXISTS user_snowflake_roles_user_id_fkey;

ALTER TABLE tenant_connections DROP CONSTRAINT IF EXISTS tenant_connections_tenant_id_fkey;
ALTER TABLE schema_chunks DROP CONSTRAINT IF EXISTS schema_chunks_tenant_id_fkey;
ALTER TABLE tenant_glossary DROP CONSTRAINT IF EXISTS tenant_glossary_tenant_id_fkey;

ALTER TABLE pinned_widgets DROP CONSTRAINT IF EXISTS pinned_widgets_tenant_id_fkey;
ALTER TABLE pinned_widgets DROP CONSTRAINT IF EXISTS pinned_widgets_user_id_fkey;

ALTER TABLE briefing_send_log DROP CONSTRAINT IF EXISTS briefing_send_log_tenant_id_fkey;
ALTER TABLE briefing_send_log DROP CONSTRAINT IF EXISTS briefing_send_log_user_id_fkey;

-- Step 2: Convert ID columns in tenants and users to TEXT
ALTER TABLE tenants ALTER COLUMN id TYPE TEXT USING id::text;
ALTER TABLE users ALTER COLUMN id TYPE TEXT USING id::text;

-- Step 3: Convert foreign key columns across all tables to TEXT
ALTER TABLE conversations ALTER COLUMN tenant_id TYPE TEXT USING tenant_id::text;
ALTER TABLE conversations ALTER COLUMN user_id TYPE TEXT USING user_id::text;

ALTER TABLE turns ALTER COLUMN tenant_id TYPE TEXT USING tenant_id::text;
ALTER TABLE turns ALTER COLUMN user_id TYPE TEXT USING user_id::text;

ALTER TABLE sessions ALTER COLUMN tenant_id TYPE TEXT USING tenant_id::text;
ALTER TABLE sessions ALTER COLUMN user_id TYPE TEXT USING user_id::text;

ALTER TABLE user_snowflake_roles ALTER COLUMN tenant_id TYPE TEXT USING tenant_id::text;
ALTER TABLE user_snowflake_roles ALTER COLUMN user_id TYPE TEXT USING user_id::text;

ALTER TABLE tenant_connections ALTER COLUMN tenant_id TYPE TEXT USING tenant_id::text;
ALTER TABLE schema_chunks ALTER COLUMN tenant_id TYPE TEXT USING tenant_id::text;
ALTER TABLE tenant_glossary ALTER COLUMN tenant_id TYPE TEXT USING tenant_id::text;

ALTER TABLE pinned_widgets ALTER COLUMN tenant_id TYPE TEXT USING tenant_id::text;
ALTER TABLE pinned_widgets ALTER COLUMN user_id TYPE TEXT USING user_id::text;

ALTER TABLE briefing_send_log ALTER COLUMN tenant_id TYPE TEXT USING tenant_id::text;
ALTER TABLE briefing_send_log ALTER COLUMN user_id TYPE TEXT USING user_id::text;

-- Step 4: Create tenant_memberships table
CREATE TABLE IF NOT EXISTS tenant_memberships (
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'viewer',
  permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ,
  PRIMARY KEY (tenant_id, user_id)
);

-- Backfill tenant_memberships from legacy users shape if applicable
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'tenant_id') THEN
    INSERT INTO tenant_memberships (tenant_id, user_id, role, created_at)
    SELECT tenant_id::text, id::text, COALESCE(role, 'viewer'), created_at
    FROM users
    WHERE tenant_id IS NOT NULL
    ON CONFLICT (tenant_id, user_id) DO NOTHING;
    
    ALTER TABLE users DROP COLUMN tenant_id;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'role') THEN
    ALTER TABLE users DROP COLUMN role;
  END IF;
END $$;

ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- Drop rigid global email unique constraint to allow recreated Clerk users with same email
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key;
DROP INDEX IF EXISTS users_email_key;
CREATE UNIQUE INDEX IF NOT EXISTS users_active_email_key ON users(email) WHERE deleted_at IS NULL;

-- Step 5: Re-add FK constraints
ALTER TABLE conversations ADD CONSTRAINT conversations_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE conversations ADD CONSTRAINT conversations_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);

ALTER TABLE turns ADD CONSTRAINT turns_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE turns ADD CONSTRAINT turns_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);

ALTER TABLE sessions ADD CONSTRAINT sessions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE sessions ADD CONSTRAINT sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);

ALTER TABLE tenant_connections ADD CONSTRAINT tenant_connections_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE schema_chunks ADD CONSTRAINT schema_chunks_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE tenant_glossary ADD CONSTRAINT tenant_glossary_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);

ALTER TABLE pinned_widgets ADD CONSTRAINT pinned_widgets_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE pinned_widgets ADD CONSTRAINT pinned_widgets_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);

ALTER TABLE briefing_send_log ADD CONSTRAINT briefing_send_log_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
ALTER TABLE briefing_send_log ADD CONSTRAINT briefing_send_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);

-- Step 6: Update user_snowflake_roles primary key to composite (tenant_id, user_id)
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'user_snowflake_roles_pkey') THEN
    ALTER TABLE user_snowflake_roles DROP CONSTRAINT user_snowflake_roles_pkey;
  END IF;
END $$;

ALTER TABLE user_snowflake_roles ADD CONSTRAINT user_snowflake_roles_pkey PRIMARY KEY (tenant_id, user_id);

-- Step 7: Update admin views to work with TEXT tenant_id / user_id
CREATE OR REPLACE VIEW admin_glossary_view AS
  SELECT 
    tg.tenant_id,
    COALESCE(t.name, tg.tenant_id) AS workspace_name,
    tg.metric_synonyms,
    tg.table_synonyms,
    tg.synonym_hits,
    tg.total_hits,
    tg.updated_at
  FROM tenant_glossary tg
  LEFT JOIN tenants t ON t.id = tg.tenant_id;

CREATE OR REPLACE VIEW admin_workspaces_view AS
  SELECT
    t.id,
    t.name AS workspace_name,
    COUNT(DISTINCT tg.tenant_id) > 0 AS has_glossary,
    COUNT(DISTINCT tu.turn_id) AS total_turns,
    MAX(tu.created_at) AS last_active_at
  FROM tenants t
  LEFT JOIN tenant_glossary tg ON tg.tenant_id = t.id
  LEFT JOIN turns tu ON tu.tenant_id = t.id
  GROUP BY t.id, t.name;
