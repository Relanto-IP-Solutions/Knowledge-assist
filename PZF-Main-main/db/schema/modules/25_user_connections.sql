-- OAuth layer: per-user connector tokens and scope grants
-- Supports per-provider OAuth credentials without bloating users table.

CREATE TABLE IF NOT EXISTS user_connections (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    provider VARCHAR(50) NOT NULL,
    access_token TEXT,
    refresh_token TEXT,
    granted_scopes JSONB,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING_AUTHORIZATION',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_user_connections_status CHECK (status IN ('active', 'expired'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_connections_user_provider
    ON user_connections (user_id, provider);

CREATE INDEX IF NOT EXISTS idx_user_connections_user_id
    ON user_connections (user_id);

CREATE INDEX IF NOT EXISTS idx_user_connections_provider
    ON user_connections (provider);

CREATE INDEX IF NOT EXISTS idx_user_connections_status
    ON user_connections (status);

CREATE INDEX IF NOT EXISTS idx_user_connections_expires_at
    ON user_connections (expires_at);

CREATE INDEX IF NOT EXISTS idx_user_connections_scopes
    ON user_connections USING GIN (granted_scopes);

CREATE OR REPLACE FUNCTION update_user_connections_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_user_connections_updated_at ON user_connections;
CREATE TRIGGER trg_update_user_connections_updated_at
BEFORE UPDATE ON user_connections
FOR EACH ROW
EXECUTE FUNCTION update_user_connections_updated_at();
