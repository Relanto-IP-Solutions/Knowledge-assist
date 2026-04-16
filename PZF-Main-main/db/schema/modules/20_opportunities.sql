-- Business layer: opportunities
-- RAG paths use opportunities.opportunity_id (string business key) everywhere.
-- SQLAlchemy plugin routes use integer id + FK from opportunity_sources.

CREATE TABLE IF NOT EXISTS opportunities (
    id SERIAL PRIMARY KEY,
    opportunity_id VARCHAR(64) NOT NULL UNIQUE,
    name VARCHAR(512) NOT NULL,
    owner_id INTEGER NOT NULL REFERENCES users (id),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,

    status VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ,
    total_documents BIGINT NOT NULL DEFAULT 0,
    processed_documents BIGINT NOT NULL DEFAULT 0,
    last_extraction_at TIMESTAMPTZ,

    oid VARCHAR(128),
    team_id INTEGER
);

CREATE INDEX IF NOT EXISTS idx_opportunities_owner ON opportunities (owner_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities (status);
CREATE INDEX IF NOT EXISTS idx_opportunities_updated ON opportunities (updated_at DESC);
-- list_opportunity_ids: ORDER BY created_at DESC, opportunity_id ASC with filters
CREATE INDEX IF NOT EXISTS idx_opportunities_created_at_id ON opportunities (created_at DESC, opportunity_id ASC);
