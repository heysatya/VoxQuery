-- Migration 007: WOW Features Foundation (Session/Turn Persistence, User Preferences, Pinned Widgets, Briefing Send Log)

CREATE TABLE IF NOT EXISTS sessions (
  session_id      UUID PRIMARY KEY,
  tenant_id       UUID NOT NULL REFERENCES tenants(id),
  user_id         UUID NOT NULL REFERENCES users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_active_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ensure turns table has all required columns for TurnRecord persistence
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

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'turns' AND column_name = 'id')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'turns' AND column_name = 'turn_id') THEN
    ALTER TABLE turns RENAME COLUMN id TO turn_id;
  END IF;
END $$;

ALTER TABLE turns ADD COLUMN IF NOT EXISTS session_id UUID REFERENCES sessions(session_id) ON DELETE CASCADE;
ALTER TABLE turns ADD COLUMN IF NOT EXISTS parent_turn_id UUID REFERENCES turns(turn_id);
ALTER TABLE turns ADD COLUMN IF NOT EXISTS source_tables TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE turns ADD COLUMN IF NOT EXISTS filter_predicates JSONB NOT NULL DEFAULT '[]';
ALTER TABLE turns ADD COLUMN IF NOT EXISTS full_result JSONB;
ALTER TABLE turns ADD COLUMN IF NOT EXISTS anomalies JSONB NOT NULL DEFAULT '[]';
ALTER TABLE turns ADD COLUMN IF NOT EXISTS proactive_questions JSONB NOT NULL DEFAULT '[]';
ALTER TABLE turns ADD COLUMN IF NOT EXISTS completed BOOLEAN NOT NULL DEFAULT false;

-- Drop NOT NULL constraints on turns table from migration 001 if table pre-existed
ALTER TABLE turns ALTER COLUMN result_json DROP NOT NULL;
ALTER TABLE turns ALTER COLUMN input_modality DROP NOT NULL;
ALTER TABLE turns ALTER COLUMN chart_type DROP NOT NULL;
ALTER TABLE turns ALTER COLUMN chart_rationale DROP NOT NULL;
ALTER TABLE turns ALTER COLUMN confidence_tier DROP NOT NULL;
ALTER TABLE turns ALTER COLUMN composite_score DROP NOT NULL;

CREATE INDEX IF NOT EXISTS idx_turns_session_created ON turns (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_turns_tenant ON turns (tenant_id);
CREATE INDEX IF NOT EXISTS idx_turns_parent ON turns (parent_turn_id);

ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS timezone TEXT NOT NULL DEFAULT 'UTC';

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

CREATE TABLE IF NOT EXISTS briefing_send_log (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id),
  tenant_id   UUID NOT NULL REFERENCES tenants(id),
  send_date   DATE NOT NULL,
  status      TEXT NOT NULL DEFAULT 'sent',
  error       TEXT,
  sent_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, send_date)
);
