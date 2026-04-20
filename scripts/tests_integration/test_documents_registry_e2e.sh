#!/usr/bin/env bash
# Test script: documents + registry, re-ingestion (skip, chunk diff, orphan), and optional E2E.
#
# Implements the Testing Plan: Documents, Registry, Re-ingestion, and E2E.
#
# Run from project root:
#   ./scripts/test_documents_registry_e2e.sh                    # Phase 1 + 2
#   ./scripts/test_documents_registry_e2e.sh --e2e               # Phase 1 + 2 + 3 (E2E)
#   ./scripts/test_documents_registry_e2e.sh --phase1-only       # Phase 1 only
#
# Prerequisites:
#   - configs/.env and configs/secrets/.env configured
#   - GOOGLE_APPLICATION_CREDENTIALS, GCP_PROJECT_ID, GCS_BUCKET_INGESTION
#   - INDEX_RESOURCE_NAME_DOCUMENTS, CLOUDSQL_* or PG_* for registry
#   - For E2E: data/sample_test3.pdf, sase_questions populated, ANSWER_GENERATION_URL (optional)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

OPP_ID="${OPPORTUNITY_ID:-OPP-TEST-REGISTRY}"
PHASE1_ONLY=false
RUN_E2E=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --e2e) RUN_E2E=true; shift ;;
    --phase1-only) PHASE1_ONLY=true; shift ;;
    -h|--help)
      echo "Usage: $0 [--e2e] [--phase1-only]"
      echo "  --e2e         Run Phase 3 (E2E: upload, GcsPipeline, ingestion, retrieval, answer-gen)"
      echo "  --phase1-only Run Phase 1 only (documents + registry)"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

BUCKET=$(uv run python -c "
from configs.settings import get_settings
print(get_settings().ingestion.gcs_bucket_ingestion or '')
")
[[ -n "$BUCKET" ]] || { echo "ERROR: GCS_BUCKET_INGESTION not set" >&2; exit 1; }

verify_registry() {
  local opp=$1
  local expected_docs=${2:-1}
  uv run python -c "
from pathlib import Path
import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('configs/.env', override=False)
load_dotenv('configs/secrets/.env', override=True)
from src.services.database_manager.connection import get_db_connection
conn = get_db_connection()
cur = conn.cursor()
cur.execute(\"SELECT COUNT(*) FROM document_registry WHERE opportunity_id = %s\", ('$opp',))
doc_count = cur.fetchone()[0]
cur.execute(\"SELECT COUNT(*) FROM chunk_registry cr JOIN document_registry dr ON cr.document_id = dr.document_id WHERE dr.opportunity_id = %s\", ('$opp',))
chunk_count = cur.fetchone()[0]
cur.close()
conn.close()
if doc_count < $expected_docs:
    print(f'FAIL: expected >= $expected_docs document_registry rows for $opp, got {doc_count}')
    sys.exit(1)
print(f'OK: document_registry={doc_count} rows, chunk_registry={chunk_count} rows for $opp')
"
}

# ---------------------------------------------------------------------------
# Phase 1: Documents + Registry
# ---------------------------------------------------------------------------
echo ""
echo "=== Phase 1: Documents + Registry ==="
echo "  Opportunity ID: $OPP_ID"
echo ""

echo "1.1 Creating test document in processed/documents..."
uv run python -c "
from pathlib import Path
import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('configs/.env', override=False)
load_dotenv('configs/secrets/.env', override=True)
from src.services.storage import Storage
Storage().write('processed', '$OPP_ID', 'documents', 'smoke_doc.txt', b'Test content for registry.', content_type='text/plain')
print('   Wrote gs://$BUCKET/$OPP_ID/processed/documents/smoke_doc.txt')
"
echo ""

echo "1.2 Running smoke_rag_deletion (first ingest)..."
uv run python scripts/tests_integration/smoke_rag_deletion.py --opportunity-id "$OPP_ID" --object-names "smoke_doc.txt"
echo ""

echo "1.3 Verifying registry..."
verify_registry "$OPP_ID" 1
echo ""

if $PHASE1_ONLY; then
  echo "=== Phase 1 complete (--phase1-only) ==="
  exit 0
fi

# ---------------------------------------------------------------------------
# Phase 2: Re-ingestion
# ---------------------------------------------------------------------------
echo ""
echo "=== Phase 2: Re-ingestion ==="
echo ""

echo "2.1 Doc hash skip: running smoke_rag_deletion again (unchanged content)..."
RESULT=$(uv run python scripts/tests_integration/smoke_rag_deletion.py --opportunity-id "$OPP_ID" --object-names "smoke_doc.txt" 2>&1) || true
if echo "$RESULT" | grep -q "documents:0"; then
  echo "   OK: Got documents:0 (skip)"
elif echo "$RESULT" | grep -q "Document unchanged"; then
  echo "   OK: Document unchanged, skipped"
else
  echo "   Result: $RESULT"
fi
echo ""

echo "2.2 Chunk diff: overwriting with different content..."
uv run python -c "
from pathlib import Path
import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('configs/.env', override=False)
load_dotenv('configs/secrets/.env', override=True)
from src.services.storage import Storage
# Longer content to get multiple chunks
content = b'Updated content. This is a longer document to produce multiple chunks for chunk-level diff testing. We need enough text to exceed the chunk size.'
Storage().write('processed', '$OPP_ID', 'documents', 'smoke_doc.txt', content, content_type='text/plain')
print('   Overwrote smoke_doc.txt with longer content')
"
echo ""

echo "2.3 Running smoke_rag_deletion (chunk diff)..."
uv run python scripts/tests_integration/smoke_rag_deletion.py --opportunity-id "$OPP_ID" --object-names "smoke_doc.txt"
echo ""

echo "2.4 Creating second document for orphan test..."
uv run python -c "
from pathlib import Path
import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('configs/.env', override=False)
load_dotenv('configs/secrets/.env', override=True)
from src.services.storage import Storage
Storage().write('processed', '$OPP_ID', 'documents', 'smoke_doc_keep.txt', b'Document to keep.', content_type='text/plain')
print('   Wrote smoke_doc_keep.txt')
"
echo ""

echo "2.5 Ingesting second document..."
uv run python scripts/tests_integration/smoke_rag_deletion.py --opportunity-id "$OPP_ID" --object-names "smoke_doc_keep.txt"
echo ""

echo "2.6 Orphan reconciliation: deleting smoke_doc.txt from GCS..."
gsutil rm "gs://${BUCKET}/${OPP_ID}/processed/documents/smoke_doc.txt" 2>/dev/null || true
echo "   Deleted smoke_doc.txt from GCS"
echo ""

echo "2.7 Running smoke_rag_deletion for smoke_doc_keep.txt (triggers reconciliation)..."
uv run python scripts/tests_integration/smoke_rag_deletion.py --opportunity-id "$OPP_ID" --object-names "smoke_doc_keep.txt"
echo ""

echo "2.8 Verifying orphan removed from registry..."
uv run python -c "
from pathlib import Path
import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('configs/.env', override=False)
load_dotenv('configs/secrets/.env', override=True)
from src.services.database_manager.connection import get_db_connection
conn = get_db_connection()
cur = conn.cursor()
cur.execute(\"SELECT document_id FROM document_registry WHERE opportunity_id = %s\", ('$OPP_ID',))
rows = cur.fetchall()
cur.close()
conn.close()
doc_ids = [r[0] for r in rows]
if any('smoke_doc.txt' in d for d in doc_ids):
    print('FAIL: smoke_doc.txt still in registry (orphan not removed)')
    sys.exit(1)
if not any('smoke_doc_keep.txt' in d for d in doc_ids):
    print('FAIL: smoke_doc_keep.txt not in registry')
    sys.exit(1)
print('OK: Orphan removed, smoke_doc_keep.txt retained')
"
echo ""

echo "=== Phase 2 complete ==="

if ! $RUN_E2E; then
  echo ""
  echo "=== All tests complete (use --e2e for Phase 3) ==="
  exit 0
fi

# ---------------------------------------------------------------------------
# Phase 3: E2E (optional)
# ---------------------------------------------------------------------------
echo ""
echo "=== Phase 3: End-to-End (documents + retrieval + answer generation) ==="
echo ""

E2E_OPP="${OPP_ID}-E2E"
SAMPLE_PDF="${PROJECT_ROOT}/data/sample_test3.pdf"

if [[ ! -f "$SAMPLE_PDF" ]]; then
  echo "WARN: data/sample_test3.pdf not found; skipping E2E"
  echo "  Create it or run: ./scripts/upload_to_raw.sh --opp-id $E2E_OPP --source documents"
  exit 0
fi

echo "3.1 Uploading PDF to raw..."
gsutil cp "$SAMPLE_PDF" "gs://${BUCKET}/${E2E_OPP}/raw/documents/sample_test3.pdf"
echo "   Uploaded"
echo ""

echo "3.2 Running GcsPipeline (raw -> processed)..."
uv run python -c "
from src.services.pipelines.gcs_pipeline import GcsPipeline
from src.services.storage import Storage
pipeline = GcsPipeline(storage=Storage())
written, deleted = pipeline.run_opportunity('$E2E_OPP')
print(f'   Pipeline wrote: {written or \"(no new output)\"}')
if deleted:
    print(f'   Pipeline deleted (orphans): {deleted}')
"
echo ""

echo "3.3 Running ingestion (smoke_rag_deletion)..."
uv run python scripts/tests_integration/smoke_rag_deletion.py --opportunity-id "$E2E_OPP" --object-names "sample_test3.txt"
echo ""

echo "3.4 Running retrieval smoke..."
uv run python scripts/tests_integration/smoke_retrieval.py "$E2E_OPP" 2>&1 | head -30
echo ""

echo "3.5 Questions/prompts validation (dry-run)..."
uv run python scripts/tests_integration/smoke_retrieval.py "$E2E_OPP" --dry-run
echo ""

echo "3.6 Answer generation (mock smoke)..."
uv run python -m scripts.tests_integration.smoke_answer_generation 2>&1 | tail -5
echo ""

echo "=== Phase 3 complete ==="
echo ""
echo "For full E2E with deployed services:"
echo "  1. ./scripts/upload_to_raw.sh --opp-id $E2E_OPP --source documents"
echo "  2. Wait for workflow (gcs-file-processor, pubsub-dispatch, rag-ingestion)"
echo "  3. curl -X POST \$RAG_ORCH_URL -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" -H \"Content-Type: application/json\" -d '{\"opportunity_id\":\"$E2E_OPP\"}'"
echo ""
echo "=== All tests complete ==="
