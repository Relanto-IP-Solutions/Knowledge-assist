from __future__ import annotations

from datetime import UTC, datetime

import pytest

import src.apis.routes.opportunity_routes as opportunity_routes


def test__find_first_object_with_key__finds_first_nested_dict_with_scalar_key() -> None:
    obj = {
        "outer": [
            {"q_id": {"nested": "nope"}},
            {"x": 1, "inner": {"q_id": "Q1", "answer_id": "A1"}},
        ]
    }
    found = opportunity_routes._find_first_object_with_key(obj, "q_id")
    assert found is not None
    assert found["q_id"] == "Q1"
    assert found["answer_id"] == "A1"


def test__find_first_object_with_key__returns_none_when_not_found() -> None:
    assert opportunity_routes._find_first_object_with_key({"a": 1}, "q_id") is None


def test__find_all_objects_with_key__collects_only_valid_q_updates_and_respects_updates_list_rule() -> None:
    body = {
        "q_id": "STALE_ROOT",
        "answer_id": "STALE_ANSWER",
        "updates": [
            {"q_id": "Q1", "answer_id": "A1"},
            {"q_id": "Q2", "conflict_id": "C2", "conflict_answer_id": "A2"},
            {"q_id": "Q3"},  # missing answer_id / conflict ids => not a q-update
        ],
    }
    found = opportunity_routes._find_all_objects_with_key(body, "q_id")
    # Root is excluded because it has a non-empty updates list.
    assert [d["q_id"] for d in found] == ["Q1", "Q2"]


def test__find_all_objects_with_key__ignores_non_scalar_q_id() -> None:
    body = {"updates": [{"q_id": {"x": 1}, "answer_id": "A1"}, {"q_id": ["Q"], "answer_id": "A2"}]}
    assert opportunity_routes._find_all_objects_with_key(body, "q_id") == []


@pytest.mark.parametrize(
    ("val", "expected"),
    [
        (None, None),
        ("", None),
        ("  ", None),
        ("null", None),
        (" NULL ", None),
        (0, "0"),
        (False, "False"),
        ("abc", "abc"),
        ("  abc  ", "abc"),
    ],
)
def test__normalize_optional_str__handles_nullish_and_coerces(val, expected) -> None:
    assert opportunity_routes._normalize_optional_str(val) == expected


@pytest.mark.parametrize(
    ("status_val", "default", "expected"),
    [
        (True, "inactive", "active"),
        (False, "active", "inactive"),
        ("active", "inactive", "active"),
        ("INACTIVE", "active", "inactive"),
        ("true", "inactive", "active"),
        ("0", "active", "inactive"),
        ("yes", "inactive", "active"),
        ("no", "active", "inactive"),
        ("unknown", "active", "active"),
        (None, "inactive", "inactive"),
    ],
)
def test__coerce_answers_status__coerces_boolean_and_strings(status_val, default, expected: str) -> None:
    assert opportunity_routes._coerce_answers_status(status_val, default=default) == expected


def test__should_use_flat_save_or_resolve__false_when_not_dict() -> None:
    assert opportunity_routes._should_use_flat_save_or_resolve(["x"]) is False


def test__should_use_flat_save_or_resolve__false_when_no_question_id() -> None:
    assert opportunity_routes._should_use_flat_save_or_resolve({"q_id": "Q1"}) is False


def test__should_use_flat_save_or_resolve__false_when_updates_nonempty() -> None:
    assert (
        opportunity_routes._should_use_flat_save_or_resolve(
            {"question_id": "Q1", "updates": [{"q_id": "Q2", "answer_id": "A"}]}
        )
        is False
    )


def test__should_use_flat_save_or_resolve__true_when_selected_answer_id_present() -> None:
    assert (
        opportunity_routes._should_use_flat_save_or_resolve(
            {"question_id": "Q1", "selected_answer_id": "A1"}
        )
        is True
    )


def test__should_use_flat_save_or_resolve__true_when_answer_id_present() -> None:
    assert (
        opportunity_routes._should_use_flat_save_or_resolve({"question_id": "Q1", "answer_id": "A1"})
        is True
    )


def test__should_use_flat_save_or_resolve__true_when_answers_present() -> None:
    assert (
        opportunity_routes._should_use_flat_save_or_resolve({"question_id": "Q1", "answers": [{"value": "x", "confidence": 0.9}]})
        is True
    )


def test__should_use_flat_save_or_resolve__true_when_action_present() -> None:
    assert (
        opportunity_routes._should_use_flat_save_or_resolve({"question_id": "Q1", "action": "INSERT"})
        is True
    )

