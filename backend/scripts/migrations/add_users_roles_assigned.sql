-- One-time migration: add users.roles_assigned (multi-role RBAC).
-- Safe to run multiple times (IF NOT EXISTS / idempotent updates).

ALTER TABLE users
ADD COLUMN IF NOT EXISTS roles_assigned TEXT[];

-- Backfill roles_assigned from legacy role when roles_assigned is null/empty.
-- Note: role may be an enum/custom type in some DBs; cast to text for trimming.
UPDATE users
SET roles_assigned = ARRAY[role::text]
WHERE (roles_assigned IS NULL OR array_length(roles_assigned, 1) IS NULL)
  AND role IS NOT NULL
  AND BTRIM(role::text) <> '';

