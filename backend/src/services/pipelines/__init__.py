"""Pipelines package — lazy exports to avoid importing heavy deps on submodule import."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any


__all__ = [
    "AnswerGenerationPipeline",
    "GcsPipeline",
    "IngestionPipeline",
    "PubsubPipeline",
    "RagPipeline",
]

_LAZY = {
    "AnswerGenerationPipeline": ("agent_pipeline", "AnswerGenerationPipeline"),
    "GcsPipeline": ("gcs_pipeline", "GcsPipeline"),
    "IngestionPipeline": ("ingestion_pipeline", "IngestionPipeline"),
    "PubsubPipeline": ("pubsub_pipeline", "PubsubPipeline"),
    "RagPipeline": ("rag_pipeline", "RagPipeline"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        mod_name, attr = _LAZY[name]
        mod = __import__(f"src.services.pipelines.{mod_name}", fromlist=[attr])
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:
    from src.services.pipelines.agent_pipeline import AnswerGenerationPipeline
    from src.services.pipelines.gcs_pipeline import GcsPipeline
    from src.services.pipelines.ingestion_pipeline import IngestionPipeline
    from src.services.pipelines.pubsub_pipeline import PubsubPipeline
    from src.services.pipelines.rag_pipeline import RagPipeline
