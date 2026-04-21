-- Feedback: user QA on answers (idempotent inserts use composite conflict target)

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id TEXT NOT NULL,
    answer_id TEXT NOT NULL,
    opportunity_id TEXT NOT NULL,
    question_id TEXT,
    answer_version INTEGER,
    feedback_type INTEGER,
    comments TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ,

    CONSTRAINT pk_feedback PRIMARY KEY (opportunity_id, answer_id, feedback_id),
    CONSTRAINT fk_feedback_answer
        FOREIGN KEY (opportunity_id, answer_id)
        REFERENCES answers (opportunity_id, answer_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_feedback_opp ON feedback (opportunity_id);
