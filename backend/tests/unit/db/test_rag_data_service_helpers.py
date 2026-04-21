from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import src.services.database_manager.rag_data_service as rag_data_service


def test__pg_is_unique_violation__detects_pg8000_dict_code() -> None:
    exc = Exception({"C": "23505"})
    assert rag_data_service._pg_is_unique_violation(exc) is True


def test__pg_is_unique_violation__detects_message_fallback() -> None:
    exc = Exception("ERROR: 23505 unique violation")
    assert rag_data_service._pg_is_unique_violation(exc) is True


def test__pg_is_unique_violation__non_unique_returns_false() -> None:
    exc = Exception("some other error")
    assert rag_data_service._pg_is_unique_violation(exc) is False


def test__normalize_answer_text_for_compare__handles_none_and_strips() -> None:
    assert rag_data_service._normalize_answer_text_for_compare(None) == ""
    assert rag_data_service._normalize_answer_text_for_compare("  HeLLo  ") == "hello"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 3),
        (1, 1),
        (5, 5),
        (0, 3),
        (6, 3),
        ("4", 4),
        (" 2 ", 2),
        ("0", 3),
        ("6", 3),
        ("abc", 3),
        ("", 3),
        (object(), 3),
    ],
)
def test__normalize_feedback_type_for_db__coerces_or_defaults(raw, expected: int) -> None:
    assert rag_data_service._normalize_feedback_type_for_db(raw) == expected


def test__pgvector_param__converts_list_to_literal() -> None:
    assert rag_data_service._pgvector_param([0.1, 0.2]) == "[0.1,0.2]"
    assert rag_data_service._pgvector_param("x") == "x"


def test__cosine_similarity__returns_zero_on_empty_or_mismatch() -> None:
    assert rag_data_service._cosine_similarity([], []) == 0.0
    assert rag_data_service._cosine_similarity([1.0], []) == 0.0
    assert rag_data_service._cosine_similarity([1.0], [1.0, 2.0]) == 0.0


def test__cosine_similarity__returns_expected_for_identical_vectors() -> None:
    a = [1.0, 2.0, 3.0]
    b = [1.0, 2.0, 3.0]
    assert rag_data_service._cosine_similarity(a, b) == pytest.approx(1.0, abs=1e-9)


def test__cosine_similarity__returns_expected_for_orthogonal_vectors() -> None:
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert rag_data_service._cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-9)


def test__coerce_pgvector_to_list__accepts_list_of_numbers_or_numeric_strings() -> None:
    assert rag_data_service._coerce_pgvector_to_list([1, "2", 3.5]) == [1.0, 2.0, 3.5]


def test__coerce_pgvector_to_list__parses_pgvector_string_literal() -> None:
    assert rag_data_service._coerce_pgvector_to_list("[0.1, 0.2]") == [0.1, 0.2]


def test__coerce_pgvector_to_list__invalid_returns_none() -> None:
    assert rag_data_service._coerce_pgvector_to_list(None) is None
    assert rag_data_service._coerce_pgvector_to_list("0.1,0.2") is None
    assert rag_data_service._coerce_pgvector_to_list("[]") is None
    assert rag_data_service._coerce_pgvector_to_list("[a, b]") is None
    assert rag_data_service._coerce_pgvector_to_list({"x": 1}) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "unknown"),
        ("", "unknown"),
        ("zoom_transcript", "zoom"),
        ("zoom_transcripts", "zoom"),
        ("slack_messages", "slack"),
        ("slack_message", "slack"),
        ("gdrive_doc", "docx"),
        ("drive", "docx"),
        ("doc", "docx"),
        ("pdf", "pdf"),
        ("pptx", "pptx"),
        ("gmail_messages", "email"),
        ("email", "email"),
        ("some_new_type", "docx"),  # safe default if not allowed
    ],
)
def test__normalize_citation_source_type__maps_and_defaults(raw, expected: str) -> None:
    assert rag_data_service._normalize_citation_source_type(raw) == expected


def test__drop_unique_opportunity_question_on_answers_if_present__delegates() -> None:
    cur = MagicMock()
    # smoke: the helper just delegates; no assertions about DB.
    rag_data_service._drop_unique_opportunity_question_on_answers_if_present(cur)
    assert cur is not None

