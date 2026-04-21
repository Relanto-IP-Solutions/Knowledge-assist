-- Governance layer: append-only audit trail

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_user_id INTEGER REFERENCES users (id),
    action VARCHAR(128) NOT NULL,
    entity_type VARCHAR(128),
    entity_id VARCHAR(256),
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_audit_log_occurred ON audit_log (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log (entity_type, entity_id);
