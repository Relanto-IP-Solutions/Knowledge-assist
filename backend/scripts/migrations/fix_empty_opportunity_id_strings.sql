-- One-time repair: rows where opportunities.opportunity_id is '' or whitespace-only.
-- Postgres allows '' under NOT NULL VARCHAR; application code should never insert these.
--
-- Strategy: derive canonical oid<digits> from name using the same token pattern as
-- src/utils/opportunity_id.py (oid / opp_id + digits). Only updates when the computed
-- id does not already exist on another row (avoids unique violation).
--
-- Review the result in a transaction before COMMIT. If duplicates exist (same oid as an
-- older row), merge opportunity_sources to the canonical row manually, then DELETE dupes.

BEGIN;

WITH extracted AS (
    SELECT
        id,
        lower(name) AS lname
    FROM opportunities
    WHERE trim(coalesce(opportunity_id, '')) = ''
),
computed AS (
    SELECT
        id,
        CASE
            WHEN (regexp_match(lname, '(?:oid|opp[_-]?id)[_-]?([0-9]+)'))[1] IS NOT NULL
                THEN 'oid' || (regexp_match(lname, '(?:oid|opp[_-]?id)[_-]?([0-9]+)'))[1]
            ELSE NULL
        END AS new_oid
    FROM extracted
)
UPDATE opportunities o
SET opportunity_id = c.new_oid
FROM computed c
WHERE o.id = c.id
  AND c.new_oid IS NOT NULL
  AND trim(coalesce(o.opportunity_id, '')) = ''
  AND NOT EXISTS (
      SELECT 1
      FROM opportunities x
      WHERE x.opportunity_id = c.new_oid
        AND x.id <> o.id
  );

-- Optional: list rows still broken (need manual merge)
-- SELECT id, name, opportunity_id FROM opportunities WHERE trim(coalesce(opportunity_id, '')) = '';

COMMIT;
