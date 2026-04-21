"""Dependency rule evaluation: which questions are active given current answers.

Supports depends_on_question + optional condition (e.g. "Yes", "value in list").
Rules will be loaded from DB (sase_questions.dependent_on) when schema support is added.
"""

from __future__ import annotations

from typing import Any

from src.services.agent.batch_registry import get_batches
from src.services.agent.field_loader import load_batch_fields


_dependency_engine: DependencyEngine | None = None


class DependencyEngine:
    """Evaluate which questions are active given current answers."""

    def _load_dependency_rules(self) -> dict[str, dict]:
        """Load dependency rules: question_id -> {depends_on_question, depends_on_condition}.

        TODO: Load from DB (sase_questions.dependent_on) when schema support is added.
        Until then, returns empty dict so all questions are active.
        """
        return {}

    def _eval_condition(self, condition: str | None, answer_value: object) -> bool:
        """Return True if condition is satisfied by answer_value.

        Simple rules: "Yes", "No", or comma-separated values (answer in list).
        """
        if not condition:
            return answer_value is not None
        cond = condition.strip()
        if answer_value is None:
            return False
        if cond in ("Yes", "No", "true", "false"):
            return str(answer_value).strip().lower() == cond.lower()
        allowed = [v.strip() for v in cond.split(",")]
        if isinstance(answer_value, list):
            return any(str(x).strip() in allowed for x in answer_value)
        return str(answer_value).strip() in allowed

    def get_active_question_ids(
        self,
        current_answers: dict[str, Any],
        *,
        all_question_ids: list[str] | None = None,
    ) -> set[str]:
        """Return set of question IDs that are active given current answers.

        current_answers should map question_id -> answer value (not full answer dict).

        A question is active if:
        - It has no dependency rule, or
        - Its depends_on_question is in current_answers and depends_on_condition is met.

        Args:
            current_answers: question_id -> answer value (from final or partial answers).
            all_question_ids: If provided, only these IDs are considered; else all from DB.

        Returns:
            Set of question_id that should be included in form output / validation.
        """
        if all_question_ids is None:
            all_question_ids = []
            for b in get_batches():
                for f in load_batch_fields(b.batch_id):
                    all_question_ids.append(f.q_id)

        rules = self._load_dependency_rules()
        active: set[str] = set()

        for qid in all_question_ids:
            rule = rules.get(qid)
            if not rule:
                active.add(qid)
                continue
            dep_q = rule.get("depends_on_question")
            dep_cond = rule.get("depends_on_condition")
            if not dep_q:
                active.add(qid)
                continue
            parent_val = current_answers.get(dep_q)
            if self._eval_condition(dep_cond, parent_val):
                active.add(qid)

        return active


def get_dependency_engine() -> DependencyEngine:
    """Return the singleton DependencyEngine instance."""
    global _dependency_engine
    if _dependency_engine is None:
        _dependency_engine = DependencyEngine()
    return _dependency_engine


def get_active_question_ids(
    current_answers: dict[str, Any],
    *,
    all_question_ids: list[str] | None = None,
) -> set[str]:
    """Return set of question IDs that are active given current answers."""
    return get_dependency_engine().get_active_question_ids(
        current_answers, all_question_ids=all_question_ids
    )
