"""Supervisor logic: validate, detect conflicts, recall context, select final."""

from __future__ import annotations

import ast
from typing import Any

from configs.settings import get_settings
from src.services.agent.field_loader import get_field_def_by_question_id
from src.services.agent.form_output import answer_dedupe_key
from src.services.agent.state import AgentState, CandidateAnswer
from src.utils.logger import get_logger


logger = get_logger(__name__)

_supervisor: Supervisor | None = None


class Supervisor:
    """Validate candidates, detect conflicts, build recall context, select final answers."""

    def _group_candidates_by_question(
        self,
        candidate_answers: list[CandidateAnswer],
    ) -> dict[str, list[CandidateAnswer]]:
        """Group candidate answers by question_id."""
        by_q: dict[str, list[CandidateAnswer]] = {}
        for c in candidate_answers:
            qid = c.get("question_id", "")
            if qid:
                by_q.setdefault(qid, []).append(c)
        return by_q

    def _get_field_def_for_question(self, question_id: str) -> Any | None:
        """Return FieldDefinition for question_id from any batch."""
        return get_field_def_by_question_id().get(question_id)

    def validate_candidates(self, state: AgentState) -> dict[str, str]:
        """Validate candidate answers: picklist, type, required. Return validation_errors."""
        candidate_answers = state.get("candidate_answers") or []
        by_q = self._group_candidates_by_question(candidate_answers)
        errors: dict[str, str] = {}

        for qid, candidates in by_q.items():
            field_def = self._get_field_def_for_question(qid)
            if not field_def:
                continue
            for c in candidates:
                val = c.get("candidate_answer")
                if val is None and c.get("conflict"):
                    continue
                if val is not None:
                    if (
                        field_def.answer_type in ("picklist", "picklist-search")
                        and field_def.options
                    ):
                        if isinstance(val, list):
                            for v in val:
                                if v not in field_def.options:
                                    errors[qid] = f"Value {v!r} not in picklist options"
                                    break
                        elif val not in field_def.options:
                            errors[qid] = f"Value {val!r} not in picklist options"
                    break

        return errors

    def detect_conflicts(self, state: AgentState) -> dict[str, str]:
        """Detect questions with conflicting candidates or low confidence. Return conflicts dict."""
        candidate_answers = state.get("candidate_answers") or []
        by_q = self._group_candidates_by_question(candidate_answers)
        conflicts: dict[str, str] = {}

        for qid, candidates in by_q.items():
            values = []

            for c in candidates:
                v = c.get("candidate_answer")
                if v is not None:
                    if isinstance(v, str):
                        s = v.strip()
                        if s.startswith("[") and s.endswith("]"):
                            try:
                                parsed = ast.literal_eval(s)
                            except Exception:
                                parsed = None
                            if isinstance(parsed, list):
                                v = parsed
                    if isinstance(v, list):
                        values.append(
                            tuple(sorted(answer_dedupe_key(x) for x in v))
                        )
                    else:
                        values.append(answer_dedupe_key(v))
                for detail in c.get("conflict_details") or []:
                    detail_value = detail.get("value")
                    if detail_value is None:
                        continue
                    values.append(answer_dedupe_key(detail_value))

            # Some workers set `conflict=true` via heuristic keyword matching. If the underlying
            # candidate values are effectively identical (case/order-insensitive), do not surface
            # a conflict.
            if any(c.get("conflict") for c in candidates) and len(set(values)) > 1:
                conflicts[qid] = "worker_flagged_conflict"
                continue
            if len(set(values)) > 1:
                conflicts[qid] = "multiple_differing_values"
                continue
            confidences = [
                c.get("confidence", 0.0) or 0.0
                for c in candidates
                if c.get("candidate_answer") is not None
            ]
            if (
                confidences
                and max(confidences) < get_settings().agent.low_confidence_threshold
            ):
                conflicts[qid] = "low_confidence"

        return conflicts

    def build_recall_context(self, state: AgentState) -> dict[str, Any]:
        """Build recall context: reason and existing candidates for re-evaluation."""
        conflicts = state.get("conflicts") or {}
        candidate_answers = state.get("candidate_answers") or []
        by_q = self._group_candidates_by_question(candidate_answers)

        reasons = []
        existing: dict[str, list[Any]] = {}
        for qid, reason in conflicts.items():
            reasons.append(f"{qid}: {reason}")
            existing[qid] = [
                {
                    "agent_id": c.get("agent_id"),
                    "value": c.get("candidate_answer"),
                    "confidence": c.get("confidence"),
                }
                for c in by_q.get(qid, [])
            ]

        return {
            "reason": "; ".join(reasons)
            if reasons
            else "Re-evaluate with strongest evidence.",
            "existing_by_question": existing,
        }

    @staticmethod
    def _basis_from_conflict_detail(d: dict[str, Any]) -> dict[str, Any]:
        """Shape conflict_detail dict into answer_basis row for citations."""
        return {
            "source": (d.get("source") or "").strip(),
            "excerpt": d.get("excerpt"),
            "source_type": d.get("source_type"),
            "chunk_id": d.get("chunk_id"),
            "confidence_score": d.get("confidence_score"),
            "rerank_score": d.get("rerank_score"),
            "source_file": d.get("source_file"),
        }

    def _fallback_from_conflict_only_candidates(
        self, candidates: list[CandidateAnswer]
    ) -> dict[str, Any] | None:
        """When workers set conflict=True and candidate_answer=None, still pick a primary answer.

        Otherwise the API shows ``answer_value: null`` with text only under ``conflicts[]``.
        """
        scored: list[tuple[dict[str, Any], str]] = []
        for c in candidates:
            aid = str(c.get("agent_id") or "")
            for raw in c.get("conflict_details") or []:
                if isinstance(raw, dict):
                    d = raw
                elif hasattr(raw, "model_dump"):
                    d = raw.model_dump()
                else:
                    continue
                val = d.get("value")
                if val is None or not str(val).strip():
                    continue
                scored.append((d, aid))
        if not scored:
            return None
        best_d, best_aid = max(
            scored,
            key=lambda t: (
                float(t[0].get("confidence_score") or 0.0),
                t[1],
            ),
        )
        return {
            "answer": best_d.get("value"),
            "confidence": float(best_d.get("confidence_score") or 0.0),
            "sources": [],
            "agent_id": best_aid,
            "answer_basis": [self._basis_from_conflict_detail(best_d)],
            "status": "needs_review",
        }

    def select_final_answers(self, state: AgentState) -> dict[str, dict[str, Any]]:
        """Select final answer per question from candidates (by confidence, then single agent)."""
        candidate_answers = state.get("candidate_answers") or []
        by_q = self._group_candidates_by_question(candidate_answers)
        final: dict[str, dict[str, Any]] = {}

        for qid, candidates in by_q.items():
            valid = [
                c
                for c in candidates
                if not c.get("conflict") and c.get("candidate_answer") is not None
            ]
            if not valid:
                fb = self._fallback_from_conflict_only_candidates(candidates)
                if fb:
                    final[qid] = fb
                    continue
                first = candidates[0] if candidates else {}
                sources = first.get("sources", [])
                final[qid] = {
                    "answer": None,
                    "confidence": 0.0,
                    "sources": sources,
                    "agent_id": first.get("agent_id"),
                    "answer_basis": first.get("answer_basis", []),
                    "status": "needs_review",
                }
                continue
            best = max(
                valid,
                key=lambda c: (c.get("confidence") or 0.0, c.get("agent_id") or ""),
            )
            sources = best.get("sources", []) or best.get("answer_basis", [])
            has_evidence = len(sources) > 0
            final[qid] = {
                "answer": best.get("candidate_answer"),
                "confidence": best.get("confidence") or 0.0,
                "sources": best.get("sources", []),
                "agent_id": best.get("agent_id"),
                "answer_basis": best.get("answer_basis", []),
                "status": "confirmed" if has_evidence else "needs_review",
            }

        return final


def get_supervisor() -> Supervisor:
    """Return the singleton Supervisor instance."""
    global _supervisor
    if _supervisor is None:
        _supervisor = Supervisor()
    return _supervisor


def validate_candidates(state: AgentState) -> dict[str, str]:
    """Validate candidate answers: picklist, type, required. Return validation_errors."""
    return get_supervisor().validate_candidates(state)


def detect_conflicts(state: AgentState) -> dict[str, str]:
    """Detect questions with conflicting candidates or low confidence. Return conflicts dict."""
    return get_supervisor().detect_conflicts(state)


def build_recall_context(state: AgentState) -> dict[str, Any]:
    """Build recall context: reason and existing candidates for re-evaluation."""
    return get_supervisor().build_recall_context(state)


def select_final_answers(state: AgentState) -> dict[str, dict[str, Any]]:
    """Select final answer per question from candidates (by confidence, then single agent)."""
    return get_supervisor().select_final_answers(state)
