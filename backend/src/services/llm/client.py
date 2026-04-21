"""Generic Vertex AI / Gemini LLM client.

This module is intentionally domain-agnostic — it knows nothing about Slack,
opportunity requirements, or any other product. Callers supply a Pydantic model as the output
schema and receive a validated instance back.

Usage
-----
Sync (simple callers):

    from src.services.llm import LLMClient
    result: MySchema = LLMClient().generate(prompt, MySchema)

Async (parallel batch callers):

    result = await LLMClient().generate_async(prompt, MySchema)

Async with Vertex AI context cache:

    result = await LLMClient().generate_with_cache(user_prompt, cache_name, MySchema)
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import TypeVar

import vertexai  # type: ignore[import-untyped]
from google import genai  # type: ignore[import-untyped]
from google.genai.errors import ClientError  # type: ignore[import-untyped]
from google.genai.types import (  # type: ignore[import-untyped]
    GenerateContentConfig,
    HttpOptions,
    Part,
)
from google.oauth2 import service_account  # type: ignore[import-untyped]
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)
from vertexai.generative_models import (  # type: ignore[import-untyped]
    GenerationConfig,
    GenerativeModel,
)

from configs.settings import get_settings
from src.utils.logger import get_logger


logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

_MAX_RETRIES = 2
_MAX_429_RETRIES = 5
_429_WAIT_MIN = 4
_429_WAIT_MAX = 60


def _is_rate_limit_error(exc: BaseException) -> bool:
    """True if the exception is a 429 / RESOURCE_EXHAUSTED rate limit error."""
    if isinstance(exc, ClientError):
        return getattr(exc, "code", None) == 429
    msg = str(exc).upper()
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg


def _is_cache_not_found(exc: BaseException) -> bool:
    """True if Vertex AI returned 404 for a CachedContent resource (expired/deleted)."""
    if not isinstance(exc, ClientError):
        return False
    code = getattr(exc, "code", None)
    msg = str(exc).lower()
    return code == 404 and ("cached content" in msg or "not found" in msg)


def _before_sleep_429(retry_state) -> None:
    """Log before sleeping on 429 retry."""
    next_action = getattr(retry_state, "next_action", None)
    sleep_sec = getattr(next_action, "sleep", 0) if next_action else 0
    logger.warning(
        "Vertex AI 429 rate limit (attempt {}/{}), retrying in {:.0f}s",
        retry_state.attempt_number,
        _MAX_429_RETRIES,
        sleep_sec,
    )


_retry_on_429 = retry(
    retry=retry_if_exception(_is_rate_limit_error),
    stop=stop_after_attempt(_MAX_429_RETRIES),
    wait=wait_exponential(multiplier=2, min=_429_WAIT_MIN, max=_429_WAIT_MAX),
    reraise=True,
    before_sleep=_before_sleep_429,
)

# Vertex AI (vertexai SDK) is initialised once per process.
_vertex_initialised: bool = False

_llm_client: LLMClient | None = None
_llm_client_lock = threading.Lock()


def get_llm_client() -> LLMClient:
    """Return the singleton LLMClient instance (lazy init)."""
    global _llm_client
    with _llm_client_lock:
        if _llm_client is None:
            _llm_client = LLMClient()
        return _llm_client


# ---------------------------------------------------------------------------
# Shared credential helper
# ---------------------------------------------------------------------------


def _build_sa_credentials() -> service_account.Credentials | None:
    """Load the service-account credentials from the path in settings.

    Reads ``settings.ingestion.google_application_credentials``, which is
    populated from ``GOOGLE_APPLICATION_CREDENTIALS`` in
    ``configs/secrets/.env`` by pydantic-settings.

    Returns:
        ``google.oauth2.service_account.Credentials`` if a key file path is
        configured, ``None`` otherwise (falls back to ADC).
    """
    settings = get_settings()
    key_path = (settings.ingestion.google_application_credentials or "").strip()
    if not key_path:
        return None
    resolved = Path(key_path).expanduser().resolve()
    return service_account.Credentials.from_service_account_file(
        str(resolved),
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )


def _ensure_vertex_init() -> None:
    global _vertex_initialised
    if _vertex_initialised:
        return

    settings = get_settings()
    vertexai.init(
        project=settings.ingestion.gcp_project_id,
        location=settings.llm.vertex_ai_location,
        credentials=_build_sa_credentials(),
    )
    _vertex_initialised = True
    logger.info(
        "Vertex AI initialised (project=%s, location=%s, model=%s)",
        settings.ingestion.gcp_project_id,
        settings.llm.vertex_ai_location,
        settings.llm.llm_model_name,
    )


class LLMError(RuntimeError):
    """Raised when the LLM call fails or the response cannot be validated."""


class LLMClient:
    """Thin, reusable wrapper around Vertex AI GenerativeModel.

    All domain-specific prompt construction and schema definitions live in
    the calling service (e.g. slack_prompts.py, src.services.agent.prompt_builder).
    This class only handles the transport layer: sending the prompt,
    enforcing structured JSON output, and validating the response against
    the caller's schema.

    Three calling patterns are supported:

    1. ``generate()``              — synchronous, no constrained decoding.
    2. ``generate_async()``        — async, uses google-genai for all JSON calls.
    3. ``generate_with_cache()``   — async, uses a Vertex AI CachedContent
                                     resource so the system prompt is not
                                     re-tokenised on every call.
    """

    def __init__(self) -> None:
        self._genai_client: genai.Client | None = None

    # ------------------------------------------------------------------
    # Synchronous path — kept for non-async callers (e.g. Slack service)
    # ------------------------------------------------------------------

    def generate(self, prompt: str, schema: type[T]) -> T:
        """Call Gemini with structured JSON output and return a validated instance.

        Args:
            prompt:  Full prompt text (system + user turns concatenated).
            schema:  Pydantic BaseModel subclass defining the expected shape.

        Returns:
            A validated instance of ``schema``.

        Raises:
            LLMError: If the Vertex AI call fails or the response fails validation.
        """
        _ensure_vertex_init()
        settings = get_settings()

        try:
            model = GenerativeModel(settings.llm.llm_model_name)
            response = model.generate_content(
                prompt,
                generation_config=GenerationConfig(
                    response_mime_type="application/json",
                ),
            )
        except Exception as exc:
            raise LLMError(f"Vertex AI call failed: {exc}") from exc

        try:
            return schema.model_validate_json(response.text)
        except ValidationError as exc:
            raise LLMError(
                f"LLM response did not match schema {schema.__name__}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Multimodal path — document/image extraction (PDF, images)
    # ------------------------------------------------------------------

    def generate_content_from_media(
        self,
        file_bytes: bytes,
        mime_type: str,
        prompt: str,
        *,
        model_name: str | None = None,
        max_output_tokens: int = 8192,
    ) -> str:
        """Call Gemini with binary content (PDF, image) and return raw text.

        Uses google-genai Part.from_bytes for multimodal input. No schema — returns plain text.
        Applies same 429 retry as other methods. Requests go to Vertex AI on GCP.

        Args:
            file_bytes:       Raw file content (PDF or image bytes).
            mime_type:        MIME type (e.g. application/pdf, image/jpeg).
            prompt:           Instruction prompt for the model.
            model_name:      Override model; defaults to settings.llm.llm_model_name.
            max_output_tokens: Max tokens in response (default 8192).

        Returns:
            Extracted/transcribed text as a string.

        Raises:
            LLMError: If the Vertex AI call fails.
        """
        self._ensure_genai_client()
        assert self._genai_client is not None
        settings = get_settings()
        model = model_name or settings.llm.llm_model_name

        def _do_call() -> str:
            part = Part.from_bytes(data=file_bytes, mime_type=mime_type)
            response = self._genai_client.models.generate_content(
                model=model,
                contents=[part, prompt],
                config=GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=max_output_tokens,
                ),
            )
            return response.text

        try:
            return _retry_on_429(_do_call)()
        except Exception as exc:
            raise LLMError(f"Vertex AI media extraction failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Async path — used by parallel batch callers
    # ------------------------------------------------------------------

    async def generate_async(
        self,
        prompt: str,
        schema: type[T],
        *,
        response_schema: type[BaseModel] | None = None,
        max_retries: int = _MAX_RETRIES,
    ) -> T:
        """Async call via google-genai for use in ``asyncio.gather`` calls.

        Args:
            prompt:          Full prompt string (system + user concatenated).
            schema:          Pydantic model used to validate the response text.
            response_schema: Passed to Vertex AI for constrained decoding.
                             Viable now that each batch has ≤16 fields — the
                             old 27-field schemas exceeded Vertex AI's automaton
                             limit.  Falls back gracefully: if Vertex AI rejects
                             the schema with a 400, Pydantic still validates the
                             raw JSON response post-hoc.
            max_retries:     Number of retry attempts on transient errors.

        Returns:
            A validated instance of ``schema``.

        Raises:
            LLMError: After exhausting retries.
        """
        self._ensure_genai_client()

        for attempt in range(1, max_retries + 1):
            try:
                schema_for_decode = (
                    response_schema if response_schema is not None else schema
                )
                raw = await asyncio.get_running_loop().run_in_executor(
                    None, self._sync_generate, prompt, schema_for_decode
                )
                return schema.model_validate_json(raw)
            except LLMError:
                raise
            except Exception as exc:
                logger.warning(
                    "generate_async: attempt %d/%d failed: %s",
                    attempt,
                    max_retries,
                    exc,
                    exc_info=True,
                )
                if attempt == max_retries:
                    raise LLMError(
                        f"Vertex AI call failed after {max_retries} attempts: {exc}"
                    ) from exc
                await asyncio.sleep(1)

        raise LLMError("generate_async: unreachable")  # for type checkers

    def _sync_generate(
        self,
        prompt: str,
        schema: type[BaseModel] | None = None,
    ) -> str:
        """Synchronous call via google-genai — runs in an executor to stay non-blocking.

        When ``schema`` is supplied it is first attempted with Vertex AI
        constrained decoding (``response_schema``).  If Vertex AI rejects the
        schema with a ``400 INVALID_ARGUMENT: too many states`` error — which
        occurs when the compiled automaton exceeds the service's complexity
        limit — the call is transparently retried without ``response_schema``,
        relying on the system-prompt description and post-hoc Pydantic
        validation instead.

        Returns:
            Raw JSON string from the model (not yet validated).
        """
        assert self._genai_client is not None
        settings = get_settings()

        def _do_call(use_schema: bool) -> str:
            response = self._genai_client.models.generate_content(
                model=settings.llm.llm_model_name,
                contents=prompt,
                config=GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema if use_schema else None,
                    temperature=0.0,
                ),
            )
            return response.text

        def _call(use_schema: bool) -> str:
            return _retry_on_429(lambda: _do_call(use_schema))()

        if schema is None:
            return _call(use_schema=False)

        try:
            return _call(use_schema=True)
        except Exception as exc:
            if (
                "too many states" in str(exc).lower()
                or "invalid_argument" in str(exc).lower()
            ):
                logger.warning(
                    "_sync_generate: schema {} rejected by Vertex AI ({}); "
                    "retrying without constrained decoding",
                    schema.__name__,
                    exc,
                )
                return _call(use_schema=False)
            raise

    # ------------------------------------------------------------------
    # Context-cache path — system prompt lives in a Vertex CachedContent
    # ------------------------------------------------------------------

    def _ensure_genai_client(self) -> None:
        """Lazily initialise the google-genai client.

        Service-account credentials are loaded via ``_build_sa_credentials()``
        so the client uses the key file from ``configs/secrets/.env`` rather
        than falling back to ADC user credentials, which may lack Vertex AI
        permissions.
        """
        if self._genai_client is not None:
            return

        settings = get_settings()
        self._genai_client = genai.Client(
            vertexai=True,
            project=settings.ingestion.gcp_project_id,
            location=settings.llm.vertex_ai_location,
            credentials=_build_sa_credentials(),
            http_options=HttpOptions(api_version="v1"),
        )

    async def generate_with_cache(
        self,
        user_prompt: str,
        cache_name: str,
        schema: type[T],
        *,
        system_prompt: str | None = None,
        response_schema: type[BaseModel] | None = None,
        max_retries: int = _MAX_RETRIES,
    ) -> T:
        """Generate a response using a Vertex AI CachedContent resource.

        The system prompt is NOT re-sent — it lives inside the cache identified
        by ``cache_name``.  Only ``user_prompt`` (context documents + extraction
        instruction) travels as new tokens, cutting input-token costs significantly.

        Falls back to ``generate_async()`` on any error so a stale or expired
        cache does not block the pipeline. When falling back, passes
        ``system_prompt + user_prompt`` if ``system_prompt`` is provided.

        Args:
            user_prompt:     The user-turn content (context + extraction request).
            cache_name:      Vertex AI resource name, e.g.
                             ``"projects/.../locations/.../cachedContents/123"``.
            schema:          Pydantic model used to validate the response text.
            system_prompt:   Optional; used for fallback when cache fails.
            response_schema: Unused — kept for call-site compatibility.
            max_retries:     Number of retry attempts before falling back.

        Returns:
            A validated instance of ``schema``.
        """
        self._ensure_genai_client()

        for attempt in range(1, max_retries + 1):
            try:
                raw = await asyncio.get_running_loop().run_in_executor(
                    None, self._sync_generate_with_cache, user_prompt, cache_name
                )
                return schema.model_validate_json(raw)
            except LLMError:
                raise
            except Exception as exc:
                if _is_cache_not_found(exc):
                    from src.services.agent.cache_manager import get_cache_manager

                    get_cache_manager().invalidate_by_cache_name(cache_name)
                    logger.info(
                        "generate_with_cache: cache expired (404), invalidated; "
                        "falling back to full-prompt path",
                    )
                    full_prompt = (
                        f"{system_prompt}\n\n{user_prompt}"
                        if system_prompt
                        else user_prompt
                    )
                    return await self.generate_async(full_prompt, schema)
                logger.opt(exception=True).warning(
                    "generate_with_cache: attempt {}/{} failed (cache={}): {}",
                    attempt,
                    max_retries,
                    cache_name,
                    exc,
                )
                if attempt == max_retries:
                    logger.opt(exception=True).warning(
                        "generate_with_cache: exhausted retries for cache={}; "
                        "falling back to full-prompt path",
                        cache_name,
                    )
                    full_prompt = (
                        f"{system_prompt}\n\n{user_prompt}"
                        if system_prompt
                        else user_prompt
                    )
                    return await self.generate_async(full_prompt, schema)
                await asyncio.sleep(1)

        raise LLMError("generate_with_cache: unreachable")  # for type checkers

    def _sync_generate_with_cache(
        self,
        user_prompt: str,
        cache_name: str,
    ) -> str:
        """Synchronous cached generate_content call — runs in an executor.

        Returns:
            Raw JSON string from the model (not yet validated).
        """
        assert self._genai_client is not None
        settings = get_settings()

        def _do_call() -> str:
            response = self._genai_client.models.generate_content(
                model=settings.llm.llm_model_name,
                contents=user_prompt,
                config=GenerateContentConfig(
                    cached_content=cache_name,
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            return response.text

        return _retry_on_429(_do_call)()
