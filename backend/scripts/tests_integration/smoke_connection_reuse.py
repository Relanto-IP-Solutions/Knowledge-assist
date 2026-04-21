"""Smoke test: shared HTTP session is used for vector search and reranking.

Run from repo root:
  uv run python scripts/tests_integration/smoke_connection_reuse.py

Mocks get_http_session() to return a single shared mock session. Runs
retrieve_topk_from_source (vector search) and vertex_rank (reranking), then
asserts the same session's post() was called the expected number of times.
No GCP credentials or real HTTP required.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.rag_engine.retrieval.reranking import vertex_rank
from src.services.rag_engine.retrieval.vector_search import (
    SourceConfig,
    retrieve_topk_from_source,
)


def test_same_session_used_for_vector_search_and_reranking():
    """One shared session; vector search + rerank both use it."""
    print("\n[Test 1] Connection reuse: same session for vector search and reranking")
    print(
        "  Setup: single mock session; patch get_http_session in vector_search and reranking."
    )

    shared_session = MagicMock()
    post_call_count = 0

    def mock_post(*args, **kwargs):
        nonlocal post_call_count
        post_call_count += 1
        if post_call_count == 1:
            # Vector search response
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "nearestNeighbors": [
                    {
                        "neighbors": [
                            {
                                "distance": 0.5,
                                "datapoint": {
                                    "datapointId": "chunk_0",
                                    "embeddingMetadata": {"text": "Chunk A"},
                                    "restricts": [],
                                },
                            }
                        ]
                    }
                ]
            }
            return resp
        # Rerank response
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {
            "records": [{"id": "chunk_0", "score": 0.9}],
        }
        return resp

    shared_session.post = MagicMock(side_effect=mock_post)

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

    with (
        patch(
            "src.services.rag_engine.retrieval.vector_search.get_http_session",
            return_value=shared_session,
        ),
        patch(
            "src.services.rag_engine.retrieval.reranking.get_http_session",
            return_value=shared_session,
        ),
    ):
        vec_result = retrieve_topk_from_source(
            source, query_embedding, opportunity_id, token, top_k
        )
        candidates = [
            {"datapoint_id": r["datapoint_id"], "text": r["text"]} for r in vec_result
        ]
        if not candidates:
            candidates = [{"datapoint_id": "chunk_0", "text": "Chunk A"}]
        rank_result = vertex_rank(
            query="test", candidates=candidates, token=token, keep=1
        )

    assert shared_session.post.call_count == 2, (
        f"expected 2 POST calls (1 vector search + 1 rerank), got {shared_session.post.call_count}"
    )
    assert len(vec_result) >= 1
    assert len(rank_result) >= 1
    print(
        f"  Same session used. post.call_count={shared_session.post.call_count}. PASS."
    )


def main():
    print("=" * 60)
    print("Smoke test: Connection reuse (shared HTTP session)")
    print("=" * 60)
    test_same_session_used_for_vector_search_and_reranking()
    print("\n" + "=" * 60)
    print("Connection reuse smoke test passed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
