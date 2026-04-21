-- Answer system: composite PK (opportunity_id, answer_id) matches RagDataService ON CONFLICT patterns
-- question_id references sase_questions (no legacy `questions` table).

CREATE TABLE IF NOT EXISTS answers (
    answer_id VARCHAR(256) NOT NULL,
    opportunity_id VARCHAR(64) NOT NULL,
    question_id VARCHAR(64) NOT NULL,
    answer_text TEXT,
    answer_number DOUBLE PRECISION,
    answer_date DATE,
    answer_boolean BOOLEAN,
    answer_picklist VARCHAR(512),
    answer_multi JSONB,
    answer_display TEXT,
    confidence_score DOUBLE PRECISION DEFAULT 0.0,
    status VARCHAR(32) NOT NULL DEFAULT 'inactive',
    needs_review BOOLEAN NOT NULL DEFAULT FALSE,
    has_conflicts BOOLEAN NOT NULL DEFAULT FALSE,
    conflict_count BIGINT DEFAULT 0,
    source_count BIGINT DEFAULT 0,
    primary_source VARCHAR(512),
    reasoning TEXT,
    current_version BIGINT NOT NULL DEFAULT 1,
    extraction_version BIGINT,
    is_user_override BOOLEAN NOT NULL DEFAULT FALSE,
    overridden_by VARCHAR(256),
    overridden_at TIMESTAMPTZ,
    override_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confidence DOUBLE PRECISION DEFAULT 0.0,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    answer_embedding vector(768),
    has_embeddings BOOLEAN NOT NULL DEFAULT FALSE,

    CONSTRAINT pk_answers PRIMARY KEY (opportunity_id, answer_id),
    CONSTRAINT fk_answers_opportunity
        FOREIGN KEY (opportunity_id) REFERENCES opportunities (opportunity_id) ON DELETE CASCADE,
    CONSTRAINT fk_answers_question
        FOREIGN KEY (question_id) REFERENCES sase_questions (q_id),
    CONSTRAINT chk_answers_status
        CHECK (status IN ('pending', 'active', 'inactive')),
    CONSTRAINT chk_answers_confidence
        CHECK (confidence_score IS NULL OR (confidence_score >= 0.0 AND confidence_score <= 1.0)),
    CONSTRAINT chk_answers_single_typed_value
        CHECK (
            ((answer_text IS NOT NULL)::int +
             (answer_number IS NOT NULL)::int +
             (answer_date IS NOT NULL)::int +
             (answer_boolean IS NOT NULL)::int +
             (answer_picklist IS NOT NULL)::int +
             (answer_multi IS NOT NULL)::int) <= 1
        )
);

CREATE INDEX IF NOT EXISTS idx_answers_question ON answers (question_id);
CREATE INDEX IF NOT EXISTS idx_answers_active ON answers (opportunity_id, question_id, is_active);
CREATE INDEX IF NOT EXISTS idx_answers_opp_question ON answers (opportunity_id, question_id);