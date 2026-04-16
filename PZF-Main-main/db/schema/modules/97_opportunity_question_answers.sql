-- Scoped final answer per (opportunity, question).
-- Replaces global tracking on `sase_questions.final_answer_id`.

CREATE TABLE IF NOT EXISTS opportunity_question_answers (
    opportunity_id VARCHAR(64) NOT NULL,
    question_id VARCHAR(64) NOT NULL,
    final_answer_id VARCHAR(256) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_opportunity_question_answers
        PRIMARY KEY (opportunity_id, question_id),
    CONSTRAINT fk_oqa_opportunity
        FOREIGN KEY (opportunity_id)
        REFERENCES opportunities (opportunity_id) ON DELETE CASCADE,
    CONSTRAINT fk_oqa_question
        FOREIGN KEY (question_id)
        REFERENCES sase_questions (q_id) ON DELETE CASCADE,
    CONSTRAINT fk_oqa_answer
        FOREIGN KEY (opportunity_id, final_answer_id)
        REFERENCES answers (opportunity_id, answer_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_oqa_final_answer
    ON opportunity_question_answers (opportunity_id, final_answer_id);
