# Google Cloud & Google APIs — how this project uses them

Single reference for **which Google services** appear in the codebase, **why**, and **what** they do. IAM and exact roles should follow your org’s security baseline; this doc is functional.

---

## 1. Google Cloud Storage (GCS)

**Why:** Central object store for the knowledge pipeline.

**Usage:**
- **`{opportunity_id}/raw/...`** — Immutable-ish inputs from connectors (Gmail thread JSON, Slack exports, Drive files, Zoom VTT, etc.).
- **`{opportunity_id}/processed/...`** — Text and intermediates produced by **`GcsPipeline`** (summaries, transcripts, extracted PDF text, etc.).
- **`{opportunity_id}/responses/...`** — Answer-generation outputs (when written by pipelines).

**Config:** `GCS_BUCKET_INGESTION` (and related) in `configs/settings.py` → `IngestionSettings`.

**Auth:** Service account JSON via **`GOOGLE_APPLICATION_CREDENTIALS`**, or **Application Default Credentials** on Cloud Run / GCE.

---

## 2. Gmail API (Google Workspace / consumer Gmail)

**Why:** Read threads for an OAuth user and sync to **`raw/gmail/`**.

**Usage:** `googleapiclient` in `src/services/plugins/gmail_plugin.py` — `users.threads.list`, `users.threads.get`, scope **`gmail.readonly`**.

**Auth:** User **`google_refresh_token`** stored on `users` after **Google OAuth** (`/auth/google/*`).

---

## 3. Google Drive API v3

**Why:** List folders under a configured root (e.g. **Requirements/**) and sync files into **`raw/documents/`**.

**Usage:** `googleapiclient` in `src/services/plugins/drive_plugin.py`, scope **`drive.readonly`** (or as configured).

**Auth:** Same Google OAuth refresh token as Gmail for the **connector** user (`DRIVE_CONNECTOR_USER_EMAIL` / shared token).

---

## 4. Google OAuth 2.0 (not a “product” billable by itself)

**Why:** Obtain and refresh **access tokens** for Gmail/Drive on behalf of users.

**Usage:** `src/services/plugins/oauth_service.py`, routes under **`/auth`**, browser callbacks on **`main`** (`/auth/google/callback`).

**Note:** Redirect URIs must match Google Cloud Console **OAuth client** settings.

---

## 5. Vertex AI (Gemini / embeddings / routing)

**Why:** LLM calls, **text embeddings**, and often **Vector Search** for RAG.

**Usage:** Retrieval, answer generation, agent pipelines — see `configs/settings.py` (`LLMSettings`, `RetrievalSettings`, `VERTEX_AI_LOCATION`, model IDs).

**Auth:** Same GCP project + ADC; APIs must be **enabled** on the project (Vertex AI API, etc.).

---

## 6. Cloud SQL for PostgreSQL (often with pgvector)

**Why:** Application database — `opportunities`, `opportunity_sources`, `answers`, `sase_questions`, chunk registries, etc.

**Usage:** SQLAlchemy + `psycopg2` / `pg8000`; optional **Cloud SQL Python Connector** for IAM auth (`CLOUDSQL_INSTANCE_CONNECTION_NAME`, `CLOUDSQL_USE_IAM_AUTH`).

**Config:** `DatabaseSettings` in `configs/settings.py`.

---

## 7. Cloud Pub/Sub

**Why:** Decouple **file processing** from **vector ingestion** and handle **document_deleted** notifications.

**Usage:**
- Topic for RAG ingestion (e.g. **`PUBSUB_TOPIC_RAG_INGESTION`**).
- **`pubsub-dispatch`** function publishes **`document_ingested`** messages after scanning **`processed/`**.
- Subscribers run embedding / index updates (`functions/rag_ingestion.py`, etc.).

**Config:** `IngestionSettings.pubsub_*` in settings.

---

## 8. Cloud Functions (Gen2) / Cloud Run

**Why:** Serverless HTTP entrypoints for scheduled and event-driven work.

**Usage (examples in repo):**
- **`gcs-file-processor`** — HTTP: run **`GcsPipeline`** (raw → processed).
- **`pubsub-dispatch`** — HTTP: run **`PubsubPipeline`** (processed → Pub/Sub).
- **`functions_framework`** entrypoints in `main.py` for legacy Cloud Functions deployment (`rag_ingestion`, `pubsub_dispatch`, `gcs_file_processor`).

**Auth:** Often **OIDC** from Cloud Workflows or Scheduler to Cloud Run URL (**audience** = target URL).

---

## 9. Cloud Workflows

**Why:** Orchestrate **gcs-file-processor** → **pubsub-dispatch** in order with retries.

**Usage:** `workflows/ingestion_pipeline.yaml` — pass **`lookback_minutes`**, **`opportunity_id`**.

---

## 10. Cloud Scheduler (optional, ops)

**Why:** Cron triggers for **`POST /sync/trigger`**, workflow executions, or Function URLs.

**Usage:** Not defined in Python; configured in GCP. See comments in `workflows/ingestion_pipeline.yaml` and runbooks.

---

## 11. Secret Manager

**Why:** Store secrets (e.g. **Zoom** S2S credentials) instead of plain env in some deployments.

**Usage:** `configs/bootstrap_secrets.py` — when **`ZOOM_SECRETS_FROM_SECRET_MANAGER`** is set, reads secrets named like **`ZOOM_ACCOUNT_ID`**, **`ZOOM_CLIENT_ID`**, etc.

**Auth:** Service account needs **`secretmanager.secretAccessor`** (or equivalent) on those secrets.

---

## 12. Identity and IAM (overview)

| Identity | Typical use |
|----------|-------------|
| **User OAuth** | Gmail/Drive/Slack **user-delegated** APIs. |
| **Service account (key or ADC)** | GCS, Vertex, Pub/Sub, Secret Manager, Cloud SQL IAM user. |
| **Cloud Run default SA** | Runtime for API and functions unless overridden. |

---

## 13. APIs not “Google” but often used alongside

| Service | Role in project |
|---------|-----------------|
| **Slack Web API** | Channel discovery, history (`slack.com/api`). OAuth separate from Google. |
| **Zoom REST API** | Server-to-Server OAuth; recordings listing (`api.zoom.us`). |

---

## 14. Enablement checklist (new GCP project)

Enable (at minimum) what you actually call:

- Cloud Storage API  
- Vertex AI API  
- Cloud SQL Admin API (if using Cloud SQL)  
- Pub/Sub API  
- Secret Manager API (if used)  
- Cloud Run / Cloud Functions APIs (deployment)  
- Gmail / Drive APIs are enabled via **Google Cloud Console → APIs & Services** for OAuth clients using those scopes  

---

*This document reflects the repository layout; exact env names are in `configs/settings.py` and `configs/secrets/.env.example` (if present).*
