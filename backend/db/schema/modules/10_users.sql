-- Organization layer: users (OAuth + identity)
-- Matches Cloud SQL Studio shape; extends legacy ORM fields used by plugins.

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(512) NOT NULL UNIQUE,
    name VARCHAR(512),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    gmail_refresh_token TEXT,
    slack_access_token TEXT,
    zoom_account_id VARCHAR(256),
    zoom_client_id VARCHAR(256),
    zoom_client_secret TEXT,

    firebase_uid VARCHAR(128),
    drive_refresh_token TEXT,
    google_refresh_token TEXT,
    slack_team_id VARCHAR(128),

    role VARCHAR(64),
    roles_assigned TEXT[],
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
CREATE INDEX IF NOT EXISTS idx_users_firebase_uid ON users (firebase_uid);
