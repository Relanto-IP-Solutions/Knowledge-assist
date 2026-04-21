-- Organization layer: teams

CREATE TABLE IF NOT EXISTS teams (
    id SERIAL PRIMARY KEY,
    name VARCHAR(512) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

-- Add FK after teams exists (opportunities is created in earlier module).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_opportunities_team'
    ) THEN
        ALTER TABLE opportunities
        ADD CONSTRAINT fk_opportunities_team
        FOREIGN KEY (team_id) REFERENCES teams (id);
    END IF;
END $$;
