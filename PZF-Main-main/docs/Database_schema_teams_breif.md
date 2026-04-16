# Database schema — team brief

This is a simple shareable brief for the finalized database schema.

## Source of truth

- Canonical DDL: `db/schema/modules/*.sql`
- Apply script: `scripts/db/apply_modular_schema.py`
- Drift check: `scripts/db/check_schema_drift.py`

## How to run

```bash
uv run python scripts/db/apply_modular_schema.py
uv run python scripts/db/check_schema_drift.py
```

## Final application tables (17)

1. `users`
2. `user_connections`
3. `teams`
4. `team_members`
5. `opportunities`
6. `opportunity_sources`
7. `document_registry`
8. `chunk_registry`
9. `sase_batches`
10. `sase_questions`
11. `sase_picklist_options`
12. `answers`
13. `answer_versions`
14. `citations`
15. `conflicts`
16. `feedback`
17. `audit_log`

## Notes

- The schema is managed only via module SQL + apply script.
- Avoid manual DDL changes in Cloud SQL Studio.
- Keep ORM/query code aligned with these tables.
