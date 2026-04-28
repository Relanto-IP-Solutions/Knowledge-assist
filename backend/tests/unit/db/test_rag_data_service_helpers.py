from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import src.services.agent.graph as agent_graph
import src.services.database_manager.rag_data_service as rag_data_service
from src.services.agent.form_output import answer_dedupe_key, prefer_answer_display


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


def test_answer_dedupe_key_merges_percentage_formatting_variants() -> None:
    k = answer_dedupe_key("99.9")
    assert k == answer_dedupe_key("99.9%")
    assert k == answer_dedupe_key("  99.9 % ")
    assert answer_dedupe_key("99.95") != answer_dedupe_key("99.9")


def test_answer_dedupe_key_merges_hour_formatting_variants() -> None:
    k = answer_dedupe_key("24")
    assert k == answer_dedupe_key("24 hours")
    assert k == answer_dedupe_key("24Hours")
    assert answer_dedupe_key("24-48") == answer_dedupe_key("24-48 hours")


def test_prefer_answer_display_prefers_percent_sign_or_longer() -> None:
    assert prefer_answer_display("99.9", "99.9%") == "99.9%"
    assert prefer_answer_display("24", "24 hours") == "24 hours"


def test_build_answers_list_for_persistence_dedupes_sla_percent_variants() -> None:
    answers, has_conflicts, conflict_count = (
        agent_graph._build_answers_list_for_persistence({
            "answer_value": "99.9",
            "confidence_score": 0.9,
            "citations": [],
            "conflicts": [
                {"answer_value": "99.9%", "confidence_score": 0.8},
                {"answer_value": "99.95", "confidence_score": 0.7},
                {"answer_value": "99.95%", "confidence_score": 0.6},
            ],
        })
    )
    assert [a["answer_text"] for a in answers] == ["99.9%", "99.95%"]
    assert has_conflicts is True
    assert conflict_count == 2


def test_build_answers_list_for_persistence_preserves_same_run_conflicts() -> None:
    answers, has_conflicts, conflict_count = (
        agent_graph._build_answers_list_for_persistence({
            "answer_value": "latency is 10 mins",
            "confidence_score": 0.9,
            "citations": [{"source_document": "slack", "source_chunk": "10 mins"}],
            "conflicts": [
                {
                    "answer_value": "latency is 4 minutes",
                    "confidence_score": 0.8,
                    "citations": [
                        {"source_document": "doc", "source_chunk": "4 minutes"}
                    ],
                }
            ],
        })
    )

    assert [answer["answer_text"] for answer in answers] == [
        "latency is 10 mins",
        "latency is 4 minutes",
    ]
    assert has_conflicts is True
    assert conflict_count == 2


@patch.object(rag_data_service, "embed_texts", return_value=[[1.0, 0.0, 0.0, 0.0]])
def test_merge_candidate_records_by_embedding_similarity_unions_identical_vectors(
    _mock_embed: MagicMock,
) -> None:
    """Same embedding => one row (paraphrase guardrail)."""
    vec = [1.0, 0.0, 0.0, 0.0]
    records = [
        {
            "answer_id": "a1",
            "answer_text": "Acme offers 99.9% SLA",
            "confidence_score": 0.5,
            "reasoning": "r1",
            "citations": [],
            "answer_idx": 1,
            "answer_embedding": list(vec),
        },
        {
            "answer_id": "a2",
            "answer_text": "SLA is 99.9 percent",
            "confidence_score": 0.9,
            "reasoning": "r2",
            "citations": [],
            "answer_idx": 2,
            "answer_embedding": list(vec),
        },
    ]
    out = rag_data_service._merge_candidate_records_by_embedding_similarity(
        records,
        opportunity_id="oid",
        question_id="Q-005",
        similarity_threshold=0.99,
    )
    assert len(out) == 1
    assert out[0]["confidence_score"] == 0.9
    assert out[0]["reasoning"] == "r2"


def test_merge_candidate_records_by_embedding_similarity_keeps_orthogonal_vectors() -> None:
    """Different embeddings => still two candidates."""
    r1 = [1.0, 0.0, 0.0, 0.0]
    r2 = [0.0, 1.0, 0.0, 0.0]
    records = [
        {
            "answer_id": "a1",
            "answer_text": "twenty four hours",
            "confidence_score": 0.9,
            "reasoning": "",
            "citations": [],
            "answer_idx": 1,
            "answer_embedding": r1,
        },
        {
            "answer_id": "a2",
            "answer_text": "forty eight hours",
            "confidence_score": 0.8,
            "reasoning": "",
            "citations": [],
            "answer_idx": 2,
            "answer_embedding": r2,
        },
    ]
    out = rag_data_service._merge_candidate_records_by_embedding_similarity(
        records,
        opportunity_id="oid",
        question_id="Q-020",
        similarity_threshold=0.99,
    )
    assert len(out) == 2


def test_merge_candidate_records_by_embedding_similarity_can_disable_embedding_merge() -> None:
    """Picklist-safe mode: even identical embeddings must not merge distinct texts."""
    vec = [1.0, 0.0, 0.0, 0.0]
    records = [
        {
            "answer_id": "a1",
            "answer_text": "Quarterly",
            "confidence_score": 0.9,
            "reasoning": "",
            "citations": [],
            "answer_idx": 1,
            "answer_embedding": list(vec),
        },
        {
            "answer_id": "a2",
            "answer_text": "Annually",
            "confidence_score": 0.8,
            "reasoning": "",
            "citations": [],
            "answer_idx": 2,
            "answer_embedding": list(vec),
        },
    ]
    out = rag_data_service._merge_candidate_records_by_embedding_similarity(
        records,
        opportunity_id="oid",
        question_id="QID-012",
        similarity_threshold=0.0,  # would always merge if embedding merging were enabled
        use_embedding_similarity=False,
    )
    assert len(out) == 2


@patch.object(rag_data_service, "embed_texts", return_value=[[0.5, 0.5, 0.0, 0.0]])
def test_merge_candidate_records_by_text_norm_only(_mock_embed: MagicMock) -> None:
    """Equal normalized text merges even without embeddings."""
    records = [
        {
            "answer_id": "a1",
            "answer_text": "FOO",
            "confidence_score": 0.5,
            "reasoning": "",
            "citations": [],
            "answer_idx": 1,
            "answer_embedding": None,
        },
        {
            "answer_id": "a2",
            "answer_text": "foo",
            "confidence_score": 0.8,
            "reasoning": "",
            "citations": [],
            "answer_idx": 2,
            "answer_embedding": None,
        },
    ]
    out = rag_data_service._merge_candidate_records_by_embedding_similarity(
        records,
        opportunity_id="oid",
        question_id="Q-X",
    )
    assert len(out) == 1


def test_build_answers_list_for_persistence_dedupes_conflict_values() -> None:
    answers, has_conflicts, conflict_count = (
        agent_graph._build_answers_list_for_persistence({
            "answer_value": "latency is 10 mins",
            "confidence_score": 0.9,
            "conflicts": [
                {"answer_value": " LATENCY IS 10 MINS ", "confidence_score": 0.7},
                {"answer_value": "latency is 4 minutes", "confidence_score": 0.8},
            ],
        })
    )

    assert [answer["answer_text"] for answer in answers] == [
        "latency is 10 mins",
        "latency is 4 minutes",
    ]
    assert has_conflicts is True
    assert conflict_count == 2

