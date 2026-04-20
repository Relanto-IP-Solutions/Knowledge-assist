"""Smoke test for Phase 4a: CacheManager _upload_cache retry.

Run from repo root:
  uv run python scripts/tests_unit/smoke_retry_cache_manager.py
  or: PYTHONPATH=. python scripts/tests_unit/smoke_retry_cache_manager.py

Requires project dependencies (e.g. google-genai, google-api-core). Mocks genai
client caches.create — no Vertex AI required. Verifies: transient error on
caches.create triggers retry then success.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from google.api_core.exceptions import ServiceUnavailable

from src.services.agent.cache_manager import CacheManager


def test_retry_on_transient_then_succeed():
    """Simulate ServiceUnavailable on first caches.create, success on second."""
    print("\n[Test 1] CacheManager._upload_cache: retry on transient then succeed")
    print(
        "  Setup: mock client.caches.create — "
        "1st call raises ServiceUnavailable, 2nd returns cache name."
    )

    call_count = 0

    def mock_create(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            print("  Mock: caches.create attempt 1 -> ServiceUnavailable (will retry).")
            raise ServiceUnavailable("503")
        print("  Mock: caches.create attempt 2 -> success.")
        out = MagicMock()
        out.name = "projects/p/locations/us/cachedContents/smoke-cache-123"
        out.usage_metadata = MagicMock(total_token_count=100)
        return out

    mock_settings = MagicMock()
    mock_settings.llm.llm_model_name = "gemini-2.5-flash"
    mock_settings.ingestion.gcp_project_id = "test-project"

    with patch(
        "src.services.agent.cache_manager.get_settings", return_value=mock_settings
    ):
        manager = CacheManager()
        manager._client = MagicMock()
        manager._client.caches.create = mock_create

        name = manager._upload_cache("batch1", "You are a helpful assistant.")

    assert call_count == 2, f"expected 2 caches.create calls, got {call_count}"
    assert name == "projects/p/locations/us/cachedContents/smoke-cache-123"
    print(f"  caches.create calls: {call_count}. cache name={name!r}. PASS.")


def test_invalidate_by_cache_name():
    """Verify invalidate_by_cache_name removes stale cache entry."""
    print("\n[Test 2] CacheManager.invalidate_by_cache_name: removes expired cache")
    print("  Setup: populate _cache_names, call invalidate_by_cache_name.")

    mock_settings = MagicMock()
    mock_settings.ingestion.gcp_project_id = "test-project"
    mock_settings.llm.vertex_ai_location = "us-central1"

    with patch(
        "src.services.agent.cache_manager.get_settings", return_value=mock_settings
    ):
        manager = CacheManager()
        manager._cache_names = {
            "batch1": "projects/p/locations/us/cachedContents/111",
            "batch2": "projects/p/locations/us/cachedContents/222",
        }

        manager.invalidate_by_cache_name("projects/p/locations/us/cachedContents/111")

    assert "batch1" not in manager._cache_names
    assert (
        manager._cache_names.get("batch2")
        == "projects/p/locations/us/cachedContents/222"
    )
    print("  batch1 invalidated, batch2 intact. PASS.")

    # Idempotent: invalidating non-existent cache is a no-op
    manager.invalidate_by_cache_name("projects/p/locations/us/cachedContents/999")
    assert (
        manager._cache_names.get("batch2")
        == "projects/p/locations/us/cachedContents/222"
    )
    print("  Invalidating non-existent cache: no-op. PASS.")


def test_get_returns_none_when_cache_exceeds_refresh_threshold():
    """Verify get() returns None when cache age exceeds _REFRESH_THRESHOLD_SEC."""

    print(
        "\n[Test 3] CacheManager.get: returns None when cache exceeds refresh threshold"
    )
    from src.services.agent.cache_manager import _REFRESH_THRESHOLD_SEC

    mock_settings = MagicMock()
    mock_settings.llm.llm_model_name = "gemini-2.5-flash"
    mock_settings.ingestion.gcp_project_id = "test-project"
    mock_settings.llm.vertex_ai_location = "us-central1"

    with patch(
        "src.services.agent.cache_manager.get_settings", return_value=mock_settings
    ):
        manager = CacheManager()
        manager._cache_names["batch1"] = (
            "projects/p/locations/us/cachedContents/old-123"
        )
        # Set created_at so age = monotonic() - (monotonic() - threshold - 1) > threshold
        manager._cache_created_at["batch1"] = (
            time.monotonic() - _REFRESH_THRESHOLD_SEC - 1
        )

    result = manager.get("batch1")
    assert result is None, "Expected None when cache exceeds refresh threshold"
    assert "batch1" not in manager._cache_names, "Expected cache to be evicted"
    print(
        f"  get() returned None for cache older than {_REFRESH_THRESHOLD_SEC}s. PASS."
    )


def main():
    print("=" * 60)
    print("Smoke test: Phase 4a — CacheManager retry (_upload_cache)")
    print("=" * 60)
    test_retry_on_transient_then_succeed()
    test_invalidate_by_cache_name()
    test_get_returns_none_when_cache_exceeds_refresh_threshold()
    print("\n" + "=" * 60)
    print("All Phase 4a smoke tests passed.")
    print("=" * 60)


if __name__ == "__main__":
    main()
