"""Shared retry decorator for transient HTTP and GCP API errors.

Use tenacity with exponential backoff. Apply to client methods that perform
network I/O (e.g. requests.post, blob.download_as_bytes, publisher.publish).

Example:
    from src.utils.retry import retry_on_transient

    @retry_on_transient()
    def my_http_call():
        response = requests.post(...)
        response.raise_for_status()
        return response.json()
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import tenacity
from tenacity import (
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.utils.logger import get_logger


logger = get_logger(__name__)

# HTTP status codes we retry on (transient)
_RETRYABLE_HTTP_STATUS = (429, 502, 503)


# GCP transient exceptions (import lazily to avoid loading google.api_core at module import)
def _is_retryable_gcp(exc: BaseException) -> bool:
    """Return True if the exception is a known transient GCP/API error."""
    try:
        from google.api_core import exceptions as api_core_exceptions
    except ImportError:
        return False
    transient = (
        getattr(api_core_exceptions, "ServiceUnavailable", None),
        getattr(api_core_exceptions, "ResourceExhausted", None),
        getattr(api_core_exceptions, "DeadlineExceeded", None),
        getattr(api_core_exceptions, "InternalServerError", None),
        getattr(api_core_exceptions, "Unavailable", None),
    )
    return any(c is not None and isinstance(exc, c) for c in transient)


def _is_retryable(exc: BaseException) -> bool:
    """Return True if the exception is transient and worth retrying."""
    # Do not retry on NotFound (GCS, etc.) — treat as non-transient
    try:
        from google.cloud.exceptions import NotFound

        if isinstance(exc, NotFound):
            return False
    except ImportError:
        pass
    # requests: timeout, connection, and retryable HTTP status
    if exc.__class__.__module__.startswith("requests."):
        if type(exc).__name__ in (
            "Timeout",
            "ConnectionError",
            "ConnectTimeout",
            "ReadTimeout",
        ):
            return True
        if (
            type(exc).__name__ == "HTTPError"
            and getattr(exc, "response", None) is not None
        ):
            status = getattr(exc.response, "status_code", None)
            return status in _RETRYABLE_HTTP_STATUS
        # Generic RequestException: retry only if we can detect 429/502/503
        if type(exc).__name__ == "HTTPError":
            response = getattr(exc, "response", None)
            if response is not None:
                return getattr(response, "status_code", None) in _RETRYABLE_HTTP_STATUS
    # GCP api_core
    if "google.api_core" in type(exc).__module__:
        return _is_retryable_gcp(exc)
    return False


F = TypeVar("F", bound=Callable)


def retry_on_transient(
    max_attempts: int = 3,
    min_wait_seconds: float = 2,
    max_wait_seconds: float = 30,
    multiplier: float = 1,
) -> Callable[[F], F]:
    """Decorator that retries on transient GCP/HTTP errors with exponential backoff.

    Retries on: 429, 502, 503, Timeout, ConnectionError, RESOURCE_EXHAUSTED,
    ServiceUnavailable, DeadlineExceeded, and similar transient errors.
    Does not retry on: other 4xx (except 429), NotFound, validation errors.

    Args:
        max_attempts: Total number of attempts (default 3).
        min_wait_seconds: Minimum wait between retries (default 2).
        max_wait_seconds: Maximum wait between retries (default 30).
        multiplier: Exponential multiplier for wait (default 1).

    Returns:
        Decorated callable; on failure after all retries, raises the last exception.
    """

    def before_sleep(retry_state: tenacity.RetryCallState) -> None:
        attempt = retry_state.attempt_number
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        logger.bind(opportunity_id="N/A").warning(
            "Retry %s/%s after transient error: %s",
            attempt,
            max_attempts,
            exc,
        )

    r = tenacity.retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(
            multiplier=multiplier, min=min_wait_seconds, max=max_wait_seconds
        ),
        before_sleep=before_sleep,
        reraise=True,
    )
    return r
