"""Run worker batches and return candidate answers with evidence.

Reuses prompt_builder, batch_registry, field_loader, and LLM path;
outputs normalized CandidateAnswer list for the graph.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.services.agent.batch_registry import BatchDefinition, get_batches
from src.services.agent.cache_manager import get_cache_manager
from src.services.agent.confidence import compute_question_confidence
from src.services.agent.constants import BATCH_ID_TO_AGENT_ID
from src.services.agent.field_loader import load_batch_fields
from src.services.agent.prompt_builder import build_user_prompt, get_all_system_prompts
from src.services.agent.state import CandidateAnswer, CandidateSource
from src.services.agent.types import ChunksByQuestion, RetrievedChunk
from src.services.llm.client import get_llm_client
from src.utils.logger import get_logger


logger = get_logger(__name__)

_worker_runner: WorkerRunner | None = None


class WorkerRunner:
    """Run worker batches and return candidate answers with evidence."""

    def load_chunks_from_file(
        self, context_path: Path, q_ids: set[str]
    ) -> ChunksByQuestion:
        """Load mock RAG JSON file and convert to ChunksByQuestion."""
        raw: dict = json.loads(context_path.read_text(encoding="utf-8"))
        result: ChunksByQuestion = {}
        for q_id, chunk_list in raw.items():
            if q_id not in q_ids:
                continue
            result[q_id] = [
                RetrievedChunk(
                    text=c.get("text", ""),
                    source=c.get("source", "unknown"),
                    source_type=c.get("source_type", "unknown"),
                    similarity_score=float(c.get("similarity_score", 0.0)),
                    rerank_score=c.get("rerank_score"),
                    document_id=c.get("document_id"),
                    chunk_id=c.get("chunk_id"),
                )
                for c in chunk_list
            ]
        return result

    def render_context_text(self, batch_chunks: ChunksByQuestion) -> str:
        """Flatten ChunksByQuestion into formatted context string for the LLM."""
        pieces: list[str] = []
        for q_key, chunk_list in batch_chunks.items():
            pieces.extend(
                f"### [Source: {chunk.source} | Type: {chunk.source_type} | Question: {q_key}]\n{chunk.text}"
                for chunk in chunk_list
            )
        return "\n\n---\n\n".join(pieces)

    def _build_chunk_lookup(
        self, batch_chunks: ChunksByQuestion
    ) -> list[tuple[str, str, dict]]:
        """Build (source, text, metadata) list for chunk matching."""
        entries: list[tuple[str, str, dict]] = []
        for chunk_list in batch_chunks.values():
            for chunk in chunk_list:
                meta = {
                    "source_type": chunk.source_type,
                    "confidence_score": chunk.similarity_score,
                    "rerank_score": getattr(chunk, "rerank_score", None),
                    "chunk_id": chunk.chunk_id,
                    "source_file": chunk.document_id,
                }
                entries.append((chunk.source, chunk.text, meta))
        return entries

    def _find_chunk_meta(
        self,
        source: str,
        excerpt: str,
        chunk_lookup: list[tuple[str, str, dict]],
    ) -> dict:
        """Find chunk metadata for (source, excerpt)."""
        for src, text, meta in chunk_lookup:
            if src != source:
                continue
            if excerpt == text or excerpt in text or text in excerpt:
                return meta
        for src, _text, meta in chunk_lookup:
            if src == source:
                return meta
        return {}

    def _find_chunk_meta_excerpt_only(
        self,
        excerpt: str,
        chunk_lookup: list[tuple[str, str, dict]],
    ) -> dict:
        """When the model omits ``source``, match retrieval chunks by excerpt overlap."""
        ex = (excerpt or "").strip()
        if len(ex) < 12:
            return {}
        best: dict = {}
        best_overlap = 0
        for src, text, meta in chunk_lookup:
            if not text:
                continue
            if ex in text:
                overlap = min(len(ex), len(text))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best = {**meta, "_matched_source": src}
            elif text in ex and len(text) > best_overlap:
                best_overlap = len(text)
                best = {**meta, "_matched_source": src}
        if best.get("_matched_source"):
            best["source_display"] = best.pop("_matched_source")
        return best

    def _apply_retrieved_chunk_fallback(
        self,
        d: dict[str, Any],
        ch: RetrievedChunk,
    ) -> None:
        """When the model omits source/excerpt, attach the top retrieved chunk for display."""
        if not (d.get("chunk_id") or "").strip():
            d["chunk_id"] = ch.chunk_id or ""
        if not (d.get("source_file") or "").strip():
            d["source_file"] = ch.document_id or ""
        if not (d.get("source") or "").strip():
            if (ch.source or "").strip():
                d["source"] = Path(ch.source).name
            elif ch.document_id:
                d["source"] = Path(str(ch.document_id)).name
        if not (d.get("excerpt") or "").strip() and (ch.text or "").strip():
            t = ch.text.strip()
            d["excerpt"] = (t[:800] + "…") if len(t) > 800 else t
        if not d.get("source_type") or d.get("source_type") in ("unknown", "doc"):
            if (ch.source_type or "").strip() and ch.source_type != "unknown":
                d["source_type"] = ch.source_type
        if d.get("confidence_score") in (None, 0):
            d["confidence_score"] = ch.similarity_score
        if d.get("rerank_score") is None and ch.rerank_score is not None:
            d["rerank_score"] = ch.rerank_score

    def _enrich_conflict_details(
        self,
        details: list[Any],
        chunk_lookup: list[tuple[str, str, dict]],
        *,
        fallback_chunks: list[RetrievedChunk] | None = None,
    ) -> list[dict[str, Any]]:
        """Fill chunk_id / source_file / scores on conflict rows using retrieval metadata."""
        out: list[dict[str, Any]] = []
        fb = fallback_chunks or []
        top = fb[0] if fb else None
        for row in details:
            d: dict[str, Any] = (
                row if isinstance(row, dict) else row.model_dump()  # type: ignore[union-attr]
            )
            src = (d.get("source") or "").strip()
            ex = (d.get("excerpt") or "").strip()
            meta = self._find_chunk_meta(src, ex, chunk_lookup)
            if not meta.get("chunk_id"):
                meta_ex = self._find_chunk_meta_excerpt_only(ex, chunk_lookup)
                disp = meta_ex.pop("source_display", None)
                meta = {**meta, **meta_ex}
                meta.pop("source_display", None)
                if disp and not (d.get("source") or "").strip():
                    d["source"] = disp
            if meta.get("chunk_id") and not d.get("chunk_id"):
                d["chunk_id"] = meta["chunk_id"]
            if meta.get("source_file") and not d.get("source_file"):
                d["source_file"] = meta["source_file"]
            st = meta.get("source_type")
            if st and (
                not d.get("source_type") or d.get("source_type") in ("unknown", "doc")
            ):
                d["source_type"] = st
            if not (d.get("source") or "").strip() and meta.get("source_file"):
                d["source"] = Path(str(meta["source_file"])).name
            if (
                d.get("confidence_score") in (None, 0)
                and meta.get("confidence_score") is not None
            ):
                d["confidence_score"] = meta["confidence_score"]
            if d.get("rerank_score") is None and meta.get("rerank_score") is not None:
                d["rerank_score"] = meta["rerank_score"]
            if (
                top
                and not (d.get("chunk_id") or "").strip()
                and not (d.get("source_file") or "").strip()
            ):
                self._apply_retrieved_chunk_fallback(d, top)
            out.append(d)
        return out

    def partition_by_batch(
        self, chunks: ChunksByQuestion
    ) -> dict[int, ChunksByQuestion]:
        """Slice flat ChunksByQuestion into one subset per batch (keyed by batch_order)."""
        batches = get_batches()
        partitioned: dict[int, ChunksByQuestion] = {}
        for b in batches:
            q_ids = {f.q_id for f in load_batch_fields(b.batch_id)}
            partitioned[b.batch_order] = {k: v for k, v in chunks.items() if k in q_ids}
        return partitioned

    def _batch_def_for_id(self, batch_id: str) -> BatchDefinition | None:
        """Return BatchDefinition for batch_id, or None."""
        for b in get_batches():
            if b.batch_id == batch_id:
                return b
        return None

    def _result_to_candidates(
        self,
        batch_id: str,
        batch_chunks: ChunksByQuestion,
        batch_result: BaseModel,
    ) -> list[CandidateAnswer]:
        """Convert one batch LLM response to list of CandidateAnswer."""
        agent_id = BATCH_ID_TO_AGENT_ID.get(batch_id, batch_id)
        fields = load_batch_fields(batch_id)
        chunk_lookup = self._build_chunk_lookup(batch_chunks)
        data = batch_result.model_dump()
        candidates: list[CandidateAnswer] = []

        for field_def in fields:
            value = data.get(field_def.field_key)
            if value is None:
                candidates.append(
                    CandidateAnswer(
                        question_id=field_def.q_id,
                        agent_id=agent_id,
                        candidate_answer=None,
                        confidence=0.0,
                        sources=[],
                    )
                )
                continue

            has_conflict = value.get("conflict", False)
            answer_basis = value.get("answer_basis", [])
            enriched_sources: list[CandidateSource] = []
            seen: set[tuple[str, str]] = set()
            for ab in answer_basis:
                source = ab.get("source", "")
                excerpt = ab.get("excerpt") or ""
                key = (source, excerpt)
                if key in seen:
                    continue
                seen.add(key)
                meta = self._find_chunk_meta(source, excerpt, chunk_lookup)
                enriched_sources.append(
                    CandidateSource(
                        source=source,
                        chunk_id=meta.get("chunk_id"),
                        retrieval_score=meta.get("confidence_score") or 0.0,
                        rerank_score=meta.get("rerank_score"),
                        excerpt=excerpt or None,
                        source_type=meta.get("source_type") or ab.get("source_type"),
                        source_file=meta.get("source_file"),
                    )
                )
            confidence = compute_question_confidence(enriched_sources)

            entry: CandidateAnswer = {
                "question_id": field_def.q_id,
                "agent_id": agent_id,
                "candidate_answer": None if has_conflict else value.get("answer"),
                "confidence": confidence,
                "sources": enriched_sources,
            }
            if has_conflict:
                entry["conflict"] = True
                entry["conflict_reason"] = value.get("conflict_reason")
                q_chunks = batch_chunks.get(field_def.q_id) or []
                entry["conflict_details"] = self._enrich_conflict_details(
                    value.get("conflict_details", []),
                    chunk_lookup,
                    fallback_chunks=q_chunks,
                )
            else:
                entry["answer_basis"] = [
                    {
                        "source": s.get("source", ""),
                        "excerpt": s.get("excerpt"),
                        "source_type": s.get("source_type"),
                        "chunk_id": s.get("chunk_id"),
                        "confidence_score": s.get("retrieval_score"),
                        "rerank_score": s.get("rerank_score"),
                        "source_file": s.get("source_file"),
                    }
                    for s in enriched_sources
                ]
            candidates.append(entry)

        return candidates

    async def run_worker_batch(
        self,
        batch_id: str,
        batch_chunks: ChunksByQuestion,
        use_cache: bool = True,
        recall_context: dict[str, Any] | None = None,
    ) -> list[CandidateAnswer]:
        """Run one worker (batch) and return candidate answers with evidence."""
        batch_def = self._batch_def_for_id(batch_id)
        if not batch_def:
            logger.warning("Unknown batch_id={}; skipping worker", batch_id)
            return []

        system_prompts = get_all_system_prompts()
        cache_key = f"batch{batch_def.batch_order}"
        system_prompt = system_prompts.get(cache_key, "")
        context_text = self.render_context_text(batch_chunks)
        if recall_context:
            reason = recall_context.get("reason", "Re-evaluate")
            context_text = f"## Recall instruction\n{reason}\n\n---\n\n{context_text}"
        user_content = build_user_prompt(batch_id, context_text)
        schema_class = batch_def.schema_class

        cache_name: str | None = None
        if use_cache:
            cache_manager = get_cache_manager()
            await cache_manager.ensure_all(system_prompts)
            cache_name = cache_manager.get(cache_key)

        llm = get_llm_client()
        if cache_name:
            batch_result = await llm.generate_with_cache(
                user_prompt=user_content,
                cache_name=cache_name,
                schema=schema_class,
                system_prompt=system_prompt,
                response_schema=schema_class,
            )
        else:
            prompt_text = f"{system_prompt}\n\n{user_content}"
            batch_result = await llm.generate_async(
                prompt=prompt_text,
                schema=schema_class,
                response_schema=schema_class,
            )

        return self._result_to_candidates(batch_id, batch_chunks, batch_result)

    async def run_all_workers(
        self,
        partitioned: dict[int, ChunksByQuestion],
        use_cache: bool = True,
        recall_context: dict[str, Any] | None = None,
        *,
        skip_empty_batches: bool = False,
    ) -> list[CandidateAnswer]:
        """Run all workers in parallel and return combined candidate answers.

        When ``skip_empty_batches`` is True, batches with no retrieval chunks are
        not sent to the LLM (for smoke tests and cost-saving local runs).
        """
        batches = get_batches()
        tasks: list[Any] = []
        batch_ids_run: list[str] = []
        for b in batches:
            batch_chunks = partitioned.get(b.batch_order, {})
            if skip_empty_batches and not batch_chunks:
                continue
            batch_ids_run.append(b.batch_id)
            tasks.append(
                self.run_worker_batch(
                    b.batch_id,
                    batch_chunks,
                    use_cache=use_cache,
                    recall_context=recall_context,
                )
            )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: list[CandidateAnswer] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                batch_id = batch_ids_run[i] if i < len(batch_ids_run) else "unknown"
                logger.opt(exception=True).warning(
                    "Worker batch {} failed: {}",
                    batch_id,
                    result,
                )
            else:
                out.extend(result)
        return out


def get_worker_runner() -> WorkerRunner:
    """Return the singleton WorkerRunner instance."""
    global _worker_runner
    if _worker_runner is None:
        _worker_runner = WorkerRunner()
    return _worker_runner


def load_chunks_from_file(context_path: Path, q_ids: set[str]) -> ChunksByQuestion:
    """Load mock RAG JSON file and convert to ChunksByQuestion."""
    return get_worker_runner().load_chunks_from_file(context_path, q_ids)


def render_context_text(batch_chunks: ChunksByQuestion) -> str:
    """Flatten ChunksByQuestion into formatted context string for the LLM."""
    return get_worker_runner().render_context_text(batch_chunks)


def partition_by_batch(chunks: ChunksByQuestion) -> dict[int, ChunksByQuestion]:
    """Slice flat ChunksByQuestion into one subset per batch (keyed by batch_order)."""
    return get_worker_runner().partition_by_batch(chunks)


async def run_worker_batch(
    batch_id: str,
    batch_chunks: ChunksByQuestion,
    use_cache: bool = True,
    recall_context: dict[str, Any] | None = None,
) -> list[CandidateAnswer]:
    """Run one worker (batch) and return candidate answers with evidence."""
    return await get_worker_runner().run_worker_batch(
        batch_id, batch_chunks, use_cache=use_cache, recall_context=recall_context
    )


async def run_all_workers(
    partitioned: dict[int, ChunksByQuestion],
    use_cache: bool = True,
    recall_context: dict[str, Any] | None = None,
    *,
    skip_empty_batches: bool = False,
) -> list[CandidateAnswer]:
    """Run all workers in parallel and return combined candidate answers."""
    return await get_worker_runner().run_all_workers(
        partitioned,
        use_cache=use_cache,
        recall_context=recall_context,
        skip_empty_batches=skip_empty_batches,
    )
