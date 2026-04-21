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

-- Generate human-friendly business ids (oid0001, oid0002, ...) in the DB.
-- This lets the API accept only `name` and return the generated opportunity_id.
CREATE SEQUENCE IF NOT EXISTS opportunity_oid_seq;

-- Align the sequence with existing rows (best-effort). If there are no existing
-- opportunities or ids don't contain digits, start from 1.
DO $$
BEGIN
    PERFORM setval(
        'opportunity_oid_seq',
        COALESCE(
            (
                SELECT
                    MAX(
                        NULLIF(regexp_replace(opportunity_id, '\D', '', 'g'), '')::bigint
                    )
                FROM opportunities
            ),
            0
        ) + 1,
        false
    );
EXCEPTION WHEN undefined_table THEN
    -- Table doesn't exist yet in this migration run; ignore.
    NULL;
END
$$;

ALTER TABLE opportunities
    ALTER COLUMN opportunity_id
    SET DEFAULT ('oid' || lpad(nextval('opportunity_oid_seq')::text, 4, '0'));

CREATE INDEX IF NOT EXISTS idx_opportunities_owner ON opportunities (owner_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities (status);
CREATE INDEX IF NOT EXISTS idx_opportunities_updated ON opportunities (updated_at DESC);
-- list_opportunity_ids: ORDER BY created_at DESC, opportunity_id ASC with filters
CREATE INDEX IF NOT EXISTS idx_opportunities_created_at_id ON opportunities (created_at DESC, opportunity_id ASC);
