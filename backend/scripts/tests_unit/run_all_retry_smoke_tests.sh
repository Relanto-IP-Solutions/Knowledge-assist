#!/usr/bin/env bash
# Run all four phases of client-level retry smoke tests (stop on first failure).
# Usage: ./scripts/tests_unit/run_all_retry_smoke_tests.sh
# Uses uv run if available, otherwise PYTHONPATH=. python.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"

if command -v uv &>/dev/null; then
  RUN="uv run python"
else
  export PYTHONPATH="${ROOT}"
  RUN="python"
fi

echo "=== Phase 1: Shared retry utility ==="
$RUN scripts/tests_unit/smoke_retry.py

echo ""
echo "=== Phase 2: High-priority clients ==="
$RUN scripts/tests_unit/smoke_retry_vector_search.py
$RUN scripts/tests_unit/smoke_retry_reranking.py
$RUN scripts/tests_unit/smoke_retry_embedding.py
$RUN scripts/tests_unit/smoke_retry_answer_generation.py

echo ""
echo "=== Phase 3: Medium-priority clients ==="
$RUN scripts/tests_unit/smoke_retry_storage.py
$RUN scripts/tests_unit/smoke_retry_pubsub.py
$RUN scripts/tests_unit/smoke_retry_embed_texts.py
$RUN scripts/tests_unit/smoke_retry_vertex_index.py

echo ""
echo "=== Phase 4: Low-priority (cache manager) ==="
$RUN scripts/tests_unit/smoke_retry_cache_manager.py

echo ""
echo "=== All 4 phases of retry smoke tests passed ==="
