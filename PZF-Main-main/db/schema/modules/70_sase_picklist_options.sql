-- Question framework: picklist options keyed by sase_questions.q_id

CREATE TABLE IF NOT EXISTS sase_picklist_options (
    id SERIAL PRIMARY KEY,
    q_id TEXT NOT NULL REFERENCES sase_questions (q_id) ON DELETE CASCADE,
    option_value TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sase_picklist_q ON sase_picklist_options (q_id);
