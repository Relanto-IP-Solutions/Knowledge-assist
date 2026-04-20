"""Vertex AI context-cache manager for system prompts.

Each of the 6 batch system prompts is uploaded once per process run and stored
server-side as a CachedContent resource.  Subsequent LLM calls reference the
cache by name instead of re-sending all the system-prompt tokens, cutting
input-token costs significantly.

Caching API:  google-genai  (``from google import genai``)
TTL default:  21600 s (6 hours) — refresh by calling ``ensure_all()`` again.

Restrictions imposed by Vertex AI when a cache is active:
  - Do NOT pass system_instructions to GenerativeModel — they are baked into the cache.
  - Do NOT pass tools / tool_config.
"""

from __future__ import annotations

import asyncio
import threading
import time

from google import genai  # type: ignore[import-untyped]
from google.genai.types import (  # type: ignore[import-untyped]
    CreateCachedContentConfig,
    HttpOptions,
)

from configs.settings import get_settings
from src.services.llm.client import _build_sa_credentials
from src.utils.logger import get_logger
from src.utils.retry import retry_on_transient


logger = get_logger(__name__)

_DEFAULT_TTL = "21600s"
_REFRESH_THRESHOLD_SEC = 5 * 3600  # Refresh cache ~1h before 6h TTL expires

_cache_manager: CacheManager | None = None
_cache_manager_lock = threading.Lock()


def get_cache_manager() -> CacheManager:
    """Return the singleton CacheManager instance (lazy init)."""
    global _cache_manager
    with _cache_manager_lock:
        if _cache_manager is None:
            _cache_manager = CacheManager()
        return _cache_manager


class CacheManager:
    """Creates and stores Vertex AI CachedContent resources for each batch system prompt.

    Usage
    -----
    At application startup (before any LLM calls)::

        manager = CacheManager()
        await manager.ensure_all(system_prompts)  # dict[batch_key, prompt_str]

    Then pass the cache name to ``LLMClient.generate_with_cache``::

        cache_name = manager.get("batch1")  # "projects/.../cachedContents/..."

    If ``get()`` returns ``None`` (cache unavailable or expired), the caller
    should fall back to the full-prompt path via ``LLMClient.generate_async``.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: genai.Client | None = None
        self._cache_names: dict[str, str] = {}
        self._cache_created_at: dict[str, float] = {}
        self._ready: bool = False
        self._ensure_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _ensure_client(self) -> None:
        """Lazily create the google-genai client pointed at Vertex AI."""
        if self._client is not None:
            return

        project = self._settings.ingestion.gcp_project_id
        location = self._settings.llm.vertex_ai_location

        if not project:
            raise RuntimeError(
                "Vertex AI project ID is not configured. "
                "Set GCP_PROJECT_ID in configs/.env."
            )

        self._client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            credentials=_build_sa_credentials(),
            http_options=HttpOptions(api_version="v1"),
        )
        logger.info(
            "CacheManager: google-genai client initialised (project=%s, location=%s)",
            project,
            location,
        )

    # ------------------------------------------------------------------
    # Cache creation
    # ------------------------------------------------------------------

    @retry_on_transient()
    def _upload_cache(self, batch_key: str, system_prompt: str) -> str:
        """Upload ``system_prompt`` to Vertex AI and return the resource name.

        Retries on Vertex AI / GCP transient errors (e.g. ServiceUnavailable, ResourceExhausted).
        Synchronous — intended to be called via ``run_in_executor`` from async code.
        """
        assert self._client is not None
        settings = get_settings()

        logger.info("CacheManager: uploading cache for batch_key={}", batch_key)
        cached_content = self._client.caches.create(
            model=settings.llm.llm_model_name,
            config=CreateCachedContentConfig(
                system_instruction=system_prompt,
                ttl=_DEFAULT_TTL,
                display_name=f"pzf-opp-{batch_key}",
            ),
        )
        name: str = cached_content.name
        logger.info(
            "CacheManager: cache ready for batch_key=%s -> %s (tokens=%s)",
            batch_key,
            name,
            getattr(cached_content.usage_metadata, "total_token_count", "?"),
        )
        return name

    async def _upload_cache_async(
        self, batch_key: str, system_prompt: str
    ) -> tuple[str, str]:
        """Async wrapper around ``_upload_cache``; returns (batch_key, cache_name)."""
        name = await asyncio.get_running_loop().run_in_executor(
            None, self._upload_cache, batch_key, system_prompt
        )
        return batch_key, name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ensure_all(self, system_prompts: dict[str, str]) -> None:
        """Create Vertex AI caches concurrently for all entries in ``system_prompts``.

        ``system_prompts`` maps a short batch key (e.g. ``"batch1"``) to a
        fully-rendered system prompt string.  Already-cached batches are
        skipped (idempotent within a process run).  Failed uploads are logged
        and skipped — ``get()`` will return ``None`` for that batch and the
        caller falls back to the full-prompt path automatically.

        Args:
            system_prompts: ``{batch_key: system_prompt_string}`` for all batches.
        """
        self._ensure_client()

        async with self._ensure_lock:
            pending = {
                key: prompt
                for key, prompt in system_prompts.items()
                if key not in self._cache_names
            }

            if not pending:
                logger.info("CacheManager: all caches already present")
                return

            logger.info(
                "CacheManager: uploading %d cache(s) concurrently", len(pending)
            )
            tasks = [self._upload_cache_async(k, p) for k, p in pending.items()]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    logger.warning(
                        "CacheManager: cache upload failed (will use full-prompt fallback): %s",
                        result,
                    )
                else:
                    key, name = result
                    self._cache_names[key] = name
                    self._cache_created_at[key] = time.monotonic()

            self._ready = True
            logger.info(
                "CacheManager: ready — %d/%d caches available",
                len(self._cache_names),
                len(system_prompts),
            )

    def get(self, batch_key: str) -> str | None:
        """Return the CachedContent resource name for ``batch_key``, or ``None``.

        ``None`` means no cache is available — the caller must fall back to
        sending the full system prompt via ``LLMClient.generate_async``.

        Caches older than ``_REFRESH_THRESHOLD_SEC`` (5 hours) are treated as
        expired and removed so the next ``ensure_all()`` re-creates them.
        """
        if batch_key not in self._cache_names:
            return None
        if batch_key in self._cache_created_at:
            age = time.monotonic() - self._cache_created_at[batch_key]
            if age > _REFRESH_THRESHOLD_SEC:
                del self._cache_names[batch_key]
                del self._cache_created_at[batch_key]
                logger.info(
                    "CacheManager: cache for batch_key=%s exceeded refresh threshold (age=%.0fs); "
                    "will re-create on next ensure_all",
                    batch_key,
                    age,
                )
                return None
        return self._cache_names[batch_key]

    def invalidate_by_cache_name(self, cache_name: str) -> None:
        """Remove a cache entry by its resource name (e.g. after 404 NOT_FOUND).

        Call when Vertex AI returns 404 for a cached content — prevents
        subsequent requests from repeatedly hitting the expired cache.
        """
        for key, name in list(self._cache_names.items()):
            if name == cache_name:
                del self._cache_names[key]
                self._cache_created_at.pop(key, None)
                logger.info(
                    "CacheManager: invalidated stale cache for batch_key=%s (was 404)",
                    key,
                )
                return

    @property
    def is_ready(self) -> bool:
        """True if ``ensure_all`` has completed at least once."""
        return self._ready
