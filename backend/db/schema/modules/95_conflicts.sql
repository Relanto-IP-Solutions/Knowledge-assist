-- Quality control: conflicting candidate answers

CREATE TABLE IF NOT EXISTS conflicts (
    conflict_id VARCHAR(64) NOT NULL,
    answer_id VARCHAR(256) NOT NULL,
    opportunity_id VARCHAR(64) NOT NULL,
    question_id VARCHAR(64) NOT NULL,
    conflicting_value TEXT NOT NULL,
    value_display TEXT,
    confidence_score DOUBLE PRECISION,
    source_type VARCHAR(32),
    source_file VARCHAR(1024),
    source_name VARCHAR(512),
    reasoning TEXT,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ,
    resolved_by VARCHAR(64),
    resolved_at TIMESTAMPTZ,
    resolution_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confidence DOUBLE PRECISION,

    CONSTRAINT pk_conflicts PRIMARY KEY (opportunity_id, answer_id, conflict_id),
    CONSTRAINT fk_conflicts_answer
        FOREIGN KEY (opportunity_id, answer_id)
        REFERENCES answers (opportunity_id, answer_id) ON DELETE CASCADE,
    CONSTRAINT chk_conflicts_status
        CHECK (status IN ('pending', 'resolved', 'ignored'))
);

CREATE INDEX IF NOT EXISTS idx_conflicts_opp_q ON conflicts (opportunity_id, question_id);
CREATE INDEX IF NOT EXISTS idx_conflicts_opp_q_status ON conflicts (opportunity_id, question_id, status);
