-- Add hit tracking to tenant_glossary
ALTER TABLE tenant_glossary 
  ADD COLUMN IF NOT EXISTS synonym_hits JSONB NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS total_hits INTEGER NOT NULL DEFAULT 0;

-- Admin glossary view with workspace names
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

-- Admin workspaces view  
CREATE OR REPLACE VIEW admin_workspaces_view AS
  SELECT
    t.id,
    t.name AS workspace_name,
    COUNT(DISTINCT tg.tenant_id) > 0 AS has_glossary,
    COUNT(DISTINCT tu.id) AS total_turns,
    MAX(tu.created_at) AS last_active_at
  FROM tenants t
  LEFT JOIN tenant_glossary tg ON tg.tenant_id = t.id
  LEFT JOIN turns tu ON tu.tenant_id = t.id
  GROUP BY t.id, t.name;
