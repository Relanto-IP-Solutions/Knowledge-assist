"""Build BRD §18 form JSON and optionally write to GCS."""

from __future__ import annotations

import ast
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from configs.settings import get_settings
from src.services.agent.dependency import get_active_question_ids
from src.utils.logger import get_logger


logger = get_logger(__name__)

_form_output_builder: FormOutputBuilder | None = None


def norm_val_str(val: Any) -> str:
    """Normalize value to string for dedupe."""
    def _norm_token(x: Any) -> str:
        # Case-insensitive normalization for conflict/dedupe keys.
        return str(x).strip().casefold()

    if val is None:
        return ""
    if isinstance(val, str):
        s = val.strip()
        # Some worker outputs stringify multiselect lists. Normalize list-like strings
        # so ordering does not create artificial conflicts.
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = ast.literal_eval(s)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                return ",".join(sorted(_norm_token(x) for x in parsed))
    if isinstance(val, list):
        return ",".join(sorted(_norm_token(x) for x in val))
    return _norm_token(val)


def _canonicalize_multiselect_value(val: Any) -> Any:
    """Return a deterministic representation for multiselect values.

    The UI may treat list order as meaningful; for multiselect answers we sort
    case-insensitively to avoid artificial conflicts from ordering differences.
    """
    if val is None:
        return None
    if isinstance(val, str):
        s = val.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = ast.literal_eval(s)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                return sorted([str(x).strip() for x in parsed], key=lambda x: x.casefold())
        return val
    if isinstance(val, list):
        return sorted([str(x).strip() for x in val], key=lambda x: x.casefold())
    return val


class FormOutputBuilder:
    """Build BRD §18 form JSON and optionally write to GCS."""

    def _all_question_ids(self) -> list[str]:
        """Return all DB-backed question IDs in batch order."""
        from src.services.agent.batch_registry import get_batches
        from src.services.agent.field_loader import load_batch_fields

        qids: list[str] = []
        for batch in get_batches():
            qids.extend(field.q_id for field in load_batch_fields(batch.batch_id))
        return qids

    def _citation_from_basis(self, ab: dict, source_file_fallback: str = "") -> dict:
        """Build API citation from answer_basis/source entry."""
        return {
            "source_document": ab.get("source", "unknown"),
            "source_chunk": ab.get("excerpt") or ab.get("source_chunk") or "",
            "chunk_id": ab.get("chunk_id") or "",
            "source_type": ab.get("source_type") or "doc",
            "source_file": ab.get("source_file")
            or ab.get("document_id")
            or source_file_fallback
            or "",
            # similarity_score here is the per-chunk retrieval similarity (confidence_score in answer_basis)
            "similarity_score": ab.get("confidence_score"),
            "rerank_score": ab.get("rerank_score"),
        }

    def _citation_from_conflict_detail(self, detail: dict) -> dict:
        """Build API citation from a conflict_details entry."""
        src = (detail.get("source") or "").strip()
        sfile = (detail.get("source_file") or "").strip()
        if not src and sfile:
            src = Path(sfile).name
        return {
            "source_document": src or "unknown",
            "source_chunk": detail.get("excerpt") or "",
            "chunk_id": detail.get("chunk_id") or "",
            "source_type": detail.get("source_type") or "doc",
            "source_file": sfile or src or "",
            "similarity_score": detail.get("confidence_score"),
            "rerank_score": detail.get("rerank_score"),
        }

    def _sort_q_id(self, q: str) -> tuple[str, int]:
        """Sort key for question IDs (e.g. OPP-001, OPP-002)."""
        parts = q.split("-", 1)
        return (
            parts[0],
            int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else 0,
        )

    def extract_conflict_alternatives(
        self,
        candidate_answers: list[dict],
        question_ids: set[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Extract conflict entries (answer_value, confidence_score, citations) for given questions."""
        by_q: dict[str, list] = {}
        for c in candidate_answers:
            qid = c.get("question_id", "")
            if qid and qid in question_ids:
                by_q.setdefault(qid, []).append(c)

        result: dict[str, list[dict[str, Any]]] = {}
        for qid in question_ids:
            candidates = by_q.get(qid, [])
            seen: set[str] = set()
            entries: list[dict] = []
            for c in candidates:
                for detail in c.get("conflict_details") or []:
                    val = detail.get("value")
                    val = _canonicalize_multiselect_value(val)
                    val_str = norm_val_str(val) if val is not None else ""
                    if val_str and val_str not in seen:
                        seen.add(val_str)
                        entries.append({
                            "answer_value": val,
                            "confidence_score": float(
                                detail.get("confidence_score", 0) or 0
                            ),
                            "citations": [self._citation_from_conflict_detail(detail)],
                        })
                cand_val = c.get("candidate_answer")
                if cand_val is None:
                    continue
                cand_val = _canonicalize_multiselect_value(cand_val)
                cand_str = norm_val_str(cand_val)
                if cand_str not in seen:
                    seen.add(cand_str)
                    cand_basis = c.get("answer_basis") or c.get("sources") or []
                    entries.append({
                        "answer_value": cand_val,
                        "confidence_score": float(c.get("confidence", 0) or 0),
                        "citations": [self._citation_from_basis(b) for b in cand_basis],
                    })
            if entries:
                result[qid] = entries
        return result

    def build_full_answers_payload(
        self,
        opportunity_id: str,
        final_answers: dict[str, dict[str, Any]],
        candidate_answers: list[dict],
        accumulated_conflict_alternatives: dict[str, list[dict[str, Any]]]
        | None = None,
    ) -> dict[str, Any]:
        """Build full answers payload: opportunity_id, answers with answer_value, confidence_score, citations, conflicts."""
        accumulated = accumulated_conflict_alternatives or {}
        by_q: dict[str, list] = {}
        for c in candidate_answers:
            qid = c.get("question_id", "")
            if qid:
                by_q.setdefault(qid, []).append(c)

        current_answers = {
            qid: data.get("answer") for qid, data in final_answers.items()
        }
        active = get_active_question_ids(
            current_answers, all_question_ids=self._all_question_ids()
        )
        answers_list: list[dict[str, Any]] = []

        for q_id in sorted(active, key=self._sort_q_id):
            data = final_answers.get(q_id, {})
            answer_val = _canonicalize_multiselect_value(data.get("answer"))
            confidence = float(data.get("confidence", 0) or 0)
            basis = data.get("answer_basis") or data.get("sources") or []
            citations = [self._citation_from_basis(b) for b in basis]

            selected_str = norm_val_str(answer_val)
            seen_conflict_values: set[str] = set()
            conflicts_list: list[dict] = []

            for entry in accumulated.get(q_id, []):
                v = _canonicalize_multiselect_value(entry.get("answer_value"))
                v_str = norm_val_str(v) if v is not None else ""
                if (
                    v_str
                    and v_str != selected_str
                    and v_str not in seen_conflict_values
                ):
                    seen_conflict_values.add(v_str)
                    conflicts_list.append({
                        "answer_value": entry.get("answer_value"),
                        "confidence_score": float(
                            entry.get("confidence_score", 0) or 0
                        ),
                        "citations": entry.get("citations", []),
                    })

            for c in by_q.get(q_id, []):
                for detail in c.get("conflict_details") or []:
                    val = _canonicalize_multiselect_value(detail.get("value"))
                    val_str = norm_val_str(val) if val is not None else ""
                    if (
                        not val_str
                        or val_str == selected_str
                        or val_str in seen_conflict_values
                    ):
                        continue
                    seen_conflict_values.add(val_str)
                    conflicts_list.append({
                        "answer_value": val,
                        "confidence_score": float(
                            detail.get("confidence_score", 0) or 0
                        ),
                        "citations": [self._citation_from_conflict_detail(detail)],
                    })
                cand_val = c.get("candidate_answer")
                if cand_val is None:
                    continue
                cand_val = _canonicalize_multiselect_value(cand_val)
                cand_str = norm_val_str(cand_val)
                if cand_str == selected_str or cand_str in seen_conflict_values:
                    continue
                seen_conflict_values.add(cand_str)
                cand_basis = c.get("answer_basis") or c.get("sources") or []
                conflicts_list.append({
                    "answer_value": cand_val,
                    "confidence_score": float(c.get("confidence", 0) or 0),
                    "citations": [self._citation_from_basis(b) for b in cand_basis],
                })

            entry_out: dict = {
                "question_id": q_id,
                "answer_value": answer_val,
                "confidence_score": confidence,
                "citations": citations,
                "conflicts": conflicts_list,
            }
            answers_list.append(entry_out)

        logger.info(
            "form_output built | opportunity_id={} answer_entries={}",
            opportunity_id,
            len(answers_list),
        )
        return {
            "opportunity_id": opportunity_id,
            "answers": answers_list,
        }

    def build_form_output(
        self,
        opportunity_id: str,
        final_answers: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Build final form JSON per BRD §18: form_id + answers array."""
        current_answers = {
            qid: data.get("answer") for qid, data in final_answers.items()
        }
        active = get_active_question_ids(
            current_answers, all_question_ids=self._all_question_ids()
        )
        form_id = (
            f"{get_settings().agent.form_id_prefix}_{opportunity_id.replace('-', '_')}"
        )
        answers_list: list[dict[str, Any]] = []
        for qid in sorted(active):
            data = final_answers.get(qid, {})
            answers_list.append({
                "question_id": qid,
                "answer": data.get("answer"),
            })
        return {
            "form_id": form_id,
            "opportunity_id": opportunity_id,
            "answers": answers_list,
        }

    def write_form_output_gcs(
        self,
        opportunity_id: str,
        form_output: dict[str, Any],
    ) -> str | None:
        """Write form_output JSON to GCS. Returns URI or None."""
        try:
            from src.services.storage.service import Storage

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"form_output_{ts}.json"
            content = json.dumps(form_output, indent=2, ensure_ascii=False)
            uri = Storage().write_response(opportunity_id, filename, content)
            logger.bind(opportunity_id=opportunity_id).info(
                "Wrote form output to GCS: %s",
                uri,
            )
            return uri
        except Exception as e:
            logger.bind(opportunity_id=opportunity_id).warning(
                "GCS write of form output failed: %s",
                e,
            )
            return None


def get_form_output_builder() -> FormOutputBuilder:
    """Return the singleton FormOutputBuilder instance."""
    global _form_output_builder
    if _form_output_builder is None:
        _form_output_builder = FormOutputBuilder()
    return _form_output_builder


def extract_conflict_alternatives(
    candidate_answers: list[dict],
    question_ids: set[str],
) -> dict[str, list[dict[str, Any]]]:
    """Extract conflict entries for given questions."""
    return get_form_output_builder().extract_conflict_alternatives(
        candidate_answers, question_ids
    )


def build_full_answers_payload(
    opportunity_id: str,
    final_answers: dict[str, dict[str, Any]],
    candidate_answers: list[dict],
    accumulated_conflict_alternatives: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build full answers payload."""
    return get_form_output_builder().build_full_answers_payload(
        opportunity_id,
        final_answers,
        candidate_answers,
        accumulated_conflict_alternatives,
    )


def build_form_output(
    opportunity_id: str,
    final_answers: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build final form JSON per BRD §18."""
    return get_form_output_builder().build_form_output(opportunity_id, final_answers)


def write_form_output_gcs(
    opportunity_id: str,
    form_output: dict[str, Any],
) -> str | None:
    """Write form_output JSON to GCS. Returns URI or None."""
    return get_form_output_builder().write_form_output_gcs(opportunity_id, form_output)
