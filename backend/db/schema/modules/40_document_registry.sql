-- Data ingestion: processed document registry (GCS path, hash, chunk count)

CREATE TABLE IF NOT EXISTS document_registry (
    document_id VARCHAR(512) PRIMARY KEY,
    opportunity_id VARCHAR(64) NOT NULL REFERENCES opportunities (opportunity_id) ON DELETE CASCADE,
    source_type VARCHAR(64) NOT NULL,
    gcs_path TEXT NOT NULL,
    doc_hash VARCHAR(128) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ,
    total_chunks INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_document_registry_opp ON document_registry (opportunity_id);
CREATE INDEX IF NOT EXISTS idx_document_registry_source ON document_registry (opportunity_id, source_type);
