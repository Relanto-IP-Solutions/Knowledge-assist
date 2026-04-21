-- Answer system: version history

CREATE TABLE IF NOT EXISTS answer_versions (
    version_id VARCHAR(320) NOT NULL,
    answer_id VARCHAR(256) NOT NULL,
    opportunity_id VARCHAR(64) NOT NULL,
    question_id VARCHAR(64) NOT NULL,
    version BIGINT NOT NULL,
    answer_text TEXT,
    answer_number DOUBLE PRECISION,
    answer_date DATE,
    answer_boolean BOOLEAN,
    answer_picklist VARCHAR(512),
    answer_multi JSONB,
    answer_display TEXT,
    confidence_score DOUBLE PRECISION,
    reasoning TEXT,
    change_type VARCHAR(32) NOT NULL,
    change_reason TEXT,
    changed_by VARCHAR(64) NOT NULL,
    previous_value TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ,
    confidence DOUBLE PRECISION,
    created_by VARCHAR(64),
    created_by_type VARCHAR(16) DEFAULT 'ai',

    CONSTRAINT pk_answer_versions PRIMARY KEY (opportunity_id, answer_id, version),
    CONSTRAINT fk_answer_versions_answer
        FOREIGN KEY (opportunity_id, answer_id)
        REFERENCES answers (opportunity_id, answer_id) ON DELETE CASCADE,
    CONSTRAINT chk_answer_versions_change_type
        CHECK (
            lower(change_type) IN (
                'initial',
                'extraction',
                'user_override',
                'conflict_resolution'
            )
        ),
    CONSTRAINT chk_answer_versions_created_by_type
        CHECK (created_by_type IN ('ai', 'user'))
);

CREATE INDEX IF NOT EXISTS idx_answer_versions_lookup
    ON answer_versions (opportunity_id, answer_id);
