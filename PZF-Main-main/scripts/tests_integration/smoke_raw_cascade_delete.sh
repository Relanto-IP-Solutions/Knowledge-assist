#!/usr/bin/env bash
# Smoke test: raw→processed cascade delete.
#
# Tests the full flow:
#   1. Upload file to raw/documents
#   2. Run GcsPipeline → verify processed/documents exists
#   3. Delete file from raw/documents
#   4. Run GcsPipeline again → reconciliation should delete processed counterpart
#   5. Verify processed/documents file is gone
#
# Requires:
#   - gcloud CLI (gsutil) for upload/delete
#   - configs/.env: GCP_PROJECT_ID, GCS_BUCKET_INGESTION
#   - configs/secrets/.env: GOOGLE_APPLICATION_CREDENTIALS
#
# Usage (from repo root):
#   ./scripts/tests_integration/smoke_raw_cascade_delete.sh
#   OPP_ID=my-opp ./scripts/tests_integration/smoke_raw_cascade_delete.sh

set -e

OPP_ID="${OPP_ID:-smoke-cascade-test}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SAMPLE_PDF="${PROJECT_ROOT}/data/sample_test3.pdf"
RAW_OBJECT="sample_test3.pdf"
PROCESSED_OBJECT="sample_test3.txt"

if [[ ! -f "$SAMPLE_PDF" ]]; then
  echo "ERROR: Sample PDF not found: $SAMPLE_PDF" >&2
  exit 1
fi

cd "$PROJECT_ROOT"

# Get bucket from config
BUCKET=$(uv run python -c "
from configs.settings import get_settings
print(get_settings().ingestion.gcs_bucket_ingestion)
")

echo "=== Raw→Processed cascade delete smoke test ==="
echo "  Opportunity ID: $OPP_ID"
echo "  Bucket: $BUCKET"
echo "  Raw: $RAW_OBJECT → Processed: $PROCESSED_OBJECT"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Upload to raw/documents
# ---------------------------------------------------------------------------
echo "1. Uploading to raw/documents..."
gsutil cp "$SAMPLE_PDF" "gs://${BUCKET}/${OPP_ID}/raw/documents/${RAW_OBJECT}"
echo "   Uploaded gs://${BUCKET}/${OPP_ID}/raw/documents/${RAW_OBJECT}"
echo ""

# ---------------------------------------------------------------------------
# Step 2: Run GcsPipeline (raw → processed)
# ---------------------------------------------------------------------------
echo "2. Running GcsPipeline (raw → processed)..."
uv run python -c "
from src.services.pipelines.gcs_pipeline import GcsPipeline
from src.services.storage import Storage

storage = Storage()
pipeline = GcsPipeline(storage=storage)
written, deleted = pipeline.run_opportunity('$OPP_ID')
print(f'   Pipeline wrote: {written or \"(no new output)\"}')
if deleted:
    print(f'   Pipeline deleted (orphans): {deleted}')
"
echo ""

# ---------------------------------------------------------------------------
# Step 3: Verify processed exists
# ---------------------------------------------------------------------------
echo "3. Verifying processed/documents/${PROCESSED_OBJECT} exists..."
uv run python -c "
from src.services.storage import Storage

storage = Storage()
exists = storage.exists('processed', '$OPP_ID', 'documents', '$PROCESSED_OBJECT')
if not exists:
    raise SystemExit('FAIL: processed/documents/$PROCESSED_OBJECT not found after pipeline run')
content = storage.read('processed', '$OPP_ID', 'documents', '$PROCESSED_OBJECT')
print(f'   Found {len(content)} bytes in processed/documents/$PROCESSED_OBJECT')
print('   PASS')
"
echo ""

# ---------------------------------------------------------------------------
# Step 4: Delete from raw/documents
# ---------------------------------------------------------------------------
echo "4. Deleting from raw/documents..."
gsutil rm "gs://${BUCKET}/${OPP_ID}/raw/documents/${RAW_OBJECT}" 2>/dev/null || true
echo "   Deleted gs://${BUCKET}/${OPP_ID}/raw/documents/${RAW_OBJECT}"
echo ""

# ---------------------------------------------------------------------------
# Step 5: Run GcsPipeline again (should reconcile and delete processed)
# ---------------------------------------------------------------------------
echo "5. Running GcsPipeline again (reconciliation should delete processed)..."
uv run python -c "
from src.services.pipelines.gcs_pipeline import GcsPipeline
from src.services.storage import Storage

storage = Storage()
pipeline = GcsPipeline(storage=storage)
written, deleted = pipeline.run_opportunity('$OPP_ID')
print(f'   Pipeline wrote: {written or \"(no new output)\"}')
if deleted:
    print(f'   Pipeline deleted (orphans): {deleted}')
    if any('$PROCESSED_OBJECT' in u for u in deleted):
        print('   PASS: processed counterpart was deleted')
    else:
        print('   WARN: expected $PROCESSED_OBJECT in deleted_uris')
else:
    print('   FAIL: expected processed counterpart to be deleted (deleted_uris empty)')
    raise SystemExit(1)
"
echo ""

# ---------------------------------------------------------------------------
# Step 6: Verify processed is gone
# ---------------------------------------------------------------------------
echo "6. Verifying processed/documents/${PROCESSED_OBJECT} is gone..."
uv run python -c "
from src.services.storage import Storage

storage = Storage()
exists = storage.exists('processed', '$OPP_ID', 'documents', '$PROCESSED_OBJECT')
if exists:
    raise SystemExit('FAIL: processed/documents/$PROCESSED_OBJECT still exists (cascade delete did not work)')
print('   Processed file correctly removed')
print('   PASS')
"
echo ""
echo "=== Smoke test PASSED ==="
