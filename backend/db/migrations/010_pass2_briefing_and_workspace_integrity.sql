-- Pass 2: prevent duplicate saved analyses and make delivery idempotency tenant-safe.

DELETE FROM pinned_widgets a
USING pinned_widgets b
WHERE a.tenant_id = b.tenant_id
  AND a.user_id = b.user_id
  AND a.turn_id = b.turn_id
  AND a.id > b.id;

CREATE UNIQUE INDEX IF NOT EXISTS uq_pinned_widgets_tenant_user_turn
  ON pinned_widgets (tenant_id, user_id, turn_id);

ALTER TABLE briefing_send_log
  DROP CONSTRAINT IF EXISTS briefing_send_log_user_id_send_date_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_briefing_send_log_tenant_user_date
  ON briefing_send_log (tenant_id, user_id, send_date);

CREATE INDEX IF NOT EXISTS idx_briefing_send_log_status_date
  ON briefing_send_log (status, send_date);
