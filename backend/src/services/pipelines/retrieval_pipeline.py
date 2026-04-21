"""Retrieval pipeline: opportunity questions → embed → Vector Search → rerank → answer items."""

from __future__ import annotations

from configs.settings import get_settings
from src.services.rag_engine.retrieval import (
    build_answer_items,
    embed_question,
    filter_candidates_by_similarity,
    get_access_token,
    load_questions_for_retrieval,
    retrieve_topk_from_combined_source,
    vertex_rank,
)
from src.utils.logger import get_logger


logger = get_logger(__name__)


class RetrievalPipeline:
    """Orchestrates retrieval for one opportunity: all opportunity questions → Vector Search → rerank."""

    def process_one_opportunity(
        self, opportunity_id: str, questions_override: dict[str, str] | None = None
    ) -> dict:
        """Run retrieval for all opportunity questions; return {opportunity_id, retrievals}.

        Args:
            opportunity_id: Opportunity ID for scoping.
            questions_override: If set, use this dict instead of loading from DB (for smoke tests).
        """
        logger.bind(opportunity_id=opportunity_id).info(
            "Retrieval pipeline starting for opportunity_id=%s",
            opportunity_id,
        )
        settings = get_settings().retrieval
        token = get_access_token()
        questions = (
            questions_override
            if questions_override is not None
            else load_questions_for_retrieval()
        )
        k_per_source = settings.k_per_source
        k_final = settings.k_final
        logger.bind(opportunity_id=opportunity_id).debug(
            "Loaded %d questions, k_per_source=%s, k_final=%s",
            len(questions),
            k_per_source,
            k_final,
        )

        retrievals: dict[str, list] = {}
        cached_count = 0
        live_count = 0
        for qid, question in questions.items():
            # Support both legacy overrides (dict[qid -> str]) and new loader shape
            # (dict[qid -> {"text": str, "embedding": list[float] | None}]).
            if isinstance(question, dict):
                q = (question.get("text") or "").strip()
                cached_embedding = question.get("embedding")
            else:
                q = (question or "").strip()
                cached_embedding = None
            if not q:
                logger.bind(opportunity_id=opportunity_id).debug(
                    "Skipping empty question qid=%s",
                    qid,
                )
                retrievals[qid] = []
                continue

            # Prefer cached embedding when available; fall back to live embedding.
            if isinstance(cached_embedding, list) and cached_embedding:
                logger.bind(opportunity_id=opportunity_id).debug(
                    "qid=%s: using cached question_embedding (len=%d)",
                    qid,
                    len(cached_embedding),
                )
                embedding = cached_embedding
                cached_count += 1
            else:
                logger.bind(opportunity_id=opportunity_id).debug(
                    "qid=%s: embedding via Vertex API (no valid cache)",
                    qid,
                )
                embedding = embed_question(q)
                live_count += 1
            all_candidates = retrieve_topk_from_combined_source(
                embedding, opportunity_id, token, k_per_source
            )
            logger.bind(opportunity_id=opportunity_id).debug(
                "qid=%s: %d candidates from parallel retrieval",
                qid,
                len(all_candidates),
            )

            min_similarity = settings.similarity_min_threshold
            candidates_for_rerank = filter_candidates_by_similarity(
                all_candidates, min_similarity
            )
            if len(candidates_for_rerank) < len(all_candidates):
                logger.bind(opportunity_id=opportunity_id).debug(
                    "qid=%s: filtered to %d candidates above similarity threshold %.2f",
                    qid,
                    len(candidates_for_rerank),
                    min_similarity,
                )
            if not candidates_for_rerank:
                logger.bind(opportunity_id=opportunity_id).debug(
                    "qid=%s: no candidates after similarity filter, skipping rerank",
                    qid,
                )
                topk = []
            else:
                topk = vertex_rank(q, candidates_for_rerank, token, k_final)
            retrievals[qid] = build_answer_items(topk)
            logger.bind(opportunity_id=opportunity_id).debug(
                "qid=%s: %d candidates -> %d answer items after rerank",
                qid,
                len(candidates_for_rerank),
                len(retrievals[qid]),
            )

        logger.bind(opportunity_id=opportunity_id).info(
            "Retrieval pipeline finished for opportunity_id=%s: %d questions, %d total items "
            "(cached embeddings: %d, live embeddings: %d)",
            opportunity_id,
            len(retrievals),
            sum(len(v) for v in retrievals.values()),
            cached_count,
            live_count,
        )
        return {"opportunity_id": opportunity_id, "retrievals": retrievals}
