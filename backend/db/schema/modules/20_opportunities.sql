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

ALTER TABLE opportunities
    ADD COLUMN IF NOT EXISTS team_id INTEGER;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'unique_opportunity_id'
    ) THEN
        ALTER TABLE opportunities
            ADD CONSTRAINT unique_opportunity_id UNIQUE (opportunity_id);
    END IF;
END $$;

-- Generate human-friendly business ids (oid0001, oid0002, ...) in the DB.
-- This lets the API accept only `name` and return the generated opportunity_id.
CREATE SEQUENCE IF NOT EXISTS opportunity_oid_seq START 1;

SELECT setval(
  'opportunity_oid_seq',
  COALESCE(
    (
      SELECT MAX(CAST(SUBSTRING(opportunity_id FROM 4) AS INTEGER))
      FROM opportunities
      WHERE opportunity_id ~ '^oid[0-9]+$'
    ),
    0
  ) + 1,
  false
);

ALTER TABLE opportunities
    ALTER COLUMN opportunity_id
    SET DEFAULT ('oid' || lpad(nextval('opportunity_oid_seq')::text, 4, '0'));

CREATE UNIQUE INDEX IF NOT EXISTS unique_opportunity_name
    ON opportunities (LOWER(name));

CREATE INDEX IF NOT EXISTS idx_opportunities_owner ON opportunities (owner_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_team_id ON opportunities (team_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities (status);
CREATE INDEX IF NOT EXISTS idx_opportunities_updated ON opportunities (updated_at DESC);
-- list_opportunity_ids: ORDER BY created_at DESC, opportunity_id ASC with filters
CREATE INDEX IF NOT EXISTS idx_opportunities_created_at_id ON opportunities (created_at DESC, opportunity_id ASC);
