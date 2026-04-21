"""Smoke test: run answer generation (or load prior output) and summarize typed answers.

Shows, for each question, the DB ``answer_type`` (picklist, multi-select, integer,
text, …), whether picklist options exist, the runtime type of ``answer`` / ``answer_value``,
and a short preview. Use this to verify picklist → string, integer → number, multi-select → list.

Usage
-----
  # Full run (needs retrieval JSON + DB for field definitions):
  uv run python -m scripts.tests_integration.smoke_answer_types_summary oid0003

  # Same, skip Vertex prompt cache:
  uv run python -m scripts.tests_integration.smoke_answer_types_summary oid0003 --no-cache

  # Analyze an existing pipeline output (no agent rerun):
  uv run python -m scripts.tests_integration.smoke_answer_types_summary --from-json data/output/answer_gen_oid0003_20260401_130635.json

  # Only rows where DB says picklist:
  uv run python -m scripts.tests_integration.smoke_answer_types_summary oid0003 --filter-type picklist

Requires
--------
  configs/.env and configs/secrets/.env for GCP/DB when running the pipeline or loading field metadata.
  Retrieval file: ``data/output/smoke_retrieval_{opportunity_id}.json`` when not using ``--from-json``.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_DIR = _REPO_ROOT / "data" / "output"

# Load env before importing app code
for _ef in (
    _REPO_ROOT / "configs" / ".env",
    _REPO_ROOT / "configs" / "secrets" / ".env",
):
    if _ef.exists():
        try:
            from dotenv import load_dotenv

            load_dotenv(_ef, override=True)
        except ImportError:
            pass


def _value_kind(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int) and not isinstance(v, bool):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    return type(v).__name__


def _preview(v: Any, max_len: int = 80) -> str:
    if v is None:
        return ""
    s = json.dumps(v, ensure_ascii=False) if isinstance(v, list) else str(v)
    s = s.replace("\n", " ")
    return s if len(s) <= max_len else s[: max_len - 3] + "..."


def _load_field_metadata() -> dict[str, dict[str, Any]]:
    """q_id -> answer_type, option_count, options_sample."""
    from src.services.agent.batch_registry import get_batches
    from src.services.agent.field_loader import load_batch_fields

    out: dict[str, dict[str, Any]] = {}
    for b in get_batches():
        for f in load_batch_fields(b.batch_id):
            opts = f.options or []
            out[f.q_id] = {
                "answer_type": f.answer_type,
                "option_count": len(opts),
                "options_sample": opts[:8],
                "batch_id": f.batch_id,
            }
    return out


def _iter_answer_rows(
    result: dict[str, Any],
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Normalize pipeline dict or list-shaped answers."""
    answers = result.get("answers")
    if answers is None:
        return
    if isinstance(answers, dict):
        for qid, row in answers.items():
            if isinstance(row, dict):
                yield str(qid), row
        return
    if isinstance(answers, list):
        for row in answers:
            if not isinstance(row, dict):
                continue
            qid = row.get("question_id") or row.get("q_id") or ""
            if qid:
                yield str(qid), row


def _answer_value_from_row(row: dict[str, Any]) -> Any:
    if "answer" in row:
        return row.get("answer")
    return row.get("answer_value")


def _conflict_from_row(row: dict[str, Any]) -> bool:
    return row.get("conflict") is True or bool(row.get("conflicts"))


def _run_pipeline(opp_id: str, no_cache: bool) -> dict[str, Any]:
    retrieval_file = _OUTPUT_DIR / f"smoke_retrieval_{opp_id.replace('/', '_')}.json"
    if not retrieval_file.exists():
        raise FileNotFoundError(
            f"Retrieval file not found: {retrieval_file}\n"
            f"Run: uv run python scripts/tests_integration/smoke_retrieval.py {opp_id}"
        )
    body = json.loads(retrieval_file.read_text(encoding="utf-8"))
    from src.services.pipelines.agent_pipeline import AnswerGenerationPipeline

    pipeline = AnswerGenerationPipeline(use_cache=not no_cache)
    return pipeline.run(body)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize typed answers (picklist / integer / text / multi-select) for smoke testing."
    )
    parser.add_argument(
        "opportunity_id",
        nargs="?",
        help="Opportunity id when running the pipeline (e.g. oid0003). Omit if --from-json only.",
    )
    parser.add_argument(
        "--from-json",
        type=Path,
        help="Skip pipeline; load this answer_gen / pipeline JSON instead.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip Vertex prompt cache when running the pipeline.",
    )
    parser.add_argument(
        "--filter-type",
        type=str,
        default="",
        help="Only show questions whose DB answer_type equals this (e.g. picklist, integer, text, multi-select).",
    )
    parser.add_argument(
        "--write-summary-json",
        action="store_true",
        help="Write data/output/smoke_answer_types_summary_<opp>_<ts>.json with one row per question.",
    )
    args = parser.parse_args()

    if args.from_json:
        path = Path(args.from_json)
        if not path.is_file():
            path = _OUTPUT_DIR / args.from_json
        if not path.is_file():
            raise SystemExit(f"File not found: {args.from_json}")
        result = json.loads(path.read_text(encoding="utf-8"))
        opp_id = result.get("_meta", {}).get("opportunity_id") or result.get(
            "opportunity_id", "unknown"
        )
    else:
        if not args.opportunity_id:
            raise SystemExit("Provide opportunity_id or --from-json PATH")
        opp_id = args.opportunity_id
        print(f"Running AnswerGenerationPipeline for {opp_id} ...")
        result = _run_pipeline(opp_id, args.no_cache)

    meta = result.get("_meta", {})
    field_meta = _load_field_metadata()

    rows_out: list[dict[str, Any]] = []
    print()
    print(
        f"{'q_id':<12} {'db_type':<14} {'opts':>4} {'value_kind':<10} {'conflict':<8} preview"
    )
    print("-" * 100)

    filter_t = (args.filter_type or "").strip().lower()

    for qid, ans_row in sorted(_iter_answer_rows(result), key=lambda x: x[0]):
        fm = field_meta.get(qid, {})
        db_type = (fm.get("answer_type") or "?").lower()
        if filter_t and db_type != filter_t:
            continue

        val = _answer_value_from_row(ans_row)
        kind = _value_kind(val)
        conflict = _conflict_from_row(ans_row)
        opt_n = int(fm.get("option_count") or 0)

        preview = _preview(val)
        err = ans_row.get("error")
        if err:
            preview = f"ERROR: {err}"

        print(
            f"{qid:<12} {db_type:<14} {opt_n:>4} {kind:<10} {conflict!s:<8} {preview}"
        )

        rows_out.append({
            "question_id": qid,
            "answer_type_db": fm.get("answer_type"),
            "option_count": opt_n,
            "options_sample": fm.get("options_sample"),
            "batch_id": fm.get("batch_id"),
            "value_kind": kind,
            "answer_value": val,
            "conflict": conflict,
            "error": ans_row.get("error"),
        })

    print("-" * 100)
    print(f"Rows shown: {len(rows_out)}  |  opportunity_id: {opp_id}")
    if meta:
        print(
            f"Pipeline meta: elapsed={meta.get('elapsed_seconds')}s  errors={meta.get('failed_question_ids', [])}"
        )

    if args.write_summary_json:
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = (
            _OUTPUT_DIR
            / f"smoke_answer_types_summary_{str(opp_id).replace('/', '_')}_{ts}.json"
        )
        out_path.write_text(
            json.dumps(
                {
                    "opportunity_id": opp_id,
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "meta": meta,
                    "rows": rows_out,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
