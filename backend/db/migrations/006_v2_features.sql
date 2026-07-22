-- Additive migration for VoxQuery V2.0 features

CREATE TABLE IF NOT EXISTS briefings (
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  date TEXT NOT NULL,
  greeting TEXT NOT NULL,
  summary_narrative TEXT NOT NULL,
  kpis_json JSONB NOT NULL,
  anomalies_json JSONB NOT NULL,
  proactive_insights_json JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, date)
);

CREATE TABLE IF NOT EXISTS user_preferences (
  user_id UUID PRIMARY KEY REFERENCES users(id),
  email_briefing_enabled BOOLEAN NOT NULL DEFAULT false,
  email TEXT,
  delivery_time TEXT NOT NULL DEFAULT '08:00',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
