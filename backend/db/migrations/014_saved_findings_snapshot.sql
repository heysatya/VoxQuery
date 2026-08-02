-- Migration 014: Saved Findings Snapshot
-- Converts "Pinned analyses" from fragile JOIN-based references to true snapshots.
-- The turn_id FK becomes nullable so saved findings survive turn deletion.

ALTER TABLE pinned_widgets
  ADD COLUMN IF NOT EXISTS original_question       TEXT,
  ADD COLUMN IF NOT EXISTS chart_type               TEXT,
  ADD COLUMN IF NOT EXISTS snapshot_result_json     JSONB,
  ADD COLUMN IF NOT EXISTS snapshot_narrative       TEXT,
  ADD COLUMN IF NOT EXISTS snapshot_generated_sql   TEXT,
  ADD COLUMN IF NOT EXISTS snapshot_taken_at        TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS note                     TEXT,
  ADD COLUMN IF NOT EXISTS snapshot_headline_value  DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS snapshot_headline_label  TEXT;

-- turn_id becomes optional context for "Check now" / "Ask again", not a hard
-- dependency for display. Constraint name confirmed via Step 0 pre-flight query.
ALTER TABLE pinned_widgets DROP CONSTRAINT IF EXISTS pinned_widgets_turn_id_fkey;
ALTER TABLE pinned_widgets
  ADD CONSTRAINT pinned_widgets_turn_id_fkey
  FOREIGN KEY (turn_id) REFERENCES turns(turn_id) ON DELETE SET NULL;
ALTER TABLE pinned_widgets ALTER COLUMN turn_id DROP NOT NULL;

-- Best-effort backfill for existing rows where the source turn still exists.
-- Rows where the join finds nothing are left with snapshot_result_json = NULL —
-- the frontend renders these with "predates snapshot storage" copy,
-- not the old "unavailable" wording.
UPDATE pinned_widgets w
SET snapshot_result_json     = t.full_result,
    original_question        = t.user_input,
    chart_type                = t.chart_type,
    snapshot_generated_sql   = t.generated_sql,
    snapshot_taken_at         = w.created_at
FROM turns t
WHERE w.turn_id = t.turn_id AND w.snapshot_result_json IS NULL;
