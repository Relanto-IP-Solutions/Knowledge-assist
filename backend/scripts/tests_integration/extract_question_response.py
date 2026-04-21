"""Slice a full opportunity response JSON to one question_id — same schema as the source file.

Input files use the extract / ``opp_id_1_response.json`` shape::

    { "opportunity_id": "...", "answers": [ { "question_id", "answer_value", ... }, ... ] }

Output is identical structure with ``answers`` containing a single element.

Usage:
    uv run python -m scripts.tests_integration.extract_question_response \\
        data/output/opp_id_1_response.json QID-001

    uv run python -m scripts.tests_integration.extract_question_response \\
        data/output/opp_id_1_response.json QID-001 -o data/output/qid001_only.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract one question from a response JSON (same format as opp_id_1_response.json)."
    )
    parser.add_argument(
        "response_json",
        type=Path,
        help="Path to full response file (opportunity_id + answers array).",
    )
    parser.add_argument(
        "question_id",
        help="question_id to keep (e.g. QID-001).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write JSON here; default: print to stdout.",
    )
    args = parser.parse_args()

    path = (
        args.response_json
        if args.response_json.is_absolute()
        else _REPO_ROOT / args.response_json
    )
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(path.read_text(encoding="utf-8"))
    answers = data.get("answers")
    if not isinstance(answers, list):
        print("ERROR: expected top-level 'answers' array.", file=sys.stderr)
        sys.exit(1)

    qid = args.question_id
    found = None
    for row in answers:
        if isinstance(row, dict) and row.get("question_id") == qid:
            found = row
            break

    if found is None:
        ids = [r.get("question_id") for r in answers if isinstance(r, dict)]
        print(f"ERROR: no answer for question_id={qid!r}.", file=sys.stderr)
        print(
            f"  Available ({len(ids)}): {ids[:40]}{'...' if len(ids) > 40 else ''}",
            file=sys.stderr,
        )
        sys.exit(1)

    out = {
        "opportunity_id": data.get("opportunity_id", ""),
        "answers": [found],
    }
    text = json.dumps(out, indent=2, ensure_ascii=False)

    if args.output is not None:
        outp = args.output if args.output.is_absolute() else _REPO_ROOT / args.output
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(text, encoding="utf-8")
        print(str(outp))
    else:
        print(text)


if __name__ == "__main__":
    main()
