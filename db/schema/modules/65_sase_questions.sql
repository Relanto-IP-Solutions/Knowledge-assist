-- Question framework: operational question bank (runtime uses this, not legacy `questions`)

CREATE TABLE IF NOT EXISTS sase_questions (
    q_id VARCHAR(64) PRIMARY KEY,
    api_name VARCHAR(256),
    question TEXT,
    batch VARCHAR(128) REFERENCES sase_batches (batch_id),
    answer_type VARCHAR(64),
    requirement_type VARCHAR(64),
    section_prefix VARCHAR(256),
    seq_in_section INTEGER,
    dependent_on VARCHAR(256),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ,
    question_prompt TEXT,
    question_embedding vector(768),
    final_answer_id VARCHAR(256),
    section VARCHAR(256)
);

CREATE INDEX IF NOT EXISTS idx_sase_questions_batch ON sase_questions (batch);
CREATE INDEX IF NOT EXISTS idx_sase_questions_section ON sase_questions (section);
