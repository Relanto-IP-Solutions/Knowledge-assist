-- Data ingestion: chunk text + embeddings (Vertex text-embedding-004 => 768 dims)

CREATE TABLE IF NOT EXISTS chunk_registry (
    chunk_id VARCHAR(512) PRIMARY KEY,
    document_id VARCHAR(512) NOT NULL REFERENCES document_registry (document_id) ON DELETE CASCADE,
    opportunity_id VARCHAR(64) NOT NULL REFERENCES opportunities (opportunity_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_hash VARCHAR(128) NOT NULL,
    datapoint_id VARCHAR(512),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    chunk_text TEXT,
    embedding vector(768),

    CONSTRAINT uq_chunk_registry_document_chunk UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunk_registry_opp ON chunk_registry (opportunity_id);
CREATE INDEX IF NOT EXISTS idx_chunk_registry_doc ON chunk_registry (document_id);
