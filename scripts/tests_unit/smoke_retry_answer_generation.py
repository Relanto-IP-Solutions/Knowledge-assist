"""Smoke test for Phase 2d: Answer-Generation HTTP client (_call_answer_generation).

Run from repo root:
  uv run python scripts/tests_unit/smoke_retry_answer_generation.py
  or: PYTHONPATH=. python scripts/tests_unit/smoke_retry_answer_generation.py

Requires project dependencies (e.g. google-auth, requests; pipelines import chain
may require langgraph). Mocks fetch_id_token and get_http_session().post —
no GCP credentials or Cloud Run required.

Note: ``_call_answer_generation`` does **not** retry (to avoid duplicate DB writes).
This script verifies: 503 on first POST raises (single attempt); 404 is not retried.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests

from src.services.pipelines.rag_pipeline import _call_answer_generation


def test_503_raises_single_post():
    """503 on POST raises; no automatic retry (avoids duplicate answer-generation runs)."""
    print("\n[Test 1] Answer-Generation: 503 on POST — single attempt, raises")
    print(
        "  Setup: mock fetch_id_token and get_http_session().post — "
        "POST returns 503 (no retry)."
    )
    url = "https://answer-gen.example.com/run"
    body = {"opportunity_id": "opp-1", "questions": []}

    post_call_count = 0

    def mock_post(*args, **kwargs):
        nonlocal post_call_count
        post_call_count += 1
        print("  Mock: POST attempt 1 -> 503 Service Unavailable.")
        resp = requests.Response()
        resp.status_code = 503
        raise requests.HTTPError("503 Service Unavailable", response=resp)

    mock_session = MagicMock()
    mock_session.post = MagicMock(side_effect=mock_post)
    with (
        patch(
            "src.services.pipelines.rag_pipeline.google.oauth2.id_token.fetch_id_token",
            return_value="fake-token",
        ),
        patch(
            "src.services.pipelines.rag_pipeline.get_http_session",
            return_value=mock_session,
        ),
    ):
        try:
            _call_answer_generation(url, body)
        except requests.HTTPError as e:
            assert e.response.status_code == 503
            assert post_call_count == 1, (
                f"expected 1 POST call (no retry on 503), got {post_call_count}"
            )
            print(
                f"  POST calls: {post_call_count}. HTTPError(503) propagated. PASS."
            )
            return
    raise AssertionError("expected HTTPError to propagate")


def test_no_retry_on_404():
    """404 should not be retried; exception propagates after first attempt."""
    print("\n[Test 2] Answer-Generation: no retry on 404")
    print(
        "  Setup: mock fetch_id_token and get_http_session().post — POST returns 404. Expect 1 call only."
    )
    url = "https://answer-gen.example.com/run"
    body = {"opportunity_id": "opp-1"}

    post_call_count = 0

    def mock_post(*args, **kwargs):
        nonlocal post_call_count
        post_call_count += 1
        print(f"  Mock: POST attempt {post_call_count} -> 404 Not Found.")
        resp = requests.Response()
        resp.status_code = 404
        raise requests.HTTPError("404 Not Found", response=resp)

    mock_session = MagicMock()
    mock_session.post = MagicMock(side_effect=mock_post)
    with (
        patch(
            "src.services.pipelines.rag_pipeline.google.oauth2.id_token.fetch_id_token",
            return_value="fake-token",
        ),
        patch(
            "src.services.pipelines.rag_pipeline.get_http_session",
            return_value=mock_session,
        ),
    ):
        try:
            _call_answer_generation(url, body)
        except requests.HTTPError as e:
            assert e.response.status_code == 404
            assert post_call_count == 1, (
                f"expected 1 POST call (no retry on 404), got {post_call_count}"
            )
            print(
                f"  POST calls: {post_call_count}. HTTPError(404) propagated. No retry. PASS."
            )
            return
    raise AssertionError("expected HTTPError to propagate")


def main():
    print("=" * 60)
    print(
        "Smoke test: Phase 2d — Answer-Generation HTTP client (_call_answer_generation)"
    )
    print("=" * 60)
    test_503_raises_single_post()
    test_no_retry_on_404()
    print("\n" + "=" * 60)
    print("All Phase 2d smoke tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
