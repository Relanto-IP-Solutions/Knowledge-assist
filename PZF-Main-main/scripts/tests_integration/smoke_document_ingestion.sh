#!/usr/bin/env bash
# Smoke test: upload sample PDF to raw/documents, run gcs-file-processor, verify processed/documents.
#
# Requires:
#   - gcloud CLI (gsutil) for upload
#   - configs/.env: GCP_PROJECT_ID, GCS_BUCKET_INGESTION
#   - configs/secrets/.env: GOOGLE_APPLICATION_CREDENTIALS
#
# Usage (from repo root):
#   ./scripts/tests_integration/smoke_document_ingestion.sh
#   OPP_ID=my-opp ./scripts/tests_integration/smoke_document_ingestion.sh

set -e

OPP_ID="${OPP_ID:-smoke-doc-test}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SAMPLE_PDF="${PROJECT_ROOT}/data/sample_test3.pdf"

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

echo "=== Document ingestion smoke test ==="
echo "  Opportunity ID: $OPP_ID"
echo "  Bucket: $BUCKET"
echo "  Sample PDF: $SAMPLE_PDF"
echo ""

# 1. Upload sample PDF to raw/documents
echo "1. Uploading sample PDF to raw/documents..."
gsutil cp "$SAMPLE_PDF" "gs://${BUCKET}/${OPP_ID}/raw/documents/sample_test3.pdf"
echo "   Uploaded gs://${BUCKET}/${OPP_ID}/raw/documents/sample_test3.pdf"
echo ""

# 2. Run GcsPipeline (same logic as gcs-file-processor Cloud Function)
echo "2. Running GcsPipeline (process raw → processed)..."
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

# 3. Verify processed/documents output exists
echo "3. Verifying processed/documents/sample_test3.txt..."
uv run python -c "
from src.services.storage import Storage

storage = Storage()
exists = storage.exists('processed', '$OPP_ID', 'documents', 'sample_test3.txt')
if not exists:
    raise SystemExit('FAIL: processed/documents/sample_test3.txt not found')
content = storage.read('processed', '$OPP_ID', 'documents', 'sample_test3.txt')
print(f'   Found {len(content)} bytes in processed/documents/sample_test3.txt')
print('   PASS')
"
echo ""
echo "=== Smoke test PASSED ==="
