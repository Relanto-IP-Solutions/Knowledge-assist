# Scripts

This folder contains all scripts for the Knowledge-Assist project, organized by purpose.

## Folder Structure

```
scripts/
├── setup/              # Infrastructure and database setup
├── tests_integration/  # Integration tests (real GCP services, requires credentials)
├── tests_unit/         # Unit tests (mocked, no credentials needed)
├── debug/              # Debugging and data inspection tools
├── utils/              # Data processing and utility scripts
└── run_agent_local.py  # Run the agent locally
```

## Folders

### `setup/` - Infrastructure Setup
Scripts for setting up databases, Cloud SQL instances, and infrastructure.

| Script | Description |
|--------|-------------|
| `setup_database.py` | One-command database setup for new machines |
| `setup_cloudsql_and_restore.py` | Create Cloud SQL instance and restore from dump |
| `create_pg_tables.py` | Deprecated (use modular schema scripts in `scripts/db/`) |

```bash
uv run python -m scripts.setup.setup_database
```

---

### `tests_integration/` - Integration Tests (Real Infrastructure)
Tests that hit **real GCP services** (GCS, Vertex AI, Cloud SQL, Vector Search).  
**Requires**: GCP credentials and proper `.env` configuration.

| Script | Description |
|--------|-------------|
| `smoke_retrieval.py` | Test retrieval pipeline (embed → Vector Search → rerank) |
| `smoke_ingestion_pipeline.py` | Test ingestion pipeline for a GCS file |
| `smoke_answer_generation.py` | Test answer generation with mock context |
| `smoke_rag_deletion.py` | Test RAG deletion flow |
| `smoke_document_deletion_flow.py` | Test document deletion flow |
| `smoke_slack_gcs_pipeline.py` | Test Slack message ingestion pipeline |
| `smoke_vtt_gcs_pipeline.py` | Test VTT transcript ingestion pipeline |
| `test_documents_registry_e2e.sh` | End-to-end document registry tests |

```bash
uv run python scripts/tests_integration/smoke_retrieval.py oid1001 --dry-run
```

---

### `tests_unit/` - Unit Tests (Mocked, No Credentials)
Unit tests that use **mocks** to verify behavior without hitting real services.  
**No credentials required** - safe to run anywhere.

| Script | Description |
|--------|-------------|
| `smoke_retry.py` | Base retry utility tests |
| `smoke_retry_embedding.py` | Embedding service retry tests |
| `smoke_retry_reranking.py` | Reranking service retry tests |
| `smoke_retry_vector_search.py` | Vector search retry tests |
| `smoke_retry_storage.py` | GCS storage retry tests |
| `smoke_retry_answer_generation.py` | Answer generation retry tests |
| `run_all_retry_smoke_tests.sh` | Run all unit tests |

```bash
# Run a single test
uv run python scripts/tests_unit/smoke_retry_embedding.py

# Run all unit tests
./scripts/tests_unit/run_all_retry_smoke_tests.sh
```

---

### `debug/` - Debugging Tools
Scripts for inspecting data, debugging issues, and analyzing results.

| Script | Description |
|--------|-------------|
| `view_pg_data.py` | View PostgreSQL data |
| `inspect_registry_tables.py` | Inspect document and chunk registry tables |
| `debug_retrieval_scores.py` | Debug retrieval scoring for a question |

```bash
uv run python scripts/debug/inspect_registry_tables.py --limit-docs 5
```

---

### `utils/` - Utility Scripts
Data processing, conversion, and one-off utility scripts.

| Script | Description |
|--------|-------------|
| `gemini_ocr.py` | OCR using Gemini |
| `json_to_excel.py` | Convert JSON output to Excel |
| `vtt_preprocessing_chunking.py` | Preprocess and chunk VTT files |
| `generate_llm_question_batches.py` | Generate LLM question batches |
| `backfill_question_embeddings.py` | Backfill missing question embeddings |

```bash
uv run python scripts/utils/json_to_excel.py data/output/results.json
```

---

## Quick Reference

| Folder | Credentials | What it tests |
|--------|-------------|---------------|
| `tests_integration/` | Required | Real GCP services |
| `tests_unit/` | Not needed | Mocked behavior |
| `setup/` | Required | Infrastructure setup |
| `debug/` | Required | Data inspection |
| `utils/` | Varies | Data processing |
