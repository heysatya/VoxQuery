ALTER TABLE clarifications DROP CONSTRAINT IF EXISTS clarifications_resolution_type_check;
ALTER TABLE clarifications ADD CONSTRAINT clarifications_resolution_type_check
  CHECK (resolution_type IN ('option_selected', 'escaped', 'timeout'));