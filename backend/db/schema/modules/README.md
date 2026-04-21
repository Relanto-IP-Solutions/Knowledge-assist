# Modular DB Schema (`db/schema/modules`)

This folder is the source of truth for PostgreSQL schema DDL.

## Module inventory (current files, numeric order)

1. `00_extensions.sql`
2. `10_users.sql`
3. `20_opportunities.sql`
4. `25_user_connections.sql`
5. `30_opportunity_sources.sql`
6. `40_document_registry.sql`
7. `50_chunk_registry.sql`
8. `60_sase_batches.sql`
9. `65_sase_questions.sql`
10. `70_sase_picklist_options.sql`
11. `80_answers.sql`
12. `85_answer_versions.sql`
13. `90_citations.sql`
14. `95_conflicts.sql`
15. `97_opportunity_question_answers.sql`
16. `98_feedback.sql`
17. `99_teams.sql`
18. `99_team_members.sql`
19. `99_audit_log.sql`

## Current apply script behavior

`scripts/db/apply_modular_schema.py` applies modules in a fixed internal order.
Use the module inventory above as the canonical file list.

Notes:
- `00_extensions.sql` exists and enables `vector`; run before tables that use vector columns.

## How to apply

From repo root:

- `uv run python scripts/db/apply_modular_schema.py`
- `uv run python scripts/db/check_schema_drift.py` (alerts if live schema changed manually)

Behavior:
- Applies files in explicit order from `scripts/db/apply_modular_schema.py`.
- Uses idempotent DDL (`IF NOT EXISTS`) where supported.
- Uses DB env loaded from `configs/.env` and `configs/secrets/.env`.
- Writes `db/schema/last_schema_baseline.json` after apply (used by drift checks).

## How to verify drift (live DB vs modules)

Run these SQL checks against the target DB.

### 1) Tables

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
```

### 2) Columns and defaults

```sql
SELECT
  table_name,
  column_name,
  data_type,
  is_nullable,
  column_default
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position;
```

### 3) Constraints (PK/FK/UNIQUE/CHECK)

```sql
SELECT
  tc.table_name,
  tc.constraint_name,
  tc.constraint_type
FROM information_schema.table_constraints tc
WHERE tc.table_schema = 'public'
ORDER BY tc.table_name, tc.constraint_type, tc.constraint_name;
```

FK details:

```sql
SELECT
  tc.table_name,
  kcu.column_name,
  ccu.table_name AS foreign_table_name,
  ccu.column_name AS foreign_column_name,
  tc.constraint_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
 AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu
  ON tc.constraint_name = ccu.constraint_name
 AND tc.table_schema = ccu.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_schema = 'public'
ORDER BY tc.table_name, tc.constraint_name;
```

### 4) Indexes

```sql
SELECT schemaname, tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;
```

## Operating rules

- Update schema in `.sql` modules first.
- Keep runtime ORM mappings aligned with tables they query.
- Avoid duplicate schema ownership across SQL and Python DDL creators.
