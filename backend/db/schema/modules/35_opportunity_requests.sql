-- Business workflow layer: opportunity request approvals
-- Captures requester submission and admin decision lifecycle.

CREATE TABLE IF NOT EXISTS opportunity_requests (
    request_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    organization_name VARCHAR(512),
    opportunity_title VARCHAR(512) NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    admin_remarks TEXT,
    reviewed_at TIMESTAMPTZ,
    reviewed_by INTEGER REFERENCES users (id) ON DELETE RESTRICT,
    created_opportunity_id INTEGER REFERENCES opportunities (id) ON DELETE SET NULL,
    CONSTRAINT chk_opportunity_requests_status
        CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    CONSTRAINT chk_opportunity_requests_review_state
        CHECK (
            (status = 'PENDING' AND reviewed_at IS NULL AND reviewed_by IS NULL)
            OR (status IN ('APPROVED', 'REJECTED') AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL)
        ),
    CONSTRAINT chk_opportunity_requests_rejection_remarks
        CHECK (
            status <> 'REJECTED'
            OR (admin_remarks IS NOT NULL AND btrim(admin_remarks) <> '')
        ),
    CONSTRAINT chk_opportunity_requests_approved_link
        CHECK (
            status <> 'APPROVED'
            OR created_opportunity_id IS NOT NULL
        )
);

ALTER TABLE opportunity_requests
    ADD COLUMN IF NOT EXISTS organization_name VARCHAR(512);

CREATE INDEX IF NOT EXISTS idx_opportunity_requests_status_submitted
    ON opportunity_requests (status, submitted_at DESC);

CREATE INDEX IF NOT EXISTS idx_opportunity_requests_user_submitted
    ON opportunity_requests (user_id, submitted_at DESC);

CREATE INDEX IF NOT EXISTS idx_opportunity_requests_reviewed_by
    ON opportunity_requests (reviewed_by);

CREATE INDEX IF NOT EXISTS idx_opportunity_requests_created_opportunity
    ON opportunity_requests (created_opportunity_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_opportunity_requests_approved_link'
          AND conrelid = 'opportunity_requests'::regclass
    ) THEN
        ALTER TABLE opportunity_requests
            ADD CONSTRAINT chk_opportunity_requests_approved_link
            CHECK (
                status <> 'APPROVED'
                OR created_opportunity_id IS NOT NULL
            );
    END IF;
END
$$;