-- PR-2 / D18: Bottom-Up DIA list-query indexes.
-- Apply with:
--   psql -h localhost -U postgres -d "Universal_Viewer" -f "back/migrations/20260522_bu_identification_match_indexes.sql"

CREATE INDEX IF NOT EXISTS idx_im_dataset_q
    ON identification_matches(dataset_id, q_value);

CREATE INDEX IF NOT EXISTS idx_im_dataset_run
    ON identification_matches(dataset_id, run_id);

