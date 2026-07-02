CREATE TABLE IF NOT EXISTS tenants (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  email TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK (role IN ('viewer', 'admin')),
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

CREATE TABLE IF NOT EXISTS turns (
  id UUID PRIMARY KEY,
  conversation_id UUID NOT NULL REFERENCES conversations(id),
  user_id UUID NOT NULL REFERENCES users(id),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  user_input TEXT NOT NULL,
  raw_transcript TEXT,
  deepgram_confidence_raw DOUBLE PRECISION,
  generated_sql TEXT NOT NULL,
  result_json JSONB NOT NULL,
  chart_type TEXT NOT NULL,
  chart_rationale TEXT NOT NULL,
  confidence_tier TEXT NOT NULL,
  composite_score DOUBLE PRECISION NOT NULL,
  clarification_triggered BOOLEAN NOT NULL DEFAULT false,
  quality_flag TEXT NOT NULL DEFAULT 'ok' CHECK (quality_flag IN ('ok', 'low')),
  source TEXT NOT NULL DEFAULT 'user' CHECK (source IN ('user', 'scheduled')),
  input_modality TEXT NOT NULL CHECK (input_modality IN ('voice', 'text')),
  latency_ms INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clarifications (
  id UUID PRIMARY KEY,
  turn_id UUID NOT NULL REFERENCES turns(id),
  prompt_sent TEXT NOT NULL,
  user_choice TEXT,
  resolution_type TEXT NOT NULL CHECK (resolution_type IN ('option_selected', 'escaped', 'timeout')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
