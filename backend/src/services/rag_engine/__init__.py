"""RAG engine integrations: ingestion chunkers, retrieval."""

from __future__ import annotations

from typing import Any


__all__ = ["retrieval"]


def __getattr__(name: str) -> Any:
    """Lazy-load retrieval so importing ingestion subpackages does not pull GCP deps."""
    if name == "retrieval":
        from src.services.rag_engine import retrieval as retrieval_module

        return retrieval_module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
