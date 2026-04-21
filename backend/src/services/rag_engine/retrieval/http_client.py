"""Shared HTTP session for connection reuse across retrieval API calls."""

from __future__ import annotations

import threading

import requests

from src.utils.logger import get_logger


logger = get_logger(__name__)

_session: requests.Session | None = None
_session_lock = threading.Lock()


def get_http_session() -> requests.Session:
    """Return a shared Session for connection reuse. Thread-safe for concurrent post() calls."""
    global _session
    if _session is not None:
        return _session
    with _session_lock:
        if _session is None:
            logger.info(
                "Creating shared HTTP session for connection reuse (pool_connections=10, pool_maxsize=10)"
            )
            _session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=10,
                pool_maxsize=10,
                max_retries=0,  # tenacity handles retries
            )
            _session.mount("https://", adapter)
    return _session
