# End-to-end smoke: connectors → ingestion → answer generation

This guide ties together **three** layers with **copy-paste commands** and explains **how ingestion decides which opportunities** to process.

---

## How ingestion scopes work (important)

Ingestion is **not** “only opportunities missing `processed/`”. It works in **two stages**:

### Stage A — `GcsPipeline` (raw → `processed/`)

Implemented in `src/services/pipelines/gcs_pipeline.py` and triggered by the **`gcs-file-processor`** Cloud Function (or run locally).

| Call | What gets processed |
|------|---------------------|
| **`opportunity_id` set** (e.g. `oid0123`) | **Only that OID.** Still respects **`since`** / lookback on raw blobs unless you disable the window. |
| **`opportunity_id` omitted** | **Every opportunity ID** discovered by scanning the bucket: OIDs that appear under `{oid}/raw/...` **plus** OIDs that only have `processed/` (reconciliation). |
| **`lookback_minutes=0`** (HTTP) | Sets **`since=None`** → **no time filter** on blob age → **all matching raw files** are eligible for that run (per-opp or global). |
| **`lookback_minutes=15`** (default) | Only raw blobs **updated** in the last 15 minutes (typical scheduler). |

So: if you **uploaded raw files long ago** and never processed them, use **`lookback_minutes=0`** (or run **`GcsPipeline().run(opportunity_id="oid0123", since=None)`** locally) so they are not skipped by the time window.

### Stage B — `PubsubPipeline` / **`pubsub-dispatch`**

Scans **`processed/`** (with its own lookback) and publishes messages to **Pub/Sub** for **vector ingestion / RAG** (`document_ingested`). This is what feeds embeddings and search—not the API `/sync` step.

**Typical GCP chain:** Cloud Workflow → `gcs-file-processor` → `pubsub-dispatch` (see `workflows/ingestion_pipeline.yaml`).

---

## Prerequisites

- **Connectors:** API running (`uvicorn main:app`), DB, OAuth users, `configs/secrets/.env`.
- **Ingestion (full cloud):** Deployed `gcs-file-processor` + `pubsub-dispatch`, `GCS_BUCKET_INGESTION`, `PUBSUB_DISPATCH_URL`, workflow URLs.
- **Ingestion (local dev):** `GOOGLE_APPLICATION_CREDENTIALS`, same bucket env, Python env with deps.
- **Answer generation:** Vertex / LLM settings per `configs/settings.py`, PostgreSQL for questions if using real pipeline.

---

## 1. Data connectors (discover + sync)

**Script:** `scripts/tests_integration/smoke_connectors_discover_and_sync.py`

Runs (by default): `POST /slack/discover` → `POST /gmail/discover` → `POST /drive/discover` → `POST /zoom/discover` → `POST /sync/trigger`.

**Local:**

```powershell
cd "C:\path\to\Project-PZF"
python scripts/tests_integration/smoke_connectors_discover_and_sync.py --base-url http://127.0.0.1:8080 --save-json output/e2e_01_connectors.json
```

**Single scheduler-shaped call** (discovers Slack+Gmail+Drive then syncs; Zoom **not** included):

```powershell
python scripts/tests_integration/smoke_connectors_discover_and_sync.py --base-url http://127.0.0.1:8080 --sync-run --save-json output/e2e_01_connectors.json
```

**Cloud Run (private) + identity token:**

```powershell
python scripts/tests_integration/smoke_connectors_discover_and_sync.py --base-url https://YOUR-SERVICE.run.app --identity-token --save-json output/e2e_01_connectors.json
```

**Optional:** `--validate-oid oid0123` to sanity-check DB rows after the run (uses same PG env as the API).

---

## 2. Ingestion (raw → processed → Pub/Sub)

### Option A — GCP workflow (recommended in prod)

Runs **gcs-file-processor** then **pubsub-dispatch** with the same `lookback_minutes` and optional `opportunity_id`.

```powershell
gcloud workflows run ingestion-pipeline --location=us-central1 --project=YOUR_PROJECT_ID --data="{\"lookback_minutes\": 0, \"opportunity_id\": \"oid0123\"}"
```

- **`lookback_minutes`: 0** → process **all** raw files for that OID (no age filter).
- Omit **`opportunity_id`** in JSON → process **all** opportunities (still heavy).

Update `workflows/ingestion_pipeline.yaml` with your Cloud Run URLs and project.

### Option B — Call Cloud Functions / Cloud Run HTTP directly

**GCS file processor** (raw → processed):

```text
POST https://<gcs-file-processor-url>?lookback_minutes=0&opportunity_id=oid0123
```

**Pub/Sub dispatch** (processed → topic):

```text
POST https://<pubsub-dispatch-url>?lookback_minutes=0&opportunity_id=oid0123
```

Use **OIDC** / auth as deployed (workflow uses OIDC audience = service URL).

### Option C — Local Python (dev only; no Pub/Sub unless you call dispatch too)

From repo root, with env loaded:

```powershell
python -c "from src.services.pipelines.gcs_pipeline import GcsPipeline; w,d = GcsPipeline().run(opportunity_id='oid0123', since=None); print('written', len(w), 'deleted', len(d))"
```

This **only** fills **`processed/`**. To enqueue RAG work you still need **`PubsubPipeline`** / **`pubsub-dispatch`** (or your ingestion subscriber) unless you test RAG separately.

**Script-style smoke** (processed file → vector ingestion message): `scripts/tests_integration/smoke_ingestion_pipeline.py` (uses `IngestionPipeline.run_message` for **one** object under `processed/` — useful for unit-style checks).

```powershell
uv run python scripts/tests_integration/smoke_ingestion_pipeline.py --opportunity-id oid1000 --source-type zoom_transcripts --create-test-file
```

---

## 3. Answer generation & RAG orchestration

### A) Mock chunks (no live retrieval)

```powershell
uv run python -m scripts.tests_integration.smoke_answer_generation
uv run python -m scripts.tests_integration.smoke_answer_generation --no-cache
```

Writes under `data/output/` (see script docstring).

### B) HTTP API (same contract as Cloud Function)

**POST `/answer-generation`** on `main:app`:

```powershell
curl -s -X POST "http://127.0.0.1:8080/answer-generation" -H "Content-Type: application/json" -d "{\"opportunity_id\":\"oid1234\",\"retrievals\":{}}"
```

Replace **`retrievals`** with the real structure your **`AnswerGenerationPipeline`** expects (chunks per question). Use **`GET /docs`** → **`POST /answer-generation`** for the exact schema.

---

## One combined report file (manual merge)

Run steps **1 → 2 → 3**, saving JSON from each, then merge:

**PowerShell** (if you have small JSON files):

```powershell
python -c "
import json, pathlib
parts = [
  json.loads(pathlib.Path('output/e2e_01_connectors.json').read_text(encoding='utf-8')),
  {'ingestion_note': 'paste HTTP response from gcs-file-processor / workflow here'},
  {'answer_generation': json.loads(pathlib.Path('data/output/your_results.json').read_text(encoding='utf-8'))},
]
pathlib.Path('output/e2e_full_stack_report.json').write_text(json.dumps({'steps': parts}, indent=2), encoding='utf-8')
print('Wrote output/e2e_full_stack_report.json')
"
```

Adjust paths to your actual saved files. For production, prefer **structured logging** + **Cloud Logging** links instead of one giant JSON.

---

## Suggested test order for your scenarios

| Goal | What to run |
|------|-------------|
| **Existing OIDs in GCS raw, never ingested** | `lookback_minutes=0` + `opportunity_id=<oid>` on **gcs-file-processor** (or local `GcsPipeline.run(oid, since=None)`), then **pubsub-dispatch** with same params. |
| **New OID: connectors + ingestion** | (1) `POST /drive/discover` + `POST /sync/trigger` (or full connector smoke), (2) workflow or HTTP ingestion with **`lookback_minutes=0`** for that OID. |
| **Answer generation / RAG** | After vectors exist for that OID, run retrieval + **`POST /answer-generation`** or **`smoke_answer_generation`** for pipeline-only tests. |

---

## Quick reference — scripts

| Script | Purpose |
|--------|---------|
| `scripts/tests_integration/smoke_connectors_discover_and_sync.py` | All connector discovers + sync; `--save-json` |
| `scripts/tests_integration/smoke_ingestion_pipeline.py` | Single-file ingestion pipeline smoke (`processed/` → embeddings path) |
| `scripts/tests_integration/smoke_answer_generation.py` | Agent / LLM answer gen with **mock** retrievals |
| `scripts/tests_integration/smoke_retrieval.py` | Retrieval smoke (optional `--no-db`) |

---

*For API route details, see `docs/API_ENDPOINTS.md`. For deployment, see `docs/runbooks/ingestion-pipeline-deployment.md` (if present) and `workflows/ingestion_pipeline.yaml`.*
