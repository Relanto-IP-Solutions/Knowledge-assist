"""Smoke script — inspect the prompt and response schema for one SASE opportunity extraction batch.

Prints the fully-rendered system prompt, a sample user prompt, and the
JSON schema that gets passed to Vertex AI as ``response_schema``, without
making any LLM calls.

Usage
-----
    uv run python -m scripts.tests_integration.smoke_agent_batch_prompt               # defaults to batch 1, all sections
    uv run python -m scripts.tests_integration.smoke_agent_batch_prompt --batch 3
    uv run python -m scripts.tests_integration.smoke_agent_batch_prompt --batch 2 --section schema
    uv run python -m scripts.tests_integration.smoke_agent_batch_prompt --section all

Sections
--------
    system   — system prompt sent to the LLM (the extraction rules + field table)
    user     — user-turn prompt (context placeholder + extraction instruction)
    schema   — JSON schema passed as response_schema for constrained decoding
    all      — print all three (default)
"""

from __future__ import annotations

import argparse
import json
import textwrap

from src.services.agent.batch_registry import BatchDefinition, get_batches
from src.services.agent.field_loader import (
    get_field_count,
    get_question_range,
    load_batch_fields,
)
from src.services.agent.prompt_builder import build_system_prompt, build_user_prompt


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_DIVIDER = "=" * 80
_SUBDIV = "-" * 80


def _header(title: str) -> str:
    padding = (_DIVIDER.__len__() - len(title) - 2) // 2
    return f"\n{_DIVIDER}\n{'=' * padding} {title} {'=' * padding}\n{_DIVIDER}\n"


def _wrap(text: str, width: int = 100) -> str:
    """Wrap long lines for readability without modifying code/JSON blocks."""
    return text  # keep raw so JSON / prompt tables stay intact


def _print_section(label: str, content: str) -> None:
    print(_header(label))
    print(content)
    print()


# ---------------------------------------------------------------------------
# Per-section printers
# ---------------------------------------------------------------------------


def show_system_prompt(batch_def: BatchDefinition) -> None:
    system = build_system_prompt(batch_def)
    _print_section(
        f"SYSTEM PROMPT — {batch_def.label} ({get_field_count(batch_def.batch_id)} fields)",
        system,
    )


def show_user_prompt(batch_def: BatchDefinition) -> None:
    q_first, q_last = get_question_range(batch_def.batch_id)
    dummy_context = textwrap.dedent(f"""\
        ### [Source: acme_discovery_call_2026-01-15.vtt | Type: transcript | Question: {q_first}]
        We are currently using Cisco AnyConnect for remote access. About 3000 users connect daily.
        No MFA is enforced on the VPN today.

        ### [Source: acme_sow_v2.pdf | Type: document | Question: {q_first}]
        The engagement will be delivered by the Professional Services team. Delivery Assurance is included.

        ### [Source: slack://channel/opp-review | Type: slack | Question: {q_last}]
        Leadership confirmed this is in scope for a POV. Full SASE deployment expected in Q3.
    """).strip()

    user = build_user_prompt(batch_def.batch_id, dummy_context)
    _print_section(
        f"USER PROMPT — {batch_def.label} (dummy context, 3 chunks)",
        user,
    )


def show_response_schema(batch_def: BatchDefinition) -> None:
    schema_class = batch_def.schema_class
    schema_json = json.dumps(
        schema_class.model_json_schema(), indent=2, ensure_ascii=False
    )

    # Count fields to give a quick summary.
    fields = load_batch_fields(batch_def.batch_id)
    type_counts: dict[str, int] = {}
    for f in fields:
        type_counts[f.answer_type] = type_counts.get(f.answer_type, 0) + 1

    summary_lines = [
        f"Schema class : {schema_class.__name__}",
        f"Total fields : {len(fields)} ({fields[0].q_id}–{fields[-1].q_id})",
        "Field types  : "
        + ", ".join(f"{t}={n}" for t, n in sorted(type_counts.items())),
        "",
    ]
    _print_section(
        f"RESPONSE SCHEMA — {batch_def.label}",
        "\n".join(summary_lines) + schema_json,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect the prompt and response schema for an opportunity extraction batch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=1,
        choices=range(1, 7),
        metavar="{1..6}",
        help="Batch order number to inspect (default: 1).",
    )
    parser.add_argument(
        "--section",
        choices=["system", "user", "schema", "all"],
        default="all",
        help="Which section to print (default: all).",
    )
    args = parser.parse_args()

    batches = get_batches()
    batch_def = next(b for b in batches if b.batch_order == args.batch)

    print(f"\nBatch {batch_def.number}: {batch_def.label}")
    print(f"Schema class : {batch_def.schema_class.__name__}")
    print(f"Context file : {batch_def.context_file}")
    print(f"Few-shot     : {batch_def.include_few_shot}")
    print(_SUBDIV)

    section = args.section
    if section in ("system", "all"):
        show_system_prompt(batch_def)
    if section in ("user", "all"):
        show_user_prompt(batch_def)
    if section in ("schema", "all"):
        show_response_schema(batch_def)


if __name__ == "__main__":
    main()
