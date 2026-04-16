"""Pub/Sub — lazy Publisher import to avoid loading google.cloud on lightweight imports."""

from __future__ import annotations

from typing import Any


__all__ = ["Publisher"]


def __getattr__(name: str) -> Any:
    if name == "Publisher":
        from src.services.pubsub.publisher import Publisher as _Publisher

        return _Publisher
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
