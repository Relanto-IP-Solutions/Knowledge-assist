"""Smoke test for Phase 3c: Embeddings (ingestion) embed_texts retry.

Run from repo root:
  uv run python scripts/tests_unit/smoke_retry_embed_texts.py
  or: PYTHONPATH=. python scripts/tests_unit/smoke_retry_embed_texts.py

Requires project dependencies. Mocks google.genai Client — no GCP required.
Verifies: transient error on embed_content(contents=texts) triggers retry then success.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.services.rag_engine.retrieval.embedding as embedding_module
from src.services.rag_engine.retrieval.embedding import embed_texts


EMBED_DIM = 768


def _reset_embedding_service():
    embedding_module._embedding_service = None


def test_retry_on_transient_then_succeed():
    """Simulate ServiceUnavailable on first embed_content(contents=texts), success on second."""
    print("\n[Test 1] embed_texts: retry on transient then succeed")
    print(
        "  Setup: mock embed_content(contents=texts) — 1st call raises ServiceUnavailable, "
        "2nd returns list of vectors."
    )
    from google.api_core.exceptions import ServiceUnavailable

    call_count = 0

    def mock_embed_content(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            print(
                "  Mock: embed_content(batch) attempt 1 -> ServiceUnavailable (will retry)."
            )
            raise ServiceUnavailable("503")
        print("  Mock: embed_content(batch) attempt 2 -> success.")
        contents = kwargs.get("contents", [])
        return MagicMock(
            embeddings=[MagicMock(values=[0.1] * EMBED_DIM) for _ in contents]
        )

    mock_client = MagicMock()
    mock_client.models.embed_content = mock_embed_content

    with patch("google.genai.Client", return_value=mock_client):
        _reset_embedding_service()
        result = embed_texts(["text one", "text two"])

    assert call_count == 2, f"expected 2 embed_content calls, got {call_count}"
    assert len(result) == 2
    assert len(result[0]) == EMBED_DIM and len(result[1]) == EMBED_DIM
    print(
        f"  embed_content calls: {call_count}. Vectors: {len(result)} x {len(result[0])}. PASS."
    )


def main():
    print("=" * 60)
    print("Smoke test: Phase 3c — Embeddings (ingestion) embed_texts retry")
    print("=" * 60)
    test_retry_on_transient_then_succeed()
    print("\n" + "=" * 60)
    print("All Phase 3c smoke tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
