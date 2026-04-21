"""Smoke test for Phase 3d: VertexIndexClient upsert_datapoints retry.

Run from repo root:
  uv run python scripts/tests_unit/smoke_retry_vertex_index.py
  or: PYTHONPATH=. python scripts/tests_unit/smoke_retry_vertex_index.py

Requires project dependencies. Mocks IndexServiceClient — no Vertex AI index required.
Verifies: transient error on upsert_datapoints triggers retry then success.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from google.api_core.exceptions import ServiceUnavailable

from src.services.vertex_index.client import VertexIndexClient


def test_retry_on_transient_then_succeed():
    """Simulate ServiceUnavailable on first upsert_datapoints, success on second."""
    print(
        "\n[Test 1] VertexIndexClient.upsert_datapoints: retry on transient then succeed"
    )
    print(
        "  Setup: mock IndexServiceClient.upsert_datapoints — "
        "1st call raises ServiceUnavailable, 2nd succeeds."
    )

    call_count = 0

    def mock_upsert(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            print(
                "  Mock: upsert_datapoints attempt 1 -> ServiceUnavailable (will retry)."
            )
            raise ServiceUnavailable("503")
        print("  Mock: upsert_datapoints attempt 2 -> success.")

    mock_client = MagicMock()
    mock_client.upsert_datapoints = mock_upsert

    with patch(
        "src.services.vertex_index.client.aiplatform_v1.IndexServiceClient",
        return_value=mock_client,
    ):
        client = VertexIndexClient()
        client.upsert_datapoints(
            index_resource_name="projects/p/locations/us-central1/indexes/idx",
            datapoints=[
                {
                    "datapoint_id": "dp0",
                    "restricts": [],
                    "embedding_metadata": {"text": "chunk"},
                }
            ],
            embeddings=[[0.1] * 768],
            api_endpoint="us-central1-aiplatform.googleapis.com",
        )

    assert call_count == 2, f"expected 2 upsert_datapoints calls, got {call_count}"
    print(f"  upsert_datapoints calls: {call_count}. PASS.")


def main():
    print("=" * 60)
    print("Smoke test: Phase 3d — VertexIndexClient retry")
    print("=" * 60)
    test_retry_on_transient_then_succeed()
    print("\n" + "=" * 60)
    print("All Phase 3d smoke tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
