-- Migration 013: Ensure nullable columns on turns are truly nullable.
-- Idempotent: DROP NOT NULL is safe even if already nullable.
-- Fixes: NotNullViolationError on chart_type when initial turn is persisted
-- before the pipeline has had a chance to resolve a chart recommendation.

ALTER TABLE turns ALTER COLUMN chart_type        DROP NOT NULL;
ALTER TABLE turns ALTER COLUMN chart_rationale   DROP NOT NULL;
ALTER TABLE turns ALTER COLUMN confidence_tier   DROP NOT NULL;
ALTER TABLE turns ALTER COLUMN composite_score   DROP NOT NULL;
ALTER TABLE turns ALTER COLUMN result_json       DROP NOT NULL;
ALTER TABLE turns ALTER COLUMN input_modality    DROP NOT NULL;
ALTER TABLE turns ALTER COLUMN generated_sql     DROP NOT NULL;
