-- Migration 008: Clerk-Native Multi-Tenancy (String IDs, Tenant Memberships, Composite Snowflake Roles)

-- Step 1: Remove dependent views
DROP VIEW IF EXISTS admin_glossary_view CASCADE;
DROP VIEW IF EXISTS admin_workspaces_view CASCADE;

-- Step 1b: Dynamically drop ALL foreign key constraints referencing tenants.id or users.id across ALL tables
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (
        SELECT DISTINCT tc.table_name, tc.constraint_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
          ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage AS ccu
          ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND ccu.table_name IN ('tenants', 'users')
    ) LOOP
        EXECUTE format('ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I;', r.table_name, r.constraint_name);
    END LOOP;
END $$;

-- Step 2 & 3: Dynamically convert ANY tenant_id or user_id column across ALL tables to TEXT
DO $$
DECLARE
    r RECORD;
BEGIN
    -- Convert tenant_id and user_id in all public tables
    FOR r IN (
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE column_name IN ('tenant_id', 'user_id')
          AND table_schema = 'public'
          AND data_type != 'text'
    ) LOOP
        EXECUTE format('ALTER TABLE %I ALTER COLUMN %I TYPE TEXT USING %I::text;', r.table_name, r.column_name, r.column_name);
    END LOOP;
    
    -- Convert primary keys tenants.id and users.id to TEXT
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'tenants' AND column_name = 'id' AND data_type != 'text') THEN
        ALTER TABLE tenants ALTER COLUMN id TYPE TEXT USING id::text;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'id' AND data_type != 'text') THEN
        ALTER TABLE users ALTER COLUMN id TYPE TEXT USING id::text;
    END IF;
END $$;

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

-- Step 5: Re-add FK constraints for core tables if present
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'conversations') THEN
    ALTER TABLE conversations ADD CONSTRAINT conversations_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
    ALTER TABLE conversations ADD CONSTRAINT conversations_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'turns') THEN
    ALTER TABLE turns ADD CONSTRAINT turns_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
    ALTER TABLE turns ADD CONSTRAINT turns_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'sessions') THEN
    ALTER TABLE sessions ADD CONSTRAINT sessions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
    ALTER TABLE sessions ADD CONSTRAINT sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tenant_connections') THEN
    ALTER TABLE tenant_connections ADD CONSTRAINT tenant_connections_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'schema_chunks') THEN
    ALTER TABLE schema_chunks ADD CONSTRAINT schema_chunks_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tenant_glossary') THEN
    ALTER TABLE tenant_glossary ADD CONSTRAINT tenant_glossary_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'pinned_widgets') THEN
    ALTER TABLE pinned_widgets ADD CONSTRAINT pinned_widgets_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
    ALTER TABLE pinned_widgets ADD CONSTRAINT pinned_widgets_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'briefing_send_log') THEN
    ALTER TABLE briefing_send_log ADD CONSTRAINT briefing_send_log_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
    ALTER TABLE briefing_send_log ADD CONSTRAINT briefing_send_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'briefings') THEN
    ALTER TABLE briefings ADD CONSTRAINT briefings_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES tenants(id);
    ALTER TABLE briefings ADD CONSTRAINT briefings_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);
  END IF;
END $$;

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
