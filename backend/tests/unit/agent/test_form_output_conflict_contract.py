from __future__ import annotations


from src.services.agent.form_output import build_full_answers_payload, norm_val_str


def _conflict_values(entry: dict) -> set[str]:
    return {norm_val_str(c.get("answer_value")) for c in (entry.get("conflicts") or [])}


def test_form_output_conflict_sets_answer_null_and_includes_selected_value_in_conflicts() -> None:
    # Simulate QID-012 case: conflict_details contains only "Quarterly", but the selected
    # value is "Annually". Contract: answer_value must be null and BOTH values must be in conflicts[].
    opportunity_id = "oid_test"
    final_answers = {
        "QID-012": {
            "answer": "Annually",
            "confidence": 0.9,
            "answer_basis": [
                {
                    "source": "doc.txt",
                    "excerpt": "Annual external ...",
                    "source_type": "gdrive_doc",
                    "chunk_id": "chunk_1",
                    "confidence_score": 0.5,
                    "rerank_score": 0.1,
                    "source_file": "doc.txt",
                }
            ],
        }
    }
    candidate_answers = [
        {
            "question_id": "QID-012",
            "agent_id": "agent_x",
            "candidate_answer": None,
            "confidence": 0.0,
            "sources": [],
            "conflict": True,
            "conflict_details": [
                {
                    "value": "Quarterly",
                    "source": "doc.txt",
                    "excerpt": "Annual external ..., quarterly internal ...",
                    "source_type": "gdrive_doc",
                    "confidence_score": 0.6,
                    "source_file": "doc.txt",
                    "chunk_id": "chunk_1",
                    "rerank_score": 0.1,
                }
            ],
        }
    ]

    payload = build_full_answers_payload(opportunity_id, final_answers, candidate_answers, {})
    answers = {a["question_id"]: a for a in payload.get("answers", [])}
    q = answers["QID-012"]

    assert q["answer_value"] is None
    assert _conflict_values(q) == {norm_val_str("Quarterly"), norm_val_str("Annually")}

