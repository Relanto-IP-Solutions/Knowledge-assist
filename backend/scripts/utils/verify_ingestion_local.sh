#!/usr/bin/env bash
# Local verification for ingestion pipeline before Cloud Function deploy.
#
# Run from project root:
#   ./scripts/verify_ingestion_local.sh
#
# Prerequisites:
#   - configs/.env and configs/secrets/.env configured
#   - GOOGLE_APPLICATION_CREDENTIALS pointing to service account JSON
#   - GCP_PROJECT_ID, GCS_BUCKET_INGESTION, INDEX_RESOURCE_NAME_* set
#   - For documents: PG_* vars for registry; files in gs://{bucket}/{opp}/processed/documents/
#
# Steps:
#   1. Dry-run smoke scripts (config check)
#   2. Zoom ingestion with --create-test-file (creates file in GCS, runs pipeline)
#   3. Documents + registry (if processed/documents has files)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

OPP_ID="${OPPORTUNITY_ID:-oid-smoke-local}"

echo "=== 1. Dry-run: smoke_ingestion_pipeline ==="
uv run python scripts/tests_integration/smoke_ingestion_pipeline.py --opportunity-id "$OPP_ID" --source-type zoom_transcripts --object-name smoke_zoom.txt --dry-run
echo ""

echo "=== 2. Dry-run: smoke_rag_deletion ==="
uv run python scripts/tests_integration/smoke_rag_deletion.py --opportunity-id "$OPP_ID" --object-names "test.txt" --dry-run
echo ""

echo "=== 3. Zoom ingestion (--create-test-file): creates file in GCS, runs IngestionPipeline ==="
uv run python scripts/tests_integration/smoke_ingestion_pipeline.py --opportunity-id "$OPP_ID" --source-type zoom_transcripts --create-test-file
echo ""

echo "=== 4. Documents + registry (if you have files in processed/documents) ==="
echo "  To test manually:"
echo "  uv run python scripts/tests_integration/smoke_rag_deletion.py --opportunity-id $OPP_ID --object-names \"your-file.txt\""
echo "  (Requires: file at gs://{bucket}/$OPP_ID/processed/documents/your-file.txt, PG_* for registry)"
echo ""

echo "=== Local verification complete ==="
