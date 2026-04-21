"""Smoke test for Phase 3b: Pub/Sub Publisher retry.

Run from repo root:
  uv run python scripts/tests_unit/smoke_retry_pubsub.py
  or: PYTHONPATH=. python scripts/tests_unit/smoke_retry_pubsub.py

Requires project dependencies. Mocks publish future.result() — no real Pub/Sub required.
Verifies: transient error triggers retry then success.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from google.api_core.exceptions import DeadlineExceeded

from src.services.pubsub.publisher import Publisher


def test_retry_on_transient_then_succeed():
    """Simulate DeadlineExceeded on first future.result(), success on second."""
    print("\n[Test 1] Pub/Sub publish: retry on DeadlineExceeded then succeed")
    print(
        "  Setup: mock _client.publish().return_value.result() — "
        "1st call raises DeadlineExceeded, 2nd returns message_id."
    )

    call_count = 0

    def mock_result():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            print("  Mock: future.result() attempt 1 -> DeadlineExceeded (will retry).")
            raise DeadlineExceeded("deadline")
        print("  Mock: future.result() attempt 2 -> success.")
        return "msg-123"

    mock_future = MagicMock()
    mock_future.result = mock_result
    mock_client = MagicMock()
    mock_client.publish.return_value = mock_future

    with patch.object(Publisher, "__init__", lambda self, topic=None: None):
        pub = Publisher()
        pub._client = mock_client
        pub._topic_path = "projects/p/topics/t"
        message_id = pub.publish({"key": "value"})

    assert call_count == 2, f"expected 2 result() calls, got {call_count}"
    assert message_id == "msg-123"
    print(f"  future.result() calls: {call_count}. message_id={message_id!r}. PASS.")


def main():
    print("=" * 60)
    print("Smoke test: Phase 3b — Pub/Sub Publisher retry")
    print("=" * 60)
    test_retry_on_transient_then_succeed()
    print("\n" + "=" * 60)
    print("All Phase 3b smoke tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
