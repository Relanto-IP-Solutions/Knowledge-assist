# Schema Usage Audit

This audit maps live schema tables to current Python code references in `src/`, plus migration-flow ownership status.

## Migration Ownership (Authoritative)

- **Keep as source of truth**
  - `db/schema/modules/*.sql` listed by `scripts/db/apply_modular_schema.py`
  - `scripts/db/apply_modular_schema.py`
  - `scripts/db/check_schema_drift.py` (compares live DB to `db/schema/last_schema_baseline.json`)
- **Deprecated / not used for live schema apply**
  - `scripts/setup/create_pg_tables.py` (disabled)
  - `scripts/create_plugin_auth_tables.py` (disabled)

## Table Usage in `src/`

### Keep (actively referenced)

- `users`
- `opportunities`
- `opportunity_sources`
- `answers`
- `answer_versions`
- `citations`
- `conflicts`
- `feedback`
- `document_registry`
- `chunk_registry`
- `sase_batches`
- `sase_questions`
- `sase_picklist_options`

### Present but currently not directly referenced in `src/` (verify before deprecating)

- `user_connections`
- `team_members`
- `audit_log`
- `teams`

### Referenced file samples by table

- **users**
  - `src/apis/routes/drive_routes.py`
  - `src/apis/routes/gmail_routes.py`
  - `src/apis/routes/slack_routes.py`
  - `src/services/database_manager/models/auth_models.py`
  - `src/services/plugins/oauth_service.py`

- **opportunities**
  - `src/apis/routes/opportunity_routes.py`
  - `src/apis/routes/sync_routes.py`
  - `src/services/database_manager/rag_data_service.py`
  - `src/services/pipelines/ingestion_pipeline.py`

- **opportunity_sources**
  - `src/apis/routes/opportunity_routes.py`
  - `src/apis/routes/sync_routes.py`
  - `src/services/database_manager/rag_data_service.py`

- **answers / answer_versions / citations / conflicts / feedback**
  - `src/apis/routes/opportunity_routes.py`
  - `src/services/database_manager/rag_data_service.py`
  - `src/services/agent/graph.py`
  - `src/services/agent/supervisor.py`

- **document_registry / chunk_registry**
  - `src/services/database_manager/registry.py`
  - `src/services/pipelines/ingestion_pipeline.py`
  - `src/services/rag_engine/retrieval/vector_search.py`

- **sase_***
  - `src/services/agent/field_loader.py`
  - `src/services/agent/batch_registry.py`
  - `src/services/rag_engine/retrieval/questions_loader.py`
  - `src/apis/routes/opportunity_routes.py`

## Dropped from schema (not used in codebase)

- Legacy `questions` table
- `opportunity_members`
- `schema_state_audit` (drift baseline is now `db/schema/last_schema_baseline.json`)
