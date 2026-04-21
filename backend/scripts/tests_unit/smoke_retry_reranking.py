"""Smoke test for Phase 2b: Reranking retry (Reranker.rank / vertex_rank).

Run from repo root:
  uv run python scripts/tests_unit/smoke_retry_reranking.py
  or: PYTHONPATH=. python scripts/tests_unit/smoke_retry_reranking.py

Requires project dependencies so retrieval module imports succeed
(e.g. google-auth, requests, tenacity). Uses mocks for HTTP — no GCP
credentials or Discovery Engine required. Verifies: 503 triggers retry
then success; 404 is not retried.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests

from src.services.rag_engine.retrieval.reranking import vertex_rank


def test_retry_on_503_then_succeed():
    """Simulate 503 on first POST, success on second; assert retry and result."""
    print("\n[Test 1] Reranking: retry on 503 then succeed")
    print(
        "  Setup: mock get_http_session().post — 1st call returns 503, 2nd returns 200 with records."
    )
    query = "test query"
    candidates = [
        {"datapoint_id": "chunk_0", "text": "First chunk text"},
        {"datapoint_id": "chunk_1", "text": "Second chunk text"},
    ]
    token = "fake-token"
    keep = 2

    success_response = MagicMock()
    success_response.status_code = 200
    success_response.raise_for_status = MagicMock()
    success_response.json.return_value = {
        "records": [
            {"id": "chunk_0", "score": 0.95},
            {"id": "chunk_1", "score": 0.80},
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
        "src.services.rag_engine.retrieval.reranking.get_http_session",
        return_value=mock_session,
    ):
        result = vertex_rank(query, candidates, token, keep)

    assert call_count == 2, (
        f"expected 2 POST calls (1 fail + 1 success), got {call_count}"
    )
    assert isinstance(result, list), result
    assert len(result) == 2, f"expected 2 ranked candidates, got {len(result)}"
    assert result[0]["datapoint_id"] == "chunk_0"
    assert result[0]["rerank_score"] == 0.95
    assert result[1]["rerank_score"] == 0.80
    print(
        f"  POST calls: {call_count}. Ranked count: {len(result)}. "
        f"Top score={result[0]['rerank_score']}. PASS."
    )


def test_no_retry_on_404():
    """404 should not be retried; exception propagates after first attempt."""
    print("\n[Test 2] Reranking: no retry on 404")
    print(
        "  Setup: mock get_http_session().post — every call returns 404. Expect 1 call only."
    )
    query = "test query"
    candidates = [{"datapoint_id": "c1", "text": "chunk"}]
    token = "fake-token"
    keep = 1

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
        "src.services.rag_engine.retrieval.reranking.get_http_session",
        return_value=mock_session,
    ):
        try:
            vertex_rank(query, candidates, token, keep)
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
    print("Smoke test: Phase 2b — Reranking retry (Reranker.rank / vertex_rank)")
    print("=" * 60)
    test_retry_on_503_then_succeed()
    test_no_retry_on_404()
    print("\n" + "=" * 60)
    print("All Phase 2b smoke tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
