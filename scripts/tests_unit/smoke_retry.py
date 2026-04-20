"""Smoke test for Phase 1: shared retry decorator (retry_on_transient).

Run from repo root:
  uv run python scripts/tests_unit/smoke_retry.py
  or: PYTHONPATH=. python scripts/tests_unit/smoke_retry.py

Requires: tenacity, requests (no GCP or retrieval deps).
Tests: retry on ConnectionError then success; retry on 503 then success; no retry on 404.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import contextlib

from src.utils.retry import retry_on_transient


@retry_on_transient(max_attempts=3)
def _call_that_fails_then_succeeds(calls):
    """Increment calls[0]; raise ConnectionError on first call, then return 42."""
    calls[0] += 1
    if calls[0] == 1:
        import requests

        raise requests.ConnectionError("simulated")
    return 42


def test_retry_connection_error_then_success():
    print("\n[Test 1] Retry on ConnectionError then success")
    print("  Expect: attempt 1 raises ConnectionError, retry, attempt 2 returns 42.")
    calls = [0]
    result = _call_that_fails_then_succeeds(calls)
    assert result == 42
    assert calls[0] == 2
    print(f"  Attempts made: {calls[0]}. Result: {result}. PASS.")


@retry_on_transient(max_attempts=3)
def _call_503_then_success(calls):
    import requests

    calls[0] += 1
    if calls[0] == 1:
        r = requests.Response()
        r.status_code = 503
        raise requests.HTTPError(response=r)
    return "ok"


def test_retry_503_then_success():
    print("\n[Test 2] Retry on HTTP 503 then success")
    print("  Expect: attempt 1 raises HTTPError(503), retry, attempt 2 returns 'ok'.")
    calls = [0]
    result = _call_503_then_success(calls)
    assert result == "ok"
    assert calls[0] == 2
    print(f"  Attempts made: {calls[0]}. Result: {result!r}. PASS.")


@retry_on_transient(max_attempts=3)
def _call_404_no_retry(calls):
    import requests

    calls[0] += 1
    r = requests.Response()
    r.status_code = 404
    raise requests.HTTPError(response=r)


def test_no_retry_on_404():
    print("\n[Test 3] No retry on HTTP 404")
    print("  Expect: attempt 1 raises HTTPError(404), no retry, total attempts = 1.")
    calls = [0]
    with contextlib.suppress(Exception):
        _call_404_no_retry(calls)
    assert calls[0] == 1
    print(
        f"  Attempts made: {calls[0]} (no retry). Exception raised as expected. PASS."
    )


def main():
    print("=" * 60)
    print("Smoke test: Phase 1 — shared retry decorator (retry_on_transient)")
    print("=" * 60)
    test_retry_connection_error_then_success()
    test_retry_503_then_success()
    test_no_retry_on_404()
    print("\n" + "=" * 60)
    print("All Phase 1 retry smoke tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
