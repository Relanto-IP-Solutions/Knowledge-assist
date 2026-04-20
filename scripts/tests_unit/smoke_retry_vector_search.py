"""Smoke test for Phase 2a: Vector Search retry (retrieve_topk_from_source).

Run: python scripts/tests_unit/smoke_retry_vector_search.py
     or: uv run python scripts/tests_unit/smoke_retry_vector_search.py

Requires project dependencies so retrieval module imports succeed:
  pip install -r requirements.txt   (with venv active)

Uses mocks for HTTP — no GCP credentials or Vector Search indexes required.
Verifies that a 503 response triggers one retry and the second call succeeds.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


# Repo root
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Avoid loading configs that may require env; we only need vector_search + retry
import requests

from src.services.rag_engine.retrieval.vector_search import (
    SourceConfig,
    retrieve_topk_from_source,
)


def test_retry_on_503_then_succeed():
    """Simulate 503 on first POST, success on second; assert retry and result."""
    print("\n[Test 1] Vector Search: retry on 503 then succeed")
    print(
        "  Setup: mock get_http_session().post — 1st call returns 503, 2nd returns 200 with neighbors."
    )
    source = SourceConfig(
        name="drive",
        public_domain="https://example.vdb.vertexai.goog",
        index_endpoint="projects/p/locations/us-central1/indexEndpoints/eid",
        deployed_index_id="deployed_docs",
    )
    query_embedding = [0.1] * 768
    opportunity_id = "test-opp"
    token = "fake-token"
    top_k = 5

    success_response = MagicMock()
    success_response.status_code = 200
    success_response.raise_for_status = MagicMock()
    success_response.json.return_value = {
        "nearestNeighbors": [
            {
                "neighbors": [
                    {
                        "distance": 0.5,
                        "datapoint": {
                            "datapointId": "chunk_0",
                            "embeddingMetadata": {"text": "Sample chunk text"},
                            "restricts": [],
                        },
                    }
                ]
            }
        ]
    }

    call_count = 0

    def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            print("  Mock: POST attempt 1 -> 503 Service Unavailable (will retry).")
            resp = requests.Response()
            resp.status_code = 503
            raise requests.HTTPError("503 Service Unavailable", response=resp)
        print("  Mock: POST attempt 2 -> 200 OK.")
        return success_response

    mock_session = MagicMock()
    mock_session.post = MagicMock(side_effect=mock_post)
    with patch(
        "src.services.rag_engine.retrieval.vector_search.get_http_session",
        return_value=mock_session,
    ):
        result = retrieve_topk_from_source(
            source, query_embedding, opportunity_id, token, top_k
        )

    assert call_count == 2, (
        f"expected 2 POST calls (1 fail + 1 success), got {call_count}"
    )
    assert isinstance(result, list), result
    assert len(result) == 1, f"expected 1 neighbor, got {len(result)}"
    assert result[0]["source_name"] == "drive"
    assert result[0]["text"] == "Sample chunk text"
    print(
        f"  POST calls: {call_count}. Neighbors returned: {len(result)}. source_name={result[0]['source_name']!r}. PASS."
    )


def test_no_retry_on_404():
    """404 should not be retried; exception propagates after first attempt."""
    print("\n[Test 2] Vector Search: no retry on 404")
    print(
        "  Setup: mock get_http_session().post — every call returns 404. Expect 1 call only."
    )
    source = SourceConfig(
        name="drive",
        public_domain="https://example.vdb.vertexai.goog",
        index_endpoint="projects/p/locations/us-central1/indexEndpoints/eid",
        deployed_index_id="deployed_docs",
    )
    query_embedding = [0.1] * 768
    opportunity_id = "test-opp"
    token = "fake-token"
    top_k = 5

    call_count = 0

    def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        print(f"  Mock: POST attempt {call_count} -> 404 Not Found.")
        resp = requests.Response()
        resp.status_code = 404
        raise requests.HTTPError("404 Not Found", response=resp)

    mock_session = MagicMock()
    mock_session.post = MagicMock(side_effect=mock_post)
    with patch(
        "src.services.rag_engine.retrieval.vector_search.get_http_session",
        return_value=mock_session,
    ):
        try:
            retrieve_topk_from_source(
                source, query_embedding, opportunity_id, token, top_k
            )
        except requests.HTTPError as e:
            assert e.response.status_code == 404
            assert call_count == 1, (
                f"expected 1 call (no retry on 404), got {call_count}"
            )
            print(
                f"  POST calls: {call_count}. HTTPError(404) propagated. No retry. PASS."
            )
            return
    raise AssertionError("expected HTTPError to propagate")


def main():
    print("=" * 60)
    print("Smoke test: Phase 2a — Vector Search retry (retrieve_topk_from_source)")
    print("=" * 60)
    test_retry_on_503_then_succeed()
    test_no_retry_on_404()
    print("\n" + "=" * 60)
    print("All Phase 2a smoke tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
