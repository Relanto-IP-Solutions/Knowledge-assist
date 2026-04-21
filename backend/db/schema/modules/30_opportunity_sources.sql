-- Business layer: per-opportunity connector sync state

CREATE TABLE IF NOT EXISTS opportunity_sources (
    id SERIAL PRIMARY KEY,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities (id) ON DELETE CASCADE,
    source_type VARCHAR(64) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING_AUTHORIZATION',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ,
    last_synced_at TIMESTAMPTZ,
    sync_checkpoint TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_opportunity_sources_status
        CHECK (status IN ('PENDING_AUTHORIZATION', 'ACTIVE', 'ERROR'))
);

CREATE INDEX IF NOT EXISTS idx_opportunity_sources_opp ON opportunity_sources (opportunity_id);
CREATE INDEX IF NOT EXISTS idx_opportunity_sources_type ON opportunity_sources (source_type);

ALTER TABLE opportunity_sources
    ADD COLUMN IF NOT EXISTS status VARCHAR(30) NOT NULL DEFAULT 'PENDING_AUTHORIZATION';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_opportunity_sources_status'
          AND conrelid = 'opportunity_sources'::regclass
    ) THEN
        ALTER TABLE opportunity_sources
            ADD CONSTRAINT chk_opportunity_sources_status
            CHECK (status IN ('PENDING_AUTHORIZATION', 'ACTIVE', 'ERROR'));
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_opportunity_sources_status ON opportunity_sources (status);
