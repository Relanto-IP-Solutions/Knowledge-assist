"""Run answer generation for one question_id using saved retrieval JSON.

Use this to debug citations and answers without running the full opportunity.

Usage:
    uv run python -m scripts.tests_integration.smoke_single_question_answer \\
        oid0003 QID-001

    uv run python -m scripts.tests_integration.smoke_single_question_answer \\
        opp_id_1 QID-001 --no-cache

Requires:
    data/output/smoke_retrieval_{opportunity_id}.json (from smoke_retrieval.py),
    or pass --retrieval-file path/to.json

The filename is whatever you used when running smoke_retrieval.py, e.g.
``smoke_retrieval_opp_id_0003.json`` if you ran ``... smoke_retrieval.py opp_id_0003``.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from src.services.pipelines.agent_pipeline import (
    AnswerGenerationPipeline,
    _build_extract_payload,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_DIR = _REPO_ROOT / "data" / "output"


def _norm(s: str) -> str:
    return "".join(c for c in s.lower() if c.isalnum())


def resolve_retrieval_json(opp_id: str, explicit: Path | None) -> Path | None:
    """Resolve path to retrieval JSON: explicit path, default name, or match by opportunity_id."""
    if explicit is not None:
        p = explicit if explicit.is_absolute() else (_REPO_ROOT / explicit).resolve()
        return p if p.exists() else None

    primary = _OUTPUT_DIR / f"smoke_retrieval_{opp_id.replace('/', '_')}.json"
    if primary.exists():
        return primary

    # Same logical id may have been saved under another string (e.g. opp_id_0003 vs oid0003).
    if not _OUTPUT_DIR.is_dir():
        return None
    candidates = sorted(_OUTPUT_DIR.glob("smoke_retrieval_*.json"))
    n_opp = _norm(opp_id)
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        oid = str(data.get("opportunity_id") or "")
        if oid == opp_id or _norm(oid) == n_opp:
            return path
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Answer generation for a single question (filtered retrieval body)."
    )
    parser.add_argument(
        "opportunity_id",
        help="Opportunity id (must match smoke_retrieval_{id}.json filename).",
    )
    parser.add_argument(
        "question_id",
        help="Canonical q_id key in retrievals, e.g. QID-001.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip Vertex AI prompt caching.",
    )
    parser.add_argument(
        "--retrieval-file",
        type=Path,
        default=None,
        help="Explicit path to retrieval JSON (overrides default smoke_retrieval_{opp}.json).",
    )
    args = parser.parse_args()

    opp_id = args.opportunity_id
    qid = args.question_id

    if args.retrieval_file is not None:
        explicit = (
            args.retrieval_file
            if args.retrieval_file.is_absolute()
            else (_REPO_ROOT / args.retrieval_file).resolve()
        )
        if not explicit.exists():
            print(f"ERROR: --retrieval-file not found: {explicit}")
            return
        retrieval_file = explicit
    else:
        retrieval_file = resolve_retrieval_json(opp_id, None)

    if retrieval_file is None:
        expected = _OUTPUT_DIR / f"smoke_retrieval_{opp_id.replace('/', '_')}.json"
        print(f"ERROR: Retrieval file not found: {expected}")
        if _OUTPUT_DIR.is_dir():
            found = sorted(_OUTPUT_DIR.glob("smoke_retrieval_*.json"))
            if found:
                print("  Existing smoke_retrieval_*.json files in data/output:")
                for p in found[:25]:
                    print(f"    {p.name}")
                if len(found) > 25:
                    print(f"    ... and {len(found) - 25} more")
        print(
            f"  Generate one: uv run python scripts/tests_integration/smoke_retrieval.py {opp_id}"
        )
        print(
            "  Or point at a file: --retrieval-file data/output/smoke_retrieval_<your_run>.json"
        )
        return

    if args.retrieval_file is None and retrieval_file.name != (
        f"smoke_retrieval_{opp_id.replace('/', '_')}.json"
    ):
        print(
            f"Using retrieval file (matched opportunity_id in JSON): {retrieval_file.name}"
        )
        print()

    full = json.loads(retrieval_file.read_text(encoding="utf-8"))
    retrievals = full.get("retrievals") or {}
    if qid not in retrievals:
        keys = sorted(retrievals.keys())
        print(f"ERROR: question_id {qid!r} not in retrievals.")
        print(
            f"  Available keys ({len(keys)}): {keys[:30]}{'...' if len(keys) > 30 else ''}"
        )
        return

    chunks = retrievals[qid]
    if not isinstance(chunks, list) or not chunks:
        print(f"WARNING: No chunks for {qid}; pipeline may return empty context.")

    body = {
        "opportunity_id": full.get("opportunity_id") or opp_id,
        "retrievals": {qid: chunks},
    }

    print(f"Opportunity: {body['opportunity_id']}")
    print(f"Question:    {qid}")
    print(f"Chunks:      {len(chunks) if isinstance(chunks, list) else 0}")
    print()

    pipeline = AnswerGenerationPipeline(use_cache=not args.no_cache)
    result = pipeline.run(body)

    answers = result.get("answers") or {}
    meta = result.get("_meta") or {}
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_opp = opp_id.replace("/", "_")
    raw_path = (
        _OUTPUT_DIR / f"answer_gen_single_{safe_opp}_{qid.replace('/', '_')}_{ts}.json"
    )
    raw_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    extract_full = _build_extract_payload(opp_id, answers)
    extract_rows = [
        r
        for r in (extract_full.get("answers") or [])
        if isinstance(r, dict) and r.get("question_id") == qid
    ]
    response_payload = {
        "opportunity_id": extract_full.get("opportunity_id") or opp_id,
        "answers": extract_rows,
    }
    response_path = (
        _OUTPUT_DIR / f"response_{safe_opp}_{qid.replace('/', '_')}_{ts}.json"
    )
    response_path.write_text(
        json.dumps(response_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("--- Same format as opp_id_1_response.json (one question) ---")
    print(json.dumps(response_payload, indent=2, ensure_ascii=False))
    print()
    print(f"Response JSON (extract shape): {response_path}")
    print(f"Raw pipeline JSON:             {raw_path}")
    print(
        f"Elapsed: {meta.get('elapsed_seconds')}s  errors: {meta.get('failed_question_ids', [])}"
    )


if __name__ == "__main__":
    main()
