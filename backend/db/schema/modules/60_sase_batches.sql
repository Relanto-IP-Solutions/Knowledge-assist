-- Question framework: batch metadata for agent / prompts

CREATE TABLE IF NOT EXISTS sase_batches (
    batch_id VARCHAR(128) PRIMARY KEY,
    batch_label VARCHAR(512),
    section_path TEXT,
    batch_order INTEGER,
    description TEXT,
    section_level_prompt TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ
);
