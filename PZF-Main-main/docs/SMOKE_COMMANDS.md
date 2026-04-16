# Smoke test commands (quick reference)

Run from the **repository root** (`Project-PZF/`). On Windows PowerShell, use `;` instead of `\\` line continuation or put the command on one line.

---

## 1. Data connectors (discover + sync)

**File:** `scripts/tests_integration/smoke_connectors_discover_and_sync.py`

**What it does:** Calls `POST /slack/discover`, `/gmail/discover`, `/drive/discover`, `/zoom/discover`, then `POST /sync/trigger` (or use `--sync-run` for a single `POST /sync/run`).

```powershell
python scripts/tests_integration/smoke_connectors_discover_and_sync.py --base-url http://127.0.0.1:8080 --save-json output/smoke_connectors.json
```

**Scheduler-style (one call):**

```powershell
python scripts/tests_integration/smoke_connectors_discover_and_sync.py --base-url http://127.0.0.1:8080 --sync-run --save-json output/smoke_connectors_sync_run.json
```

**Cloud Run (authenticated):**

```powershell
python scripts/tests_integration/smoke_connectors_discover_and_sync.py --base-url https://YOUR-SERVICE.run.app --identity-token --save-json output/smoke_connectors.json
```

---

## 2. Ingestion (raw → processed in GCS)

### Option A — Full pipeline smoke (single processed object → embeddings path)

**File:** `scripts/tests_integration/smoke_ingestion_pipeline.py`

```powershell
uv run python scripts/tests_integration/smoke_ingestion_pipeline.py --dry-run
uv run python scripts/tests_integration/smoke_ingestion_pipeline.py --opportunity-id oid1000 --source-type zoom_transcripts --create-test-file
```

### Option B — Local `GcsPipeline` for one OID (all raw under that OID, no time window)

**No separate file** — one-liner (same logic as `smoke_e2e_merge.py` ingestion step):

```powershell
python -c "from src.services.pipelines.gcs_pipeline import GcsPipeline; from src.utils.opportunity_id import normalize_opportunity_oid; o=normalize_opportunity_oid('oid0123'); w,d=GcsPipeline().run(opportunity_id=o, since=None); print('written',len(w),'deleted',len(d))"
```

### Option C — GCP (Cloud Run `gcs-file-processor`)

Replace URL and OID:

```powershell
curl.exe -s -X POST "https://<GCS_FILE_PROCESSOR_URL>?lookback_minutes=0&opportunity_id=oid0123"
```

### Option D — **Full stack** (gcs-file-processor + pubsub-dispatch + RAG ingestion)

The **workflow** `ingestion-pipeline` (see `workflows/ingestion_pipeline.yaml`) POSTs to **gcs-file-processor**, then **pubsub-dispatch**. **rag-ingestion** runs when **Pub/Sub** delivers messages to your deployed subscriber (usually automatic after step 2).

**Prerequisites:** Workflow deployed; YAML `gcs_processor_url` / `pubsub_dispatch_url` point at your Cloud Run services; Pub/Sub subscription pushes to **rag-ingestion**.

**Why `lookback_minutes=0` after connectors ran hours ago**  
The Cloud Functions only consider blobs **updated within the last N minutes** when `N > 0`. If you synced raw to GCS earlier today, use **`lookback_minutes=0`** so nothing is skipped by age. Otherwise use e.g. `1440` (24h) if you only want “recent” files.

**Recommended smoke script** (same defaults: `lookback_minutes=0`):

```powershell
uv run python scripts/tests_integration/smoke_ingestion_cloud_workflow.py --project YOUR_PROJECT_ID
uv run python scripts/tests_integration/smoke_ingestion_cloud_workflow.py --project YOUR_PROJECT_ID --opportunity-id oid0123
uv run python scripts/tests_integration/smoke_ingestion_cloud_workflow.py --project YOUR_PROJECT_ID --dry-run
```

**Raw `gcloud` (equivalent)**

**All opportunities:**

```powershell
gcloud workflows run ingestion-pipeline --location=us-central1 --project=YOUR_PROJECT_ID --data='{"lookback_minutes":0,"opportunity_id":""}'
```

**Single OID** (e.g. `oid0123`):

```powershell
gcloud workflows run ingestion-pipeline --location=us-central1 --project=YOUR_PROJECT_ID --data='{"lookback_minutes":0,"opportunity_id":"oid0123"}'
```

(Bash/Linux: same `--data='...'` form works.)

Replace `us-central1`, `YOUR_PROJECT_ID`, and the workflow name if yours differs. Watch execution: `gcloud workflows executions describe ...` or Cloud Console → Workflows.

**Note:** If you only `curl` one Cloud Run URL, you skip pubsub-dispatch and RAG will not run unless you also invoke **pubsub-dispatch** (or run the workflow).

---

## 3. Answer generation (mock retrievals → LLM)

**File:** `scripts/tests_integration/smoke_answer_generation.py`

```powershell
uv run python -m scripts.tests_integration.smoke_answer_generation
uv run python -m scripts.tests_integration.smoke_answer_generation --no-cache
```

Output is written under `data/output/` (see script log line `Written: ...`).

**HTTP API (live pipeline shape):**

```powershell
curl.exe -s -X POST "http://127.0.0.1:8080/answer-generation" -H "Content-Type: application/json" -d "{\"opportunity_id\":\"oid1234\",\"retrievals\":{}}"
```

(Adjust `retrievals` to match your real payload; see `GET /docs` → `POST /answer-generation`.)

### 3a. RAG orchestrator (deployed — retrieval + answer-generation chain)

**File:** `scripts/tests_integration/smoke_rag_orchestrator.py`  
Wraps `gcloud functions call rag-orchestrator` so Windows does not break `--data` JSON.

```powershell
uv run python scripts/tests_integration/smoke_rag_orchestrator.py --project eighth-bivouac-490806-s2 --opportunity-id oid1111
uv run python scripts/tests_integration/smoke_rag_orchestrator.py --project eighth-bivouac-490806-s2 --batch
```

See `docs/GCP_REDEPLOY_COMMANDS.md` §0.8.

---

## 4. All-in-one merged report (connectors + ingestion + answer gen)

**File:** `scripts/tests_integration/smoke_e2e_merge.py`

Runs (1) connector smoke to a temp file merged into JSON, (2) `GcsPipeline.run` for `--opportunity-id`, (3) `smoke_answer_generation`, then writes **one** JSON.

```powershell
python scripts/tests_integration/smoke_e2e_merge.py --base-url http://127.0.0.1:8080 --opportunity-id oid0123 --save-json output/e2e_merged.json
```

**Connectors only:**

```powershell
python scripts/tests_integration/smoke_e2e_merge.py --skip-ingestion --skip-answer-generation --save-json output/e2e_connectors_only.json
```

**Skip connectors (ingestion + answer gen only):**

```powershell
python scripts/tests_integration/smoke_e2e_merge.py --skip-connectors --opportunity-id oid0123 --save-json output/e2e_ingestion_and_answers.json
```

**Dry run (print planned steps):**

```powershell
python scripts/tests_integration/smoke_e2e_merge.py --opportunity-id oid0123 --dry-run
```

---

More detail: `docs/SMOKE_E2E_GUIDE.md`, API routes: `docs/API_ENDPOINTS.md`.
