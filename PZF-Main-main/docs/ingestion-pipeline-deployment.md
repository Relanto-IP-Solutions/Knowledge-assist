# Knowledge-Assist Ingestion Pipeline — Deployment Runbook

Step-by-step guide for standing up the Knowledge-Assist ingestion pipeline in a new GCP environment. Follow sections in order; later steps depend on values captured in earlier ones.

## Architecture Overview

Documents, Zoom, and Slack files are **uploaded directly to GCS** at `raw/documents`, `raw/zoom`, and `raw/slack`. The workflow processes them into `processed/` and publishes to Pub/Sub.

```
Cloud Scheduler (every 15 min)
    └─▶ Cloud Workflow: ingestion-pipeline
            ├─▶ CF: gcs-file-processor (HTTP POST, OIDC)  → GCS raw/ → GCS processed/
            └─▶ CF: pubsub-dispatch    (HTTP POST, OIDC)  → GCS processed/ → Pub/Sub rag-ingestion-queue

Pub/Sub: rag-ingestion-queue
    └─▶ CF: rag-ingestion  (Pub/Sub push, one msg per file)
            ├─▶ chunks + embeds via Vertex AI text-embedding-004
            ├─▶ upserts to Vertex AI Vector Search (3 indexes: docs / slack / zoom)
            └─▶ publishes completion to Pub/Sub: rag-retrieval-initiation

Document deletion:
  Raw deleted → gcs-file-processor orphan sync removes processed/documents → HTTP POST
    pubsub-dispatch (PUBSUB_DISPATCH_URL) → rag-ingestion-queue (document_deleted) → rag-ingestion.
  See: [DOCUMENT-DELETION-FLOW.md](../DOCUMENT-DELETION-FLOW.md)
```

---

## 1. Prerequisites

- `gcloud` CLI installed and authenticated:
  ```bash
  gcloud auth login
  gcloud auth application-default login
  ```
- Set shell variables used throughout this runbook:
  ```bash
  export PROJECT_ID=your-new-project-id
  export PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
  export REGION=us-central1
  gcloud config set project $PROJECT_ID
  ```
- `uv` installed for local Python runs ([install guide](https://docs.astral.sh/uv/))

---

## 2. Enable Required GCP APIs

```bash
gcloud services enable \
  cloudfunctions.googleapis.com \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  workflows.googleapis.com \
  pubsub.googleapis.com \
  storage.googleapis.com \
  aiplatform.googleapis.com \
  documentai.googleapis.com \
  iam.googleapis.com \
  cloudresourcemanager.googleapis.com \
  --project=$PROJECT_ID
```

---

## 3. Service Account Setup

### 3a. Create the Service Account

```bash
gcloud iam service-accounts create knowledge-assist-app \
  --display-name="Knowledge-Assist Application Service Account" \
  --project=$PROJECT_ID
```

Full email: `knowledge-assist-app@${PROJECT_ID}.iam.gserviceaccount.com`

### 3b. Assign IAM Roles

```bash
SA="knowledge-assist-app@${PROJECT_ID}.iam.gserviceaccount.com"

# GCS: read/write objects (raw files, processed files)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" --role="roles/storage.objectAdmin"

# Pub/Sub: publish to topics and subscribe for RAG ingestion
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" --role="roles/pubsub.publisher"
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" --role="roles/pubsub.subscriber"

# Vertex AI: text embeddings, Vector Search upserts
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" --role="roles/aiplatform.user"

# Vertex AI (Gemini): document extraction (PDF/images), embeddings, Vector Search
# roles/aiplatform.user (above) covers Gemini; Document AI is deprecated for extraction

# Cloud Run invoker: workflow calls functions via OIDC
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" --role="roles/run.invoker"

# Cloud Workflows: Cloud Scheduler triggers the workflow
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" --role="roles/workflows.invoker"

# OIDC token creation: workflow generates tokens for HTTP function calls
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" --role="roles/iam.serviceAccountTokenCreator"

# Cloud Logging
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA" --role="roles/logging.logWriter"
```

### 3c. Download Service Account Key (local dev only)

```bash
mkdir -p configs/secrets
gcloud iam service-accounts keys create configs/secrets/pzf-app-key.json \
  --iam-account="pzf-app@${PROJECT_ID}.iam.gserviceaccount.com"
```

> **Cloud Functions / Cloud Run:** Do not use a key file in production. The `--service-account` flag on `gcloud functions deploy` binds the SA via Workload Identity automatically. Omit `GOOGLE_APPLICATION_CREDENTIALS` from `--set-env-vars` for deployed functions.

---

## 4. GCS Bucket Setup

```bash
BUCKET_NAME="${PROJECT_ID}-ingestion"

gcloud storage buckets create gs://$BUCKET_NAME \
  --project=$PROJECT_ID \
  --location=$REGION \
  --uniform-bucket-level-access
```

The bucket uses this path structure at runtime:

```
gs://{bucket}/{opportunity_id}/raw/{source_type}/{filename}
gs://{bucket}/{opportunity_id}/processed/{source_type}/{filename}
```

### 4a. Uploading Files to GCS

Upload source files directly to the raw tier. The workflow (gcs-file-processor → pubsub-dispatch) processes them every 15 minutes.

| Source | Raw path | Processed path |
|--------|----------|----------------|
| Documents | `gs://{bucket}/{opp_id}/raw/documents/{filename}` | `{opp_id}/processed/documents/{stem}.txt` |
| Zoom | `gs://{bucket}/{opp_id}/raw/zoom/{meeting_id}.vtt` | `{opp_id}/processed/zoom_transcripts/{stem}.txt` |
| Slack | `gs://{bucket}/{opp_id}/raw/slack/{channel_id}/slack_messages.json` + `gs://{bucket}/{opp_id}/raw/slack/slack_metadata.json` | `{opp_id}/processed/slack_messages/{channel_id}/summary.txt` |

**Examples:**

```bash
# Documents (PDF, DOCX, PPTX, etc.)
gsutil cp document.pdf gs://${BUCKET_NAME}/${OID}/raw/documents/document.pdf

# Zoom VTT transcript
gsutil cp meeting-123.vtt gs://${BUCKET_NAME}/${OID}/raw/zoom/meeting-123.vtt

# Slack (requires both files)
gsutil cp slack_messages.json gs://${BUCKET_NAME}/${OID}/raw/slack/channel-abc/slack_messages.json
gsutil cp slack_metadata.json gs://${BUCKET_NAME}/${OID}/raw/slack/slack_metadata.json
```

---

## 5. Pub/Sub Topics Setup

```bash
# Primary RAG ingestion queue (pubsub-dispatch → rag-ingestion)
gcloud pubsub topics create rag-ingestion-queue --project=$PROJECT_ID

# Completion event topic (rag-ingestion → downstream consumers)
gcloud pubsub topics create rag-retrieval-initiation --project=$PROJECT_ID
```

### 5a. Pub/Sub Push Subscription for `rag-ingestion`

When deploying `rag-ingestion` with `--trigger-topic`, `gcloud` creates the push subscription automatically. If you ever need to recreate it manually:

```bash
RAG_INGEST_URL=$(gcloud run services describe rag-ingestion \
  --region=$REGION --project=$PROJECT_ID --format='value(status.url)')

gcloud pubsub subscriptions create rag-ingestion-sub \
  --topic=rag-ingestion-queue \
  --push-endpoint="${RAG_INGEST_URL}" \
  --push-auth-service-account="pzf-app@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project=$PROJECT_ID
```

---

## 6. Vertex AI Vector Search Index Creation

Three indexes are required — one each for **documents** (PDF/DOCX/PPTX), **Slack messages**, and **Zoom transcripts**. All use `text-embedding-004` (768 dimensions).

> Index creation takes approximately 30 minutes per index.

### 6a. Create the Three Indexes

```bash
# Documents index
gcloud ai indexes create \
  --display-name="pzf-documents-index" \
  --description="RAG index for Google Drive documents (PDF, DOCX, PPTX)" \
  --metadata-file=- \
  --region=$REGION \
  --project=$PROJECT_ID <<'EOF'
{
  "contentsDeltaUri": "",
  "config": {
    "dimensions": 768,
    "approximateNeighborsCount": 150,
    "distanceMeasureType": "DOT_PRODUCT_DISTANCE",
    "algorithm_config": {
      "treeAhConfig": {
        "leafNodeEmbeddingCount": 500,
        "leafNodesToSearchPercent": 7
      }
    }
  }
}
EOF

# Slack messages index
gcloud ai indexes create \
  --display-name="pzf-slack-index" \
  --description="RAG index for Slack messages" \
  --metadata-file=- \
  --region=$REGION \
  --project=$PROJECT_ID <<'EOF'
{
  "contentsDeltaUri": "",
  "config": {
    "dimensions": 768,
    "approximateNeighborsCount": 150,
    "distanceMeasureType": "DOT_PRODUCT_DISTANCE",
    "algorithm_config": {
      "treeAhConfig": {
        "leafNodeEmbeddingCount": 500,
        "leafNodesToSearchPercent": 7
      }
    }
  }
}
EOF

# Zoom transcripts index
gcloud ai indexes create \
  --display-name="pzf-zoom-index" \
  --description="RAG index for Zoom transcripts (VTT)" \
  --metadata-file=- \
  --region=$REGION \
  --project=$PROJECT_ID <<'EOF'
{
  "contentsDeltaUri": "",
  "config": {
    "dimensions": 768,
    "approximateNeighborsCount": 150,
    "distanceMeasureType": "DOT_PRODUCT_DISTANCE",
    "algorithm_config": {
      "treeAhConfig": {
        "leafNodeEmbeddingCount": 500,
        "leafNodesToSearchPercent": 7
      }
    }
  }
}
EOF
```

Poll until all three show `state: ACTIVE`:

```bash
gcloud ai indexes list --region=$REGION --project=$PROJECT_ID
```

### 6b. Create an Index Endpoint

```bash
gcloud ai index-endpoints create \
  --display-name="pzf-index-endpoint" \
  --region=$REGION \
  --project=$PROJECT_ID
```

Capture the endpoint ID from the output (or list it):

```bash
gcloud ai index-endpoints list --region=$REGION --project=$PROJECT_ID
export INDEX_ENDPOINT_ID=<endpoint-id-from-output>
```

### 6c. Deploy All Three Indexes to the Endpoint

Capture the index IDs from Step 6a output (or list with `gcloud ai indexes list`):

```bash
export INDEX_ID_DOCS=<documents-index-id>
export INDEX_ID_SLACK=<slack-index-id>
export INDEX_ID_ZOOM=<zoom-index-id>

# Deploy documents index
gcloud ai index-endpoints deploy-index $INDEX_ENDPOINT_ID \
  --deployed-index-id="ingest_docs_rag" \
  --display-name="pzf-docs-deployed" \
  --index=$INDEX_ID_DOCS \
  --region=$REGION --project=$PROJECT_ID

# Deploy Slack index
gcloud ai index-endpoints deploy-index $INDEX_ENDPOINT_ID \
  --deployed-index-id="ingest_slack_rag" \
  --display-name="pzf-slack-deployed" \
  --index=$INDEX_ID_SLACK \
  --region=$REGION --project=$PROJECT_ID

# Deploy Zoom index
gcloud ai index-endpoints deploy-index $INDEX_ENDPOINT_ID \
  --deployed-index-id="ingest_zoom_rag" \
  --display-name="pzf-zoom-deployed" \
  --index=$INDEX_ID_ZOOM \
  --region=$REGION --project=$PROJECT_ID
```

### 6d. Collect Index Resource Names

Set these variables — they are required for the `rag-ingestion` Cloud Function (Step 10d):

```bash
export INDEX_RESOURCE_NAME_DOCUMENTS="projects/${PROJECT_NUMBER}/locations/${REGION}/indexes/${INDEX_ID_DOCS}"
export INDEX_RESOURCE_NAME_SLACK="projects/${PROJECT_NUMBER}/locations/${REGION}/indexes/${INDEX_ID_SLACK}"
export INDEX_RESOURCE_NAME_ZOOM="projects/${PROJECT_NUMBER}/locations/${REGION}/indexes/${INDEX_ID_ZOOM}"
```

---

## 7. Document Extraction (Gemini / Vertex AI)

The codebase uses **Vertex AI Gemini** for document extraction (PDF, images). No separate Document AI processor is required.

- **Vertex AI API** must be enabled (`aiplatform.googleapis.com` — Step 2).
- **Service account** needs `roles/aiplatform.user` (Step 3b) for Gemini access.
- **Model**: `LLM_MODEL_NAME` (default `gemini-2.5-flash`) in `configs/.env` or `configs/secrets/.env`.
- **Optional**: `GEMINI_EXTRACTION_BATCH_SIZE` (default 15), `GEMINI_EXTRACTION_MAX_WORKERS` (default 10) for large PDF batching.

---

## 8. Environment Configuration

### 8a. `configs/.env`

Copy `configs/.env.example` to `configs/.env` and fill in non-sensitive values:

```ini
# --- GCP ---
GCP_PROJECT_ID=your-new-project-id
GCS_BUCKET_INGESTION=your-new-project-id-ingestion

# --- Pub/Sub ---
PUBSUB_TOPIC_RAG_INGESTION=rag-ingestion-queue

# --- Vector Search ---
# VECTOR_SOURCE_* vars go in configs/secrets/.env
```

### 8b. `configs/secrets/.env`

```ini
GOOGLE_APPLICATION_CREDENTIALS=configs/secrets/pzf-app-key.json

# Document extraction uses Vertex AI Gemini (LLM_MODEL_NAME); no Document AI processor needed.

# Vector Search (for retrieval; see configs/secrets/.env.example)
VECTOR_SOURCE_DRIVE_PUBLIC_DOMAIN=
VECTOR_SOURCE_DRIVE_INDEX_ENDPOINT=
VECTOR_SOURCE_DRIVE_DEPLOYED_INDEX_ID=
VECTOR_SOURCE_ZOOM_PUBLIC_DOMAIN=
VECTOR_SOURCE_ZOOM_INDEX_ENDPOINT=
VECTOR_SOURCE_ZOOM_DEPLOYED_INDEX_ID=
VECTOR_SOURCE_SLACK_PUBLIC_DOMAIN=
VECTOR_SOURCE_SLACK_INDEX_ENDPOINT=
VECTOR_SOURCE_SLACK_DEPLOYED_INDEX_ID=
```

> This file is `.gitignore`d and `.gcloudignore`d. Never commit it.

---

## 9. Update `workflows/ingestion_pipeline.yaml` for the New Environment

The workflow YAML hard-codes the Cloud Run URLs and project ID from the original environment. Update these **after** deploying the Cloud Functions (Step 10) and **before** deploying the workflow (Step 12).

```bash
# Retrieve Cloud Run URLs for the two HTTP-triggered functions
gcloud run services describe gcs-file-processor \
  --region=$REGION --project=$PROJECT_ID --format='value(status.url)'

gcloud run services describe pubsub-dispatch \
  --region=$REGION --project=$PROJECT_ID --format='value(status.url)'
```

In `workflows/ingestion_pipeline.yaml`, update the `init` and `build_urls` steps:

```yaml
# Line ~48 — update project variable
- project: "your-new-project-id"

# Lines ~76-78 — replace with new Cloud Run URLs
- gcs_processor_url: "https://gcs-file-processor-<new-hash>-uc.a.run.app"
- pubsub_dispatch_url: "https://pubsub-dispatch-<new-hash>-uc.a.run.app"
```

> The workflow uses direct Cloud Run `*.a.run.app` URLs (not `cloudfunctions.net` aliases) to avoid OIDC token routing issues with Gen2 functions. Always use the Cloud Run URL.

---

## 10. Deploy Cloud Functions

All three functions are deployed from the **repo root** (`--source=.`). Run every command from the workspace directory. The `requirements.txt` in the repo root is picked up automatically.

### 10a. `gcs-file-processor`

Preprocesses raw files in GCS (Zoom VTT → `.txt`, Slack JSON → `summary.txt`) into the `processed/` tier.

```bash
gcloud functions deploy gcs-file-processor \
  --gen2 \
  --region=$REGION \
  --runtime=python313 \
  --trigger-http \
  --entry-point=handle \
  --source=. \
  --project=$PROJECT_ID \
  --service-account="pzf-app@${PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},GCS_BUCKET_INGESTION=${PROJECT_ID}-ingestion,PYTHONPATH=/workspace,FUNCTION_SOURCE=functions/gcs_file_processor.py" \
  --timeout=300 \
  --no-allow-unauthenticated
```

### 10b. `pubsub-dispatch`

Scans `processed/` objects and publishes one Pub/Sub message per file to `rag-ingestion-queue`.

```bash
gcloud functions deploy pubsub-dispatch \
  --gen2 \
  --region=$REGION \
  --runtime=python313 \
  --trigger-http \
  --entry-point=handle_http \
  --source=. \
  --project=$PROJECT_ID \
  --service-account="pzf-app@${PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},GCS_BUCKET_INGESTION=${PROJECT_ID}-ingestion,PUBSUB_TOPIC_RAG_INGESTION=rag-ingestion-queue,PYTHONPATH=/workspace,FUNCTION_SOURCE=functions/pubsub_dispatch.py" \
  --timeout=300 \
  --memory=512MiB \
  --no-allow-unauthenticated
```

> **Note:** Default 256 MiB is insufficient for Python startup; 512 MiB avoids OOM during health check.

### 10b. `gcs-file-processor`

Preprocesses raw → `processed/`. After orphan **processed/documents** deletes, POSTs **pubsub-dispatch** (`PUBSUB_DISPATCH_URL`).

```bash
PUBSUB_DISP_URL=$(gcloud run services describe pubsub-dispatch \
  --region=$REGION --project=$PROJECT_ID --format='value(status.url)')

gcloud functions deploy gcs-file-processor \
  --gen2 \
  --region=$REGION \
  --runtime=python313 \
  --trigger-http \
  --entry-point=handle \
  --source=. \
  --project=$PROJECT_ID \
  --service-account="pzf-app@${PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},GCS_BUCKET_INGESTION=${PROJECT_ID}-ingestion,PUBSUB_DISPATCH_URL=${PUBSUB_DISP_URL},PYTHONPATH=/workspace,FUNCTION_SOURCE=functions/gcs_file_processor.py" \
  --timeout=300 \
  --no-allow-unauthenticated

gcloud run services add-iam-policy-binding pubsub-dispatch \
  --region=$REGION --project=$PROJECT_ID \
  --member="serviceAccount:pzf-app@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.invoker" \
  --quiet
```

### 10c. `rag-ingestion`

Triggered by Pub/Sub push. Chunks, embeds, and upserts content to Vertex AI Vector Search. Requires the index resource names from Step 6d.

```bash
gcloud functions deploy rag-ingestion \
  --gen2 \
  --region=$REGION \
  --runtime=python313 \
  --trigger-topic=rag-ingestion-queue \
  --entry-point=handle_pubsub \
  --source=. \
  --project=$PROJECT_ID \
  --service-account="pzf-app@${PROJECT_ID}.iam.gserviceaccount.com" \
  --set-env-vars="\
PROJECT_ID=${PROJECT_ID},\
LOCATION=${REGION},\
OUTPUT_TOPIC=projects/${PROJECT_ID}/topics/rag-retrieval-initiation,\
INDEX_RESOURCE_NAME_DOCUMENTS=${INDEX_RESOURCE_NAME_DOCUMENTS},\
INDEX_RESOURCE_NAME_SLACK=${INDEX_RESOURCE_NAME_SLACK},\
INDEX_RESOURCE_NAME_ZOOM=${INDEX_RESOURCE_NAME_ZOOM},\
DEPLOYED_INDEX_ID_DOCUMENTS=ingest_docs_rag,\
DEPLOYED_INDEX_ID_SLACK=ingest_slack_rag,\
DEPLOYED_INDEX_ID_ZOOM=ingest_zoom_rag,\
GCP_PROJECT_ID=${PROJECT_ID},\
GCS_BUCKET_INGESTION=${PROJECT_ID}-ingestion,\
PYTHONPATH=/workspace,\
FUNCTION_SOURCE=functions/rag_ingestion.py" \
  --timeout=300 \
  --memory=1GiB \
  --no-allow-unauthenticated
```

---

## 11. Complete Environment Variable Reference

### Application / Local (`configs/.env` and `configs/secrets/.env`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `GCP_PROJECT_ID` | **Yes** | — | GCP project ID |
| `GCS_BUCKET_INGESTION` | **Yes** | — | GCS ingestion bucket name |
| `DOCUMENT_AI_PROCESSOR_NAME` | No | — | Deprecated. Document extraction uses Gemini (`LLM_MODEL_NAME`). |
| `GEMINI_EXTRACTION_BATCH_SIZE` | No | 15 | Pages per PDF batch for Gemini extraction |
| `GEMINI_EXTRACTION_MAX_WORKERS` | No | 10 | Max concurrent PDF batch calls |
| `VECTOR_SOURCE_{DRIVE,ZOOM,SLACK}_*` | For retrieval | — | 9 vars: public_domain, index_endpoint, deployed_index_id per source. In secrets. |
| `PUBSUB_TOPIC_RAG_INGESTION` | No | `rag-ingestion-queue` | Pub/Sub topic name for RAG ingestion queue |
| `GOOGLE_APPLICATION_CREDENTIALS` | **Yes (local)** | — | Path to SA key JSON (`configs/secrets/pzf-app-key.json`) |

### Cloud Function Runtime (`--set-env-vars`)

| Variable | Function | Description |
|---|---|---|
| `GCP_PROJECT_ID` | All 3 | GCP project ID |
| `GCS_BUCKET_INGESTION` | All 3 | GCS bucket name |
| `PUBSUB_TOPIC_RAG_INGESTION` | `pubsub-dispatch` | Pub/Sub topic name for RAG queue |
| `PUBSUB_DISPATCH_URL` | `gcs-file-processor` | Cloud Run URL of **pubsub-dispatch** (document_deleted notify) |
| `PROJECT_ID` | `rag-ingestion` | GCP project (used by IngestionPipeline) |
| `LOCATION` | `rag-ingestion` | GCP region (used by IngestionPipeline) |
| `OUTPUT_TOPIC` | `rag-ingestion` | Full Pub/Sub topic path for completion events (e.g. `projects/{PROJECT_ID}/topics/rag-retrieval-initiation`) |
| `INDEX_RESOURCE_NAME_DOCUMENTS` | `rag-ingestion` | Full Vertex AI index resource name for documents |
| `INDEX_RESOURCE_NAME_SLACK` | `rag-ingestion` | Full Vertex AI index resource name for Slack |
| `INDEX_RESOURCE_NAME_ZOOM` | `rag-ingestion` | Full Vertex AI index resource name for Zoom |
| `INDEX_RESOURCE_NAME` | `rag-ingestion` | Fallback index resource name if type-specific ones are unset |
| `DEPLOYED_INDEX_ID_DOCUMENTS` | `rag-ingestion` | Deployed index ID for documents (e.g. `ingest_docs_rag`) |
| `DEPLOYED_INDEX_ID_SLACK` | `rag-ingestion` | Deployed index ID for Slack (e.g. `ingest_slack_rag`) |
| `DEPLOYED_INDEX_ID_ZOOM` | `rag-ingestion` | Deployed index ID for Zoom (e.g. `ingest_zoom_rag`) |
| `PYTHONPATH` | All 3 | Must be `/workspace` for Gen2 Cloud Functions |
| `FUNCTION_SOURCE` | All 3 | Path to function file (informational) |

### Registry Tables and Re-ingestion (Documents Only)

For **documents** source type, the ingestion pipeline uses `document_registry` and `chunk_registry` tables in PostgreSQL for re-ingestion and deletion:

- **Registry tables:** `document_registry` and `chunk_registry` must exist. Create them manually or via migration before running document ingestion.
- **Re-ingestion behavior:**
  - **Document-level skip:** If `doc_hash` matches the existing registry entry, ingestion is skipped.
  - **Chunk-level diff:** For changed documents, only modified chunks are re-embedded and upserted; stale chunks (e.g. when document is shortened) are deleted from Vertex AI.
  - **Orphan reconciliation:** Before each document run, the pipeline compares GCS `processed/documents` with the registry and removes documents no longer in GCS from both the registry and Vertex AI Vector Search.
- **Required for documents:** `PG_DATABASE` (or equivalent DB connection) for registry access; `INDEX_RESOURCE_NAME_DOCUMENTS`; `OUTPUT_TOPIC` (optional, for completion events).

---

## 12. Deploy Cloud Workflow

> Complete Step 9 (update `workflows/ingestion_pipeline.yaml` with new Cloud Run URLs) before this step.

```bash
gcloud workflows deploy ingestion-pipeline \
  --source=workflows/ingestion_pipeline.yaml \
  --location=$REGION \
  --project=$PROJECT_ID \
  --service-account="pzf-app@${PROJECT_ID}.iam.gserviceaccount.com"
```

Verify it is active:

```bash
gcloud workflows describe ingestion-pipeline \
  --location=$REGION --project=$PROJECT_ID
```

---

## 13. Create Cloud Scheduler Job

```bash
gcloud scheduler jobs create http ingestion-pipeline-job \
  --schedule="*/15 * * * *" \
  --location=$REGION \
  --uri="https://workflowexecutions.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/workflows/ingestion-pipeline/executions" \
  --message-body='{"argument": "{\"lookback_minutes\": 15}"}' \
  --oauth-service-account-email="pzf-app@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project=$PROJECT_ID
```

To update the schedule later:

```bash
gcloud scheduler jobs update http ingestion-pipeline-job \
  --schedule="*/15 * * * *" \
  --location=$REGION --project=$PROJECT_ID
```

To pause / resume:

```bash
gcloud scheduler jobs pause  ingestion-pipeline-job --location=$REGION --project=$PROJECT_ID
gcloud scheduler jobs resume ingestion-pipeline-job --location=$REGION --project=$PROJECT_ID
```

---

## 14. Invoke Cloud Functions Manually

Use your own identity token (must have `roles/run.invoker` on the project or function):

```bash
TOKEN=$(gcloud auth print-identity-token)

# Retrieve Cloud Run URLs
GCS_PROC_URL=$(gcloud run services describe gcs-file-processor \
  --region=$REGION --project=$PROJECT_ID --format='value(status.url)')
PUBSUB_DISP_URL=$(gcloud run services describe pubsub-dispatch \
  --region=$REGION --project=$PROJECT_ID --format='value(status.url)')

# 1. GCS file processor — process all files (no time window)
curl -X POST "${GCS_PROC_URL}?lookback_minutes=0" \
  -H "Authorization: Bearer $TOKEN"

# 2. Pub/Sub dispatch — dispatch all processed files
curl -X POST "${PUBSUB_DISP_URL}?lookback_minutes=0" \
  -H "Authorization: Bearer $TOKEN"

# Scope any call to a single opportunity
curl -X POST "${GCS_PROC_URL}?opportunity_id=oid1023&lookback_minutes=0" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 15. Execute the Workflow Manually

```bash
# Standard run — 15-minute lookback window (same as the scheduled job)
gcloud workflows run ingestion-pipeline \
  --location=$REGION \
  --project=$PROJECT_ID \
  --data='{"lookback_minutes": 15}'

# Full backfill — process and dispatch all files regardless of age
gcloud workflows run ingestion-pipeline \
  --location=$REGION \
  --project=$PROJECT_ID \
  --data='{"lookback_minutes": 0}'

# Scoped to one opportunity with a 60-minute window
gcloud workflows run ingestion-pipeline \
  --location=$REGION \
  --project=$PROJECT_ID \
  --data='{"lookback_minutes": 60, "opportunity_id": "oid1023"}'

# Check execution status
gcloud workflows executions list ingestion-pipeline \
  --location=$REGION --project=$PROJECT_ID

# Describe a specific execution
gcloud workflows executions describe <EXECUTION_ID> \
  --workflow=ingestion-pipeline \
  --location=$REGION --project=$PROJECT_ID
```

---

## 16. Smoke Test Scripts

Run from the repo root after deploying:

```bash
# Document ingestion: upload sample PDF to raw/documents, run workflow, verify processed/
./scripts/tests_integration/smoke_document_ingestion.sh

# Slack messages pipeline end-to-end
uv run python scripts/tests_integration/smoke_slack_gcs_pipeline.py

# Zoom VTT transcript pipeline end-to-end
uv run python scripts/tests_integration/smoke_vtt_gcs_pipeline.py

# Document extraction (Gemini: PDF, images; native: DOCX, MD, PPTX)
uv run python scripts/tests_integration/smoke_document_extraction.py

# Slack summary pipeline
uv run python scripts/tests_integration/smoke_slack_summary.py
```

---

## 17. Post-Deployment Checklist

- [ ] All required GCP APIs enabled (`gcloud services list --enabled --project=$PROJECT_ID`)
- [ ] Service account `pzf-app@${PROJECT_ID}.iam.gserviceaccount.com` created with all IAM roles
- [ ] GCS bucket `${PROJECT_ID}-ingestion` created
- [ ] Both Pub/Sub topics created: `rag-ingestion-queue`, `rag-retrieval-initiation`
- [ ] 3 Vertex AI Vector Search indexes created and deployed (`ACTIVE` state)
- [ ] Vertex AI / Gemini configured for document extraction (LLM_MODEL_NAME)
- [ ] `configs/.env` filled in with project-specific values
- [ ] `configs/secrets/.env` contains `GOOGLE_APPLICATION_CREDENTIALS` path
- [ ] All 3 Cloud Functions deployed and show `ACTIVE` status
- [ ] `workflows/ingestion_pipeline.yaml` updated with new project ID and Cloud Run URLs
- [ ] Cloud Workflow `ingestion-pipeline` deployed and `ACTIVE`
- [ ] Cloud Scheduler job `ingestion-pipeline-job` created and `ENABLED`
- [ ] `rag-ingestion-queue` push subscription points to the correct `rag-ingestion` Cloud Run URL
- [ ] Ingestion smoke tests pass (GCS processing, Pub/Sub dispatch)

> **If upgrading from a previous deployment:** If `drive-sync` was previously deployed, undeploy it:
> ```bash
> gcloud run services delete drive-sync --region=$REGION --project=$PROJECT_ID
> ```
