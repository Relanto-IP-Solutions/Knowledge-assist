"""Smoke test for Phase 3a: Storage (GCS) retry.

Run from repo root:
  uv run python scripts/tests_unit/smoke_retry_storage.py
  or: PYTHONPATH=. python scripts/tests_unit/smoke_retry_storage.py

Requires project dependencies. Mocks GCS bucket/blob — no real GCS required.
Verifies: transient error triggers retry then success; NotFound is not retried.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from google.cloud.exceptions import NotFound

from src.services.storage.service import Storage


def test_retry_on_transient_then_succeed():
    """Simulate transient error on first download_as_bytes, success on second."""
    print("\n[Test 1] Storage read: retry on transient then succeed")
    print(
        "  Setup: mock bucket/blob — download_as_bytes: 1st raises ServiceUnavailable, "
        "2nd returns b'ok'."
    )
    from google.api_core.exceptions import ServiceUnavailable

    call_count = 0

    def mock_download(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            print(
                "  Mock: download_as_bytes attempt 1 -> ServiceUnavailable (will retry)."
            )
            raise ServiceUnavailable("503")
        print("  Mock: download_as_bytes attempt 2 -> success.")
        return b"ok"

    mock_blob = MagicMock()
    mock_blob.download_as_bytes = mock_download
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_bucket.name = "test-bucket"

    with patch.object(Storage, "_get_bucket", return_value=mock_bucket):
        storage = Storage()
        result = storage.read("processed", "opp-1", "documents", "file.txt")

    assert call_count == 2, f"expected 2 download calls, got {call_count}"
    assert result == b"ok"
    print(f"  download_as_bytes calls: {call_count}. Result: {result!r}. PASS.")


def test_no_retry_on_not_found():
    """NotFound should not be retried; FileNotFoundError propagates after first attempt."""
    print("\n[Test 2] Storage read: no retry on NotFound")
    print("  Setup: mock download_as_bytes raises NotFound. Expect 1 call only.")

    call_count = 0

    def mock_download(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        print(f"  Mock: download_as_bytes attempt {call_count} -> NotFound.")
        raise NotFound("object not found")

    mock_blob = MagicMock()
    mock_blob.download_as_bytes = mock_download
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_bucket.name = "test-bucket"

    with patch.object(Storage, "_get_bucket", return_value=mock_bucket):
        storage = Storage()
        try:
            storage.read("processed", "opp-1", "documents", "missing.txt")
        except FileNotFoundError:
            assert call_count == 1, (
                f"expected 1 call (no retry on NotFound), got {call_count}"
            )
            print(
                f"  download_as_bytes calls: {call_count}. FileNotFoundError. No retry. PASS."
            )
            return
    raise AssertionError("expected FileNotFoundError to propagate")


def main():
    print("=" * 60)
    print("Smoke test: Phase 3a — Storage (GCS) retry")
    print("=" * 60)
    test_retry_on_transient_then_succeed()
    test_no_retry_on_not_found()
    print("\n" + "=" * 60)
    print("All Phase 3a smoke tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
