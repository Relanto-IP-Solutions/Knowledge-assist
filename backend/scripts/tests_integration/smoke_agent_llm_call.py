"""Smoke script — make one real LLM call for a single SASE opportunity extraction batch.

Loads context from the batch's dummy-chunks file (if configured), builds the
prompts, calls Vertex AI Gemini, validates the response against the Pydantic
schema, and prints a results summary alongside the full raw JSON response.

Usage
-----
    uv run python -m scripts.tests_integration.smoke_agent_llm_call               # batch 1 (default)
    uv run python -m scripts.tests_integration.smoke_agent_llm_call --batch 3
    uv run python -m scripts.tests_integration.smoke_agent_llm_call --batch 2 --output data/output/smoke_b2.json

Context source
--------------
Context is loaded from the static dummy-chunk file registered for the batch in
``batch_registry.py`` (e.g. ``data/context/sase_batch1_dummy_chunks.json``).
Each file simulates the output of a RAG retrieval step — one entry per question
field, each with 2–4 document chunks from placeholder sources.
These files stand in for a live Vertex AI RAG corpus until retrieval is integrated.
If no context file is configured for the batch, the LLM call will run with
empty context.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

from src.services.agent.batch_registry import BatchDefinition, get_batches
from src.services.agent.field_loader import load_batch_fields
from src.services.agent.prompt_builder import build_system_prompt, build_user_prompt
from src.services.agent.workers import load_chunks_from_file, render_context_text
from src.services.llm.client import LLMClient
from src.utils.logger import get_logger


logger = get_logger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "context"
_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "output"
_DIVIDER = "=" * 80
_SUBDIV = "-" * 80


def _write_json_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Results printer
# ---------------------------------------------------------------------------


def _print_summary(batch_def: BatchDefinition, result: object, elapsed: float) -> None:
    """Print a human-readable summary of the LLM response."""
    fields = load_batch_fields(batch_def.batch_id)
    field_map = {f.field_key: f for f in fields}

    data: dict = result.model_dump()  # type: ignore[attr-defined]

    answered, nulled, conflicted = [], [], []
    for field_key, val in data.items():
        if field_key not in field_map:
            continue
        if val.get("conflict"):
            conflicted.append(field_key)
        elif val.get("answer") is not None:
            answered.append(field_key)
        else:
            nulled.append(field_key)

    total = len(fields)
    print(f"\n{_DIVIDER}")
    print(f" RESULTS — {batch_def.label}  ({elapsed:.1f}s)")
    print(_DIVIDER)
    print(f"  Answered  : {len(answered):3d} / {total}")
    print(f"  Null      : {len(nulled):3d} / {total}")
    print(f"  Conflict  : {len(conflicted):3d} / {total}")
    print(_SUBDIV)

    if answered:
        print("\n  Answered fields:")
        for field_key in answered:
            field_def = field_map.get(field_key)
            label = field_def.question_label if field_def else field_key
            answer = data[field_key].get("answer")
            sources = data[field_key].get("sources", [])
            answer_str = str(answer)
            if len(answer_str) > 80:
                answer_str = answer_str[:77] + "..."
            print(f"    {label:<60s}  {answer_str}")
            if sources:
                print(f"      sources: {', '.join(sources)}")

    if conflicted:
        print("\n  Conflicted fields:")
        for field_key in conflicted:
            field_def = field_map.get(field_key)
            label = field_def.question_label if field_def else field_key
            reason = data[field_key].get("conflict_reason") or "(no reason)"
            print(f"    {label:<60s}  CONFLICT — {reason}")

    if nulled:
        print(f"\n  Null fields ({len(nulled)}):")
        null_labels = []
        for field_key in nulled:
            fd = field_map.get(field_key)
            null_labels.append(fd.question_label if fd else field_key)
        print("    " + ", ".join(null_labels))

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run(batch_order: int, output_path: Path | None) -> None:
    batches = get_batches()
    batch_def = next(b for b in batches if b.batch_order == batch_order)

    fields = load_batch_fields(batch_def.batch_id)
    q_ids = {f.q_id for f in fields}

    print(f"\nBatch        : {batch_def.label}")
    print(f"Batch ID     : {batch_def.batch_id}")
    print(f"Schema class : {batch_def.schema_class.__name__}")
    print(f"Context file : {batch_def.context_file or '(none)'}")
    print("Context size : ", end="", flush=True)

    if batch_def.context_file:
        context_path = _DATA_DIR / batch_def.context_file
        batch_chunks = load_chunks_from_file(context_path, q_ids)
        context_text = render_context_text(batch_chunks)
    else:
        context_text = ""

    print(f"{len(context_text):,} chars")

    system_prompt = build_system_prompt(batch_def)
    user_prompt = build_user_prompt(batch_def.batch_id, context_text)
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    print(f"System prompt: {len(system_prompt):,} chars")
    print(f"User prompt  : {len(user_prompt):,} chars")
    print(f"Total tokens ~: {len(full_prompt) // 4:,} (rough estimate)")
    print(_SUBDIV)
    print("Calling Vertex AI Gemini... ", end="", flush=True)

    llm = LLMClient()
    start = asyncio.get_event_loop().time()

    result = await llm.generate_async(
        prompt=full_prompt,
        schema=batch_def.schema_class,
        response_schema=batch_def.schema_class,
    )

    elapsed = asyncio.get_event_loop().time() - start
    print(f"done ({elapsed:.1f}s)")

    _print_summary(batch_def, result, elapsed)

    raw_json = result.model_dump_json(indent=2)  # type: ignore[attr-defined]

    if output_path:
        await asyncio.to_thread(_write_json_file, output_path, raw_json)
        print(f"Full response written to: {output_path}")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = _OUTPUT_DIR / f"smoke_batch{batch_order}_{timestamp}.json"
        await asyncio.to_thread(_write_json_file, default_path, raw_json)
        print(f"Full response written to: {default_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Make one real LLM call for a SASE opportunity extraction batch and print results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=1,
        choices=range(1, 7),
        metavar="{1..6}",
        help="Batch order number to run (default: 1).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to write the full JSON response (default: data/output/smoke_batch{N}_<timestamp>.json).",
    )
    args = parser.parse_args()
    asyncio.run(run(batch_order=args.batch, output_path=args.output))


if __name__ == "__main__":
    main()
