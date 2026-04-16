from __future__ import annotations

import math
from typing import Any


RERANK_SENTINEL = -1e9


def _sigmoid(z: float) -> float:
    # Numerically stable sigmoid
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


def compute_question_confidence(
    items: list[dict[str, Any]],
    *,
    w_r: float = 0.7,
    w_s: float = 0.3,
    alpha: float = 0.7,
    rerank_temperature: float = 4.0,
) -> float:
    """Compute one confidence score per question from similarity and rerank.

    Accepts either:
      - worker enriched_sources (keys: retrieval_score, rerank_score)
      - answer_basis entries (keys: confidence_score, rerank_score)

    Rerank is a raw logit; we normalize with sigmoid(rerank / T). If rerank is
    missing or sentinel, fall back to similarity-only for that item.
    """
    if not items:
        return 0.0

    chunk_scores: list[float] = []

    for it in items:
        s_raw = it.get("retrieval_score")
        if s_raw is None:
            s_raw = it.get("confidence_score")
        try:
            s = float(s_raw or 0.0)
        except (TypeError, ValueError):
            s = 0.0

        rr = it.get("rerank_score")
        r_available = False
        r = 0.0
        if rr is not None:
            try:
                rr_f = float(rr)
                if rr_f > RERANK_SENTINEL * 0.9:
                    r_available = True
                    r = _sigmoid(rr_f / rerank_temperature)
            except (TypeError, ValueError):
                pass

        if r_available:
            chunk_scores.append((w_r * r) + (w_s * s))
        else:
            chunk_scores.append(s)

    if not chunk_scores:
        return 0.0

    mx = max(chunk_scores)
    mean = sum(chunk_scores) / len(chunk_scores)
    return (alpha * mx) + ((1.0 - alpha) * mean)
