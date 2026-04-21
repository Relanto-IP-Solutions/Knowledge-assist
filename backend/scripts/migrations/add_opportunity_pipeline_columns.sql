-- One-time migration: pipeline columns on ``opportunities`` (sync / ingestion / extraction).
-- Run against Cloud SQL if your table was created before these columns existed.
-- Safe to run multiple times (IF NOT EXISTS).

ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS status VARCHAR(64);
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS total_documents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS processed_documents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS last_extraction_at TIMESTAMPTZ;
