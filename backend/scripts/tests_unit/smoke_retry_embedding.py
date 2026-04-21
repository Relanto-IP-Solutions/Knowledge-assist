"""Smoke test for Phase 2c: Embeddings (retrieval) retry (embed_question).

Run from repo root:
  uv run python scripts/tests_unit/smoke_retry_embedding.py
  or: PYTHONPATH=. python scripts/tests_unit/smoke_retry_embedding.py

Requires project dependencies so retrieval module imports succeed
(e.g. google-auth, tenacity). Mocks google.genai Client — no GCP
credentials required. Verifies: transient error triggers retry then success;
non-transient error is not retried.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import after path setup; need embedding module for singleton reset and embed_question
import src.services.rag_engine.retrieval.embedding as embedding_module
from src.services.rag_engine.retrieval.embedding import embed_question


# Standard embedding dimension for text-embedding-004
EMBED_DIM = 768


def _reset_embedding_service():
    """Reset singleton so next embed_question uses fresh service and mocks."""
    embedding_module._embedding_service = None


def test_retry_on_transient_then_succeed():
    """Simulate ServiceUnavailable on first embed_content, success on second."""
    print("\n[Test 1] Embedding: retry on transient (ServiceUnavailable) then succeed")
    print(
        "  Setup: mock google.genai Client — embed_content: "
        "1st call raises ServiceUnavailable, 2nd returns vector."
    )
    from google.api_core.exceptions import ServiceUnavailable

    call_count = 0

    def mock_embed_content(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            print("  Mock: embed_content attempt 1 -> ServiceUnavailable (will retry).")
            raise ServiceUnavailable("503")
        print("  Mock: embed_content attempt 2 -> success.")
        return MagicMock(embeddings=[MagicMock(values=[0.1] * EMBED_DIM)])

    mock_client = MagicMock()
    mock_client.models.embed_content = mock_embed_content

    with patch("google.genai.Client", return_value=mock_client):
        _reset_embedding_service()
        result = embed_question("test question")

    assert call_count == 2, (
        f"expected 2 embed_content calls (1 fail + 1 success), got {call_count}"
    )
    assert isinstance(result, list), result
    assert len(result) == EMBED_DIM, f"expected dim {EMBED_DIM}, got {len(result)}"
    assert result[0] == 0.1
    print(f"  embed_content calls: {call_count}. Vector dim: {len(result)}. PASS.")


def test_no_retry_on_invalid_argument():
    """InvalidArgument should not be retried; exception propagates after first attempt."""
    print("\n[Test 2] Embedding: no retry on InvalidArgument")
    print(
        "  Setup: mock embed_content — first call raises InvalidArgument. Expect 1 call only."
    )
    from google.api_core.exceptions import InvalidArgument

    call_count = 0

    def mock_embed_content(**kwargs):
        nonlocal call_count
        call_count += 1
        print(f"  Mock: embed_content attempt {call_count} -> InvalidArgument.")
        raise InvalidArgument("bad request")

    mock_client = MagicMock()
    mock_client.models.embed_content = mock_embed_content

    with patch("google.genai.Client", return_value=mock_client):
        _reset_embedding_service()
        try:
            embed_question("test")
        except InvalidArgument:
            assert call_count == 1, (
                f"expected 1 embed_content call (no retry on InvalidArgument), got {call_count}"
            )
            print(
                f"  embed_content calls: {call_count}. InvalidArgument propagated. No retry. PASS."
            )
            return
    raise AssertionError("expected InvalidArgument to propagate")


def main():
    print("=" * 60)
    print("Smoke test: Phase 2c — Embeddings (retrieval) retry (embed_question)")
    print("=" * 60)
    test_retry_on_transient_then_succeed()
    test_no_retry_on_invalid_argument()
    print("\n" + "=" * 60)
    print("All Phase 2c smoke tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
