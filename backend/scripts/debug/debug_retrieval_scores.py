"""Standalone debug script for retrieval score inspection.

All diagnostic output is written to a JSON file only (no terminal prints).

Runs the retrieval pipeline with the same similarity filter as production:
  Vector Search → filter by SIMILARITY_MIN_THRESHOLD → rerank → answer items.
Output is production-like: results per question (items that passed), plus
filtered_out per question (chunks dropped by the similarity threshold) in the
same item format at the bottom.

Usage:
    uv run python scripts/debug/debug_retrieval_scores.py <opportunity_id>
    uv run python scripts/debug/debug_retrieval_scores.py <opportunity_id> --qid OPP-001
    uv run python scripts/debug/debug_retrieval_scores.py <opportunity_id> --question "Does the customer use SASE?"
    uv run python scripts/debug/debug_retrieval_scores.py <opportunity_id> --all-questions
    uv run python scripts/debug/debug_retrieval_scores.py <opportunity_id> --skip-rerank
    uv run python scripts/debug/debug_retrieval_scores.py <opportunity_id> --output path/to/out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Bootstrap: project root on sys.path, .env files loaded
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv


# Load config first, then secrets so secret vars (e.g. VECTOR_SOURCE_*) always apply
for _ef in (
    _PROJECT_ROOT / "configs" / ".env",
    _PROJECT_ROOT / "configs" / "secrets" / ".env",
):
    if _ef.exists():
        load_dotenv(_ef, override=True)

SENTINEL = -1e9


def _candidate_to_item(c: dict[str, Any]) -> dict[str, Any]:
    """Build production-style item dict from a raw candidate (e.g. for filtered-out)."""
    from src.services.rag_engine.retrieval.utils import (
        distance_to_similarity,
        first_or_none,
    )

    restricts_map = c.get("restricts") or {}
    source_id = first_or_none(restricts_map.get("source_id")) or "unknown_source"
    document_id = first_or_none(restricts_map.get("document_id"))
    chunk_id = c.get("datapoint_id")
    sim = distance_to_similarity(c.get("distance"))
    return {
        "text": (c.get("text") or "").strip(),
        "source": source_id,
        "source_type": c.get("source_type") or "unknown",
        "similarity_score": sim if sim is not None else 0.0,
        "rerank_score": None,
        "document_id": document_id,
        "chunk_id": chunk_id,
    }


# ---------------------------------------------------------------------------
# Stage 1 – Embedding
# ---------------------------------------------------------------------------


def stage_embed(question: str) -> tuple[list[float], dict]:
    from src.services.rag_engine.retrieval.embedding import embed_question

    vec = embed_question(question)
    norm = sum(v**2 for v in vec) ** 0.5
    return vec, {
        "dim": len(vec),
        "l2_norm": round(norm, 6),
        "is_normalized": 0.99 < norm < 1.01,
        "first_8_values": [round(v, 6) for v in vec[:8]],
    }


# ---------------------------------------------------------------------------
# Stage 2 – Vector Search (raw)
# ---------------------------------------------------------------------------


def stage_vector_search(
    use_combined: bool,
    sources: list,
    embedding: list[float],
    opportunity_id: str,
    token: str,
    k_per_source: int,
) -> tuple[list[dict[str, Any]], dict]:
    from src.services.rag_engine.retrieval.utils import distance_to_similarity
    from src.services.rag_engine.retrieval.vector_search import (
        retrieve_topk_from_combined_source,
        retrieve_topk_from_source,
    )

    all_candidates: list[dict[str, Any]] = []
    per_source: list[dict] = []

    if use_combined:
        candidates = retrieve_topk_from_combined_source(
            embedding, opportunity_id, token, k_per_source
        )
        raw_distances = [c.get("distance") for c in candidates]
        positive_dists = [d for d in raw_distances if d is not None and d > 0]
        negative_dists = [d for d in raw_distances if d is not None and d <= 0]
        neighbors_info = []
        for c in candidates:
            d = c.get("distance")
            sim = distance_to_similarity(d)
            neighbors_info.append({
                "datapoint_id": c.get("datapoint_id"),
                "raw_distance": d,
                "converted_similarity": sim,
                "distance_sign": "positive"
                if (d is not None and d > 0)
                else "non-positive",
                "text_preview": (c.get("text") or "")[:80],
            })
        issues = []
        if positive_dists:
            issues.append(
                f"{len(positive_dists)}/{len(raw_distances)} distances are POSITIVE. "
                "distance_to_similarity() does -distance which gives NEGATIVE similarity_score. "
                "Likely cause: index uses COSINE/L2 distance, or embedding dot products are negative "
                "(task_type mismatch between ingestion and retrieval)."
            )
        if not candidates:
            issues.append(
                f"No results returned. Check that documents for opportunity_id='{opportunity_id}' "
                "are indexed with matching restrict filter."
            )
        per_source.append({
            "source": "combined",
            "neighbors_returned": len(candidates),
            "positive_distances": len(positive_dists),
            "non_positive_distances": len(negative_dists),
            "issues": issues,
            "neighbors": neighbors_info,
        })
        all_candidates.extend(candidates)
    else:
        for src in sources:
            candidates = retrieve_topk_from_source(
                src, embedding, opportunity_id, token, k_per_source
            )
            raw_distances = [c.get("distance") for c in candidates]
            positive_dists = [d for d in raw_distances if d is not None and d > 0]
            negative_dists = [d for d in raw_distances if d is not None and d <= 0]
            neighbors_info = []
            for c in candidates:
                d = c.get("distance")
                sim = distance_to_similarity(d)
                neighbors_info.append({
                    "datapoint_id": c.get("datapoint_id"),
                    "raw_distance": d,
                    "converted_similarity": sim,
                    "distance_sign": "positive"
                    if (d is not None and d > 0)
                    else "non-positive",
                    "text_preview": (c.get("text") or "")[:80],
                })
            issues = []
            if positive_dists:
                issues.append(
                    f"{len(positive_dists)}/{len(raw_distances)} distances are POSITIVE. "
                    "distance_to_similarity() does -distance which gives NEGATIVE similarity_score. "
                    "Likely cause: index uses COSINE/L2 distance, or embedding dot products are negative "
                    "(task_type mismatch between ingestion and retrieval)."
                )
            if not candidates:
                issues.append(
                    f"No results returned. Check that documents for opportunity_id='{opportunity_id}' "
                    "are indexed with matching restrict filter."
                )
            per_source.append({
                "source": src.name,
                "neighbors_returned": len(candidates),
                "positive_distances": len(positive_dists),
                "non_positive_distances": len(negative_dists),
                "issues": issues,
                "neighbors": neighbors_info,
            })
            all_candidates.extend(candidates)

    return all_candidates, {
        "sources": per_source,
        "total_candidates": len(all_candidates),
    }


# ---------------------------------------------------------------------------
# Stage 3 – Reranker (raw)
# ---------------------------------------------------------------------------


def stage_rerank(
    query: str,
    candidates: list[dict[str, Any]],
    token: str,
    k_final: int,
) -> tuple[list[dict[str, Any]], dict]:
    if not candidates:
        return [], {"error": "No candidates to rerank (Vector Search returned nothing)"}

    import requests

    from configs.settings import get_settings

    settings = get_settings().retrieval
    project_id = settings.gcp_project_id or get_settings().ingestion.gcp_project_id

    valid_candidates = [c for c in candidates if (c.get("text") or "").strip()]
    dropped_empty_text = len(candidates) - len(valid_candidates)

    if not valid_candidates:
        return [], {
            "error": "All candidates have empty text — cannot rerank. Check embeddingMetadata at ingestion."
        }

    records = [
        {"id": str(c["datapoint_id"]), "content": c["text"]} for c in valid_candidates
    ]
    endpoint = (
        f"https://{settings.rank_location}-discoveryengine.googleapis.com/v1/"
        f"projects/{project_id}/locations/{settings.rank_location}/"
        f"rankingConfigs/{settings.ranking_config_id}:rank"
    )
    payload = {
        "model": settings.rank_model,
        "query": query,
        "records": records,
        "topN": min(k_final, len(records)),
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = requests.post(endpoint, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    returned_records = data.get("records", []) or []
    score_by_id: dict[str, float] = {}
    for r in returned_records:
        rid = r.get("id")
        sc = r.get("score")
        if rid is not None and sc is not None:
            score_by_id[str(rid)] = float(sc)

    sentinel_ids = []
    for c in valid_candidates:
        dp_id = str(c["datapoint_id"])
        if dp_id in score_by_id:
            c["rerank_score"] = score_by_id[dp_id]
        else:
            c["rerank_score"] = SENTINEL
            sentinel_ids.append(dp_id)

    ranked = sorted(valid_candidates, key=lambda x: x["rerank_score"], reverse=True)
    result = ranked[:k_final]

    issues = []
    if dropped_empty_text:
        issues.append(
            f"{dropped_empty_text} candidate(s) dropped for empty text before reranking."
        )
    if sentinel_ids:
        issues.append(
            f"{len(sentinel_ids)} candidate(s) got -1e9 sentinel: IDs not in reranker response. "
            f"IDs: {sentinel_ids}. Cause: topN truncation or datapoint_id type mismatch."
        )

    raw_scores = [
        {"id": r.get("id"), "score": r.get("score")} for r in returned_records
    ]
    raw_scores.sort(key=lambda x: x["score"] or 0, reverse=True)

    return result, {
        "endpoint": endpoint,
        "model": settings.rank_model,
        "top_n_requested": payload["topN"],
        "records_sent": len(records),
        "records_returned": len(returned_records),
        "sentinel_fallback_ids": sentinel_ids,
        "dropped_empty_text": dropped_empty_text,
        "issues": issues,
        "raw_api_scores": raw_scores,
    }


# ---------------------------------------------------------------------------
# Stage 4 – Final answer items
# ---------------------------------------------------------------------------


def stage_build_answer_items(
    topk: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict]]:
    from src.services.rag_engine.retrieval.utils import build_answer_items

    items = build_answer_items(topk)

    per_item_issues = []
    for it in items:
        sim = it.get("similarity_score")
        rr = it.get("rerank_score")
        issues = []
        if sim is not None and sim < 0:
            issues.append(
                "similarity_score < 0 (raw distance was positive — see Stage 2 diagnosis)"
            )
        if rr is not None and rr < 0 and rr > SENTINEL * 0.9:
            issues.append("rerank_score < 0 (reranker rates this as low relevance)")
        if rr is not None and rr <= SENTINEL * 0.9:
            issues.append(
                "rerank_score = -1e9 SENTINEL (datapoint_id not in reranker response)"
            )
        per_item_issues.append({"chunk_id": it.get("chunk_id"), "issues": issues})

    return items, per_item_issues


# ---------------------------------------------------------------------------
# Run for one question
# ---------------------------------------------------------------------------


def run_one_question(
    qid: str,
    question: str,
    opportunity_id: str,
    use_combined: bool,
    sources: list,
    token: str,
    k_per_source: int,
    k_final: int,
    skip_rerank: bool,
    min_similarity: float,
) -> dict[str, Any]:
    from src.services.rag_engine.retrieval.utils import filter_candidates_by_similarity

    embedding, embed_info = stage_embed(question)
    candidates, vs_info = stage_vector_search(
        use_combined, sources, embedding, opportunity_id, token, k_per_source
    )

    # Apply same similarity filter as production (before reranker)
    passed = filter_candidates_by_similarity(candidates, min_similarity)
    passed_ids = {p.get("datapoint_id") for p in passed}
    filtered_out_candidates = [
        c for c in candidates if c.get("datapoint_id") not in passed_ids
    ]
    filtered_out_items = [
        _candidate_to_item(c)
        for c in filtered_out_candidates
        if (c.get("text") or "").strip()
    ]

    if skip_rerank:
        topk = passed[:k_final]
        rerank_info: dict = {"skipped": True}
    else:
        topk, rerank_info = stage_rerank(question, passed, token, k_final)

    items, item_issues = stage_build_answer_items(topk)

    sim_scores = [
        it["similarity_score"] for it in items if it.get("similarity_score") is not None
    ]
    rr_scores = [
        it["rerank_score"] for it in items if it.get("rerank_score") is not None
    ]
    real_rr = [s for s in rr_scores if s > SENTINEL * 0.9]
    sentinel_count = len(rr_scores) - len(real_rr)

    return {
        "qid": qid,
        "question": question,
        "stages": {
            "embedding": embed_info,
            "vector_search": vs_info,
            "reranker": rerank_info,
        },
        "items": items,
        "filtered_out_items": filtered_out_items,
        "per_item_issues": item_issues,
        "score_summary": {
            "similarity_scores": {
                "count": len(sim_scores),
                "negative": sum(1 for s in sim_scores if s < 0),
                "min": min(sim_scores) if sim_scores else None,
                "max": max(sim_scores) if sim_scores else None,
            },
            "rerank_scores": {
                "count": len(real_rr),
                "negative": sum(1 for s in real_rr if s < 0),
                "sentinel_count": sentinel_count,
                "min": min(real_rr) if real_rr else None,
                "max": max(real_rr) if real_rr else None,
            },
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Debug retrieval pipeline scores. All output written to JSON file only."
    )
    parser.add_argument(
        "opportunity_id", help="Opportunity ID (used as Vector Search restrict filter)"
    )
    parser.add_argument(
        "--qid",
        default=None,
        help="Test a single question by q_id from sase_questions table",
    )
    parser.add_argument(
        "--question",
        default=None,
        help="Test with a custom freeform question (bypasses DB)",
    )
    parser.add_argument(
        "--all-questions", action="store_true", help="Run all questions from DB"
    )
    parser.add_argument(
        "--k-per-source", type=int, default=None, help="Override K_PER_SOURCE setting"
    )
    parser.add_argument(
        "--k-final", type=int, default=None, help="Override K_FINAL setting"
    )
    parser.add_argument(
        "--skip-rerank", action="store_true", help="Skip the reranker stage"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path (default: data/output/debug_retrieval_scores_<opp_id>.json)",
    )
    args = parser.parse_args()

    from configs.settings import get_settings

    settings = get_settings().retrieval
    k_per_source = args.k_per_source or settings.k_per_source
    k_final = args.k_final or settings.k_final
    min_similarity = settings.similarity_min_threshold

    from src.services.rag_engine.retrieval.embedding import get_access_token
    from src.services.rag_engine.retrieval.vector_search import (
        get_combined_source,
        get_sources,
    )

    token = get_access_token()
    combined = get_combined_source()
    use_combined = combined is not None
    sources = [] if use_combined else get_sources()

    if use_combined:
        init_sources = [
            {
                "name": combined.name,
                "index_endpoint": combined.index_endpoint,
                "deployed_index_id": combined.deployed_index_id,
            }
        ]
    else:
        init_sources = [
            {
                "name": s.name,
                "index_endpoint": s.index_endpoint,
                "deployed_index_id": s.deployed_index_id,
            }
            for s in sources
        ]

    init_info: dict[str, Any] = {
        "opportunity_id": args.opportunity_id,
        "k_per_source": k_per_source,
        "k_final": k_final,
        "skip_rerank": args.skip_rerank,
        "similarity_min_threshold": min_similarity,
        "source_mode": "combined" if use_combined else "multi",
        "sources": init_sources,
    }

    if not use_combined and not sources:
        out = {
            **init_info,
            "error": "No vector sources configured. Set VECTOR_SOURCE_COMBINED_* or VECTOR_SOURCES / VECTOR_SOURCE_DRIVE/ZOOM/SLACK_* env vars.",
        }
        _write_output(out, args.output, args.opportunity_id)
        return

    # Determine questions to run
    questions_to_run: dict[str, str] = {}

    if args.question:
        questions_to_run["custom"] = args.question
    elif args.qid:
        from src.services.rag_engine.retrieval.questions_loader import (
            load_questions_for_retrieval,
        )

        all_qs = load_questions_for_retrieval()
        if args.qid not in all_qs:
            out = {
                **init_info,
                "error": f"qid '{args.qid}' not found. Available: {list(all_qs.keys())[:10]}",
            }
            _write_output(out, args.output, args.opportunity_id)
            return
        questions_to_run[args.qid] = all_qs[args.qid]
    elif args.all_questions:
        from src.services.rag_engine.retrieval.questions_loader import (
            load_questions_for_retrieval,
        )

        questions_to_run = load_questions_for_retrieval()
    else:
        from src.services.rag_engine.retrieval.questions_loader import (
            load_questions_for_retrieval,
        )

        all_qs = load_questions_for_retrieval()
        questions_to_run = dict(list(all_qs.items())[:3])

    # Run each question
    question_results: list[dict] = []
    all_sim: list[float] = []
    all_rr: list[float] = []
    total_sentinel = 0

    for qid, question in questions_to_run.items():
        q = (question or "").strip()
        if not q:
            question_results.append({"qid": qid, "skipped": "empty question"})
            continue
        result = run_one_question(
            qid=qid,
            question=q,
            opportunity_id=args.opportunity_id,
            use_combined=use_combined,
            sources=sources,
            token=token,
            k_per_source=k_per_source,
            k_final=k_final,
            skip_rerank=args.skip_rerank,
            min_similarity=min_similarity,
        )
        question_results.append(result)
        ss = result["score_summary"]
        all_sim.extend(
            it["similarity_score"]
            for it in result["items"]
            if it.get("similarity_score") is not None
        )
        rr_info = ss["rerank_scores"]
        total_sentinel += rr_info.get("sentinel_count", 0)
        all_rr.extend(
            it["rerank_score"]
            for it in result["items"]
            if it.get("rerank_score") is not None
            and it["rerank_score"] > SENTINEL * 0.9
        )

    # Global diagnosis
    n_neg_sim = sum(1 for s in all_sim if s < 0)
    n_neg_rr = sum(1 for s in all_rr if s < 0)
    diagnosis: list[str] = []

    if n_neg_sim > 0:
        diagnosis.append(
            f"{n_neg_sim}/{len(all_sim)} similarity_scores are negative. "
            "Raw distances from Vector Search are positive, meaning dot_product(query, doc) < 0. "
            "Most likely cause: text-embedding-004 called without task_type on both ingestion and retrieval sides. "
            "The default SEMANTIC_SIMILARITY task produces embeddings not optimized for asymmetric retrieval — "
            "query and document vectors can have negative dot products even for topically related content. "
            "Fix: use task_type='RETRIEVAL_QUERY' at query time and task_type='RETRIEVAL_DOCUMENT' at ingestion. "
            "Short-term: use rerank_score as the confidence signal instead of similarity_score."
        )
    if total_sentinel > 0:
        diagnosis.append(
            f"{total_sentinel} rerank_score(s) are -1e9 sentinel. "
            "Candidates whose datapoint_id was not in the reranker API response. "
            "Check topN vs num_candidates and datapoint_id type consistency."
        )
    if n_neg_rr > 0:
        diagnosis.append(
            f"{n_neg_rr}/{len(all_rr)} rerank_scores are negative (not sentinel). "
            "semantic-ranker-512 outputs raw logits; negative = below-threshold relevance. "
            "Add a rerank_score > 0 threshold to filter low-confidence results."
        )
    if not diagnosis:
        diagnosis.append("No score issues detected.")

    # Production-like: results per question (items that passed filter + rerank)
    results_by_qid: dict[str, list[dict[str, Any]]] = {}
    filtered_out_by_qid: dict[str, list[dict[str, Any]]] = {}
    for r in question_results:
        if r.get("qid") and "items" in r:
            results_by_qid[r["qid"]] = r["items"]
        if r.get("qid") and "filtered_out_items" in r:
            filtered_out_by_qid[r["qid"]] = r["filtered_out_items"]

    output_payload = {
        **init_info,
        "questions_run": list(questions_to_run.keys()),
        "results": results_by_qid,
        "filtered_out": filtered_out_by_qid,
        "question_results": question_results,
        "score_summary": {
            "similarity_scores": {
                "count": len(all_sim),
                "negative": n_neg_sim,
                "min": min(all_sim) if all_sim else None,
                "max": max(all_sim) if all_sim else None,
            },
            "rerank_scores": {
                "count": len(all_rr),
                "negative": n_neg_rr,
                "sentinel_count": total_sentinel,
                "min": min(all_rr) if all_rr else None,
                "max": max(all_rr) if all_rr else None,
            },
        },
        "diagnosis": diagnosis,
    }

    out_path = _write_output(output_payload, args.output, args.opportunity_id)
    print(out_path)


def _write_output(payload: dict, output_arg: str | None, opp_id: str) -> Path:
    if output_arg:
        out_path = Path(output_arg)
    else:
        out_dir = _PROJECT_ROOT / "data" / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        opp_safe = opp_id.replace("/", "_")
        out_path = out_dir / f"debug_retrieval_scores_{opp_safe}.json"
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out_path


if __name__ == "__main__":
    main()
