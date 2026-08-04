-- Pass 1: active tenant authorization and durable feedback state.

ALTER TABLE tenants ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

ALTER TABLE turns ADD COLUMN IF NOT EXISTS feedback_submitted BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_tenant_memberships_active_user
  ON tenant_memberships (tenant_id, user_id)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_turns_tenant_user_turn
  ON turns (tenant_id, user_id, turn_id);
