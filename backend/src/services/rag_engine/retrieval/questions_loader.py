"""Load opportunity questions from PostgreSQL for retrieval (no agent/field_loader dependency)."""

from __future__ import annotations

from typing import Any

from src.services.database_manager import get_db_connection, rows_to_dicts
from src.utils.logger import get_logger


logger = get_logger(__name__)

_questions_loader: QuestionsLoader | None = None


class QuestionsLoader:
    """Load opportunity questions from PostgreSQL for retrieval."""

    def load_questions_for_retrieval(self) -> dict[str, dict]:
        """Return {q_id: {\"text\": str, \"embedding\": list[float] | None}} for all questions.

        Uses PostgreSQL (sase_questions table) via database_manager.
        Raises RuntimeError if DB is not configured.
        """
        con = get_db_connection()
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT q_id, question, question_embedding "
                "FROM sase_questions ORDER BY q_id"
            )
            raw = cur.fetchall()
            rows = rows_to_dicts(cur, raw)
            result: dict[str, dict] = {}
            for row in rows:
                qid = row["q_id"]
                text = (row.get("question") or "") or ""
                raw_embedding = row.get("question_embedding")
                embedding = _parse_embedding(raw_embedding)
                result[qid] = {
                    "text": text,
                    "embedding": embedding,
                }
            logger.info(
                "load_questions_for_retrieval: loaded %d questions from PostgreSQL",
                len(result),
            )
            return result
        finally:
            con.close()


def get_questions_loader() -> QuestionsLoader:
    """Return the singleton QuestionsLoader instance."""
    global _questions_loader
    if _questions_loader is None:
        _questions_loader = QuestionsLoader()
    return _questions_loader


def load_questions_for_retrieval() -> dict[str, dict]:
    """Return {q_id: {"text": str, "embedding": list[float] | None}} for all questions."""
    return get_questions_loader().load_questions_for_retrieval()


def load_questions_and_answer_types() -> dict[str, tuple[str, str]]:
    """Compatibility helper for legacy callers expecting (question, answer_type).

    The original implementation loaded question text and answer type from the
    database. For current retrieval use-cases we only need the question text,
    so this shim returns a default answer_type of \"text\" for every question.
    """
    questions = get_questions_loader().load_questions_for_retrieval()
    return {
        qid: (payload.get("text", ""), "text") for qid, payload in questions.items()
    }


def _parse_embedding(value: Any) -> list[float] | None:
    """Normalize DB question_embedding into list[float] or None.

    Handles:
      - None → None
      - list/tuple of numbers or numeric strings → list[float]
      - pgvector literal string "[0.1,0.2,...]" → list[float]
    On any parse error, returns None so callers can fall back to live embedding.
    """
    if value is None:
        return None

    # Already a numeric sequence (list/tuple); coerce each element to float.
    if isinstance(value, (list, tuple)):
        out: list[float] = []
        for x in value:
            try:
                out.append(float(x))
            except (TypeError, ValueError):
                return None
        return out

    # pgvector stored as text: "[0.1,0.2,...]"
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # Strip optional surrounding brackets.
        if s[0] == "[" and s[-1] == "]":
            s = s[1:-1]
        parts = [p.strip() for p in s.split(",") if p.strip()]
        out: list[float] = []
        try:
            for part in parts:
                out.append(float(part))
        except ValueError:
            return None
        return out or None

    # Unknown type; safer to ignore and recompute.
    return None
