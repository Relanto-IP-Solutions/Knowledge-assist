-- Evidence: citations tied to answers (and optional conflict linkage)

CREATE TABLE IF NOT EXISTS citations (
    citation_id VARCHAR(64) NOT NULL,
    answer_id VARCHAR(256) NOT NULL,
    conflict_id VARCHAR(64),
    opportunity_id VARCHAR(64) NOT NULL,
    question_id VARCHAR(64) NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    source_file VARCHAR(1024),
    source_name VARCHAR(512),
    document_date DATE,
    chunk_id VARCHAR(128),
    quote TEXT,
    context TEXT,
    page_number BIGINT,
    timestamp_str VARCHAR(64),
    speaker VARCHAR(256),
    relevance_score DOUBLE PRECISION DEFAULT 0.0,
    is_primary BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version_id VARCHAR(320),

    CONSTRAINT pk_citations PRIMARY KEY (opportunity_id, answer_id, citation_id),
    CONSTRAINT fk_citations_answer
        FOREIGN KEY (opportunity_id, answer_id)
        REFERENCES answers (opportunity_id, answer_id) ON DELETE CASCADE,
    CONSTRAINT fk_citations_chunk_id
        FOREIGN KEY (chunk_id)
        REFERENCES chunk_registry (chunk_id) ON DELETE SET NULL,
    CONSTRAINT chk_citations_source_type
        CHECK (
            source_type IN (
                'slack',
                'zoom',
                'pdf',
                'docx',
                'pptx',
                'email',
                'unknown'
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_citations_answer ON citations (opportunity_id, answer_id);
CREATE INDEX IF NOT EXISTS idx_citations_chunk_id ON citations (chunk_id);
