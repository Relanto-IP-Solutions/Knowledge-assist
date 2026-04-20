-- Indexes to reduce latency on GET /opportunities/ids
-- Safe to run multiple times (IF NOT EXISTS).

-- Supports ORDER BY opportunities.created_at DESC, opportunity_id ASC
CREATE INDEX IF NOT EXISTS idx_opportunities_created_at_id
ON opportunities (created_at DESC, opportunity_id ASC);

-- Supports aggregations on answers for a limited set of opportunity_ids.
-- Most reads filter to status='active' and split by is_user_override.
CREATE INDEX IF NOT EXISTS idx_answers_opp_active_override
ON answers (opportunity_id, is_user_override)
WHERE status = 'active';

