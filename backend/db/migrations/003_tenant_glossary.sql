CREATE TABLE IF NOT EXISTS tenant_glossary (
  tenant_id UUID PRIMARY KEY REFERENCES tenants(id),
  metric_synonyms JSONB NOT NULL DEFAULT '{}',
  table_synonyms JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
