"""
Generate 6 LLM batch files from opportunity questions master mapping CSV.
Each batch has ~23 questions (142 total). Top-to-down order.

Context flow:
  - At RUNTIME, the RAG pipeline (worker.py → rag_client.py → prompt_manager.py)
    retrieves document chunks for each question (question-based context) and
    injects them into the {context} placeholder inside the prompt template.
  - Context is thus question-based: RAG retrieval is run per question; the
    chunks returned for that question become the {context} for that question.
  - The `metadata` field in the batch file is CSV-sourced metadata (answer type,
    picklist options, artifacts, comments) — NOT the RAG context chunks.

Output format:
  ## Role (defined ONCE)
  [ROLE]
  <single role definition>

  ## Few-Shot Examples
  [EXAMPLE_1] ...

  ## Global Section Prompts (description only, no role)
  [SECTION_<key>]
  <section description>

  ## Global Sub Section Prompts (description only, no role)
  [SUB_<key>]
  <subsection description>

  ## Response Format (global, defined once)
  [RESPONSE_FORMAT]
  Respond ONLY in JSON: {"answer": "...", "conflict": false, "conflict_details": [], "sources": []}

  ---
  question N: ""
  # context = RAG chunks retrieved for this question at runtime (question-based)
  question_based_prompt: ""             # lean: question + answer_type only; response format is global above
  section_prompt: "${SECTION_<key>}"
  sub_section_prompt: "${SUB_<key>}"
  metadata: ""                          # CSV metadata (type, picklist, comments) — NOT RAG context
"""

import csv
import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_PATH = REPO_ROOT / "src" / "services" / "agent" / "prompts.py"


def _load_prompts():
    """Load prompt dicts from prompts.py without importing the full agent package."""
    spec = importlib.util.spec_from_file_location("prompts", PROMPTS_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {
        "SECTION_PROMPTS": getattr(mod, "SECTION_PROMPTS", {}),
        "SUB_SECTION_1_PROMPTS": getattr(mod, "SUB_SECTION_1_PROMPTS", {}),
        "SUB_SECTION_2_PROMPTS": getattr(mod, "SUB_SECTION_2_PROMPTS", {}),
        "SUB_SECTION_3_PROMPTS": getattr(mod, "SUB_SECTION_3_PROMPTS", {}),
        "SUB_SECTION_4_PROMPTS": getattr(mod, "SUB_SECTION_4_PROMPTS", {}),
    }


# Paths
CSV_PATH = (
    REPO_ROOT
    / "docs"
    / "OPP Questions Master Mapping - 01-09-26_Relanto(Map Opportunity Analysis).csv"
)
OUT_DIR = REPO_ROOT / "docs" / "llm_question_batches"
BATCH_SIZE = 6
TOTAL_QUESTIONS = 142
QUESTIONS_PER_BATCH = (TOTAL_QUESTIONS + BATCH_SIZE - 1) // BATCH_SIZE

# CSV section name -> prompts.py section key
SECTION_TO_KEY = {
    "Platform Discovery": "platform_discovery",
    "SASE Initial Solution Discovery": "sase_initial_discovery",
    "SASE Solution Design": "sase_solution_design",
}

_SEP = "__"

# ---------------------------------------------------------------------------
# Single role definition used once per batch (not repeated in every prompt)
# ---------------------------------------------------------------------------
ROLE_PROMPT = """\
You are a Solutions Engineer assistant helping capture opportunity requirements
for a SASE customer engagement.

Your task:
- Read the context documents provided below.
- Extract the answer to the question from the context.
- Return null if the information is not present.
- If contradictory answers exist, set conflict=true and list each value with source + excerpt.
- Respond ONLY in JSON."""

# Global response format: defined once per batch; injected when assembling the full prompt.
RESPONSE_FORMAT = (
    "Respond ONLY in JSON:\n"
    '{"answer": "<extracted value or null>", "conflict": false, "conflict_details": [], "sources": []}'
)

# ---------------------------------------------------------------------------
# Few-shot examples included once per batch to guide the LLM
# ---------------------------------------------------------------------------
FEW_SHOT_EXAMPLES = [
    {
        "label": "EXAMPLE_1 — Simple text extraction",
        "question": "What is the customer's Tenant URL?",
        "answer_type": "Text Area",
        "context": "The customer portal is accessible at https://acme.prismaaccess.com. "
        "They confirmed this during the kickoff call on Jan 15.",
        "response": '{"answer": "https://acme.prismaaccess.com", "conflict": false, "conflict_details": [], "sources": ["kickoff call Jan 15"]}',
    },
    {
        "label": "EXAMPLE_2 — Picklist selection",
        "question": "Management Platform",
        "answer_type": "Picklist",
        "context": "The customer currently manages everything through Panorama on-prem "
        "but is planning to migrate to Strata Cloud Manager next quarter.",
        "response": '{"answer": "Panorama", "conflict": false, "conflict_details": [], "sources": ["customer statement"]}',
    },
    {
        "label": "EXAMPLE_3 — Conflict detected",
        "question": "License units",
        "answer_type": "Number",
        "context": "The signed quote lists 5,000 seats. However, the SE notes from the "
        "discovery call mention 3,500 users.",
        "response": '{"answer": null, "conflict": true, "conflict_details": [{"value": "5000", "source": "signed quote", "excerpt": "The signed quote lists 5,000 seats"}, {"value": "3500", "source": "SE discovery call notes", "excerpt": "the SE notes mention 3,500 users"}], "sources": ["signed quote", "SE discovery call notes"]}',
    },
]

# ---------------------------------------------------------------------------
# Patterns used to strip the role preamble from prompts.py prompt text
# ---------------------------------------------------------------------------
_ROLE_PREFIXES = [
    "You are a Solutions Engineer assistant helping capture opportunity requirements\nfor a SASE customer engagement.\n\n",
    "You are a Solutions Engineer assistant helping capture opportunity requirements\r\nfor a SASE customer engagement.\r\n\r\n",
]

# Block to remove from global section/subsection prompts so they contain only the
# section/subsection description (no Question/Answer type/Context/Respond JSON).
_GLOBAL_PROMPT_SUFFIX = '\nQuestion: {question}\nAnswer type: {answer_type}\n\nContext:\n{context}\n\nRespond ONLY in JSON:\n{"answer": "<extracted value or null>", "conflict": false, "conflict_details": [], "sources": []}'


def clean(s: str) -> str:
    if not s or not isinstance(s, str):
        return ""
    return s.strip().replace("\r\n", " ").replace("\n", " ")


def strip_role_prefix(text: str) -> str:
    """Remove the role preamble from prompt text so it is defined only once globally."""
    if not text:
        return text
    for prefix in _ROLE_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


def strip_question_context_json_from_prompt(text: str) -> str:
    """Remove the trailing Question/Answer type/Context/Respond JSON block from prompt text."""
    if not text or not isinstance(text, str):
        return text
    if _GLOBAL_PROMPT_SUFFIX in text:
        return text[: text.index(_GLOBAL_PROMPT_SUFFIX)].rstrip()
    # Fallback: strip from "Question: {question}" to end (allow slight format variance)
    marker = "\nQuestion: {question}"
    if marker in text:
        return text[: text.index(marker)].rstrip()
    return text


def strip_prompt_to_description(text: str) -> str:
    """Strip both role prefix AND question/JSON suffix, leaving only the description."""
    return strip_question_context_json_from_prompt(strip_role_prefix(text))


def get_subsections(row: list, start: int, count: int = 4) -> list[str]:
    parts = []
    for i in range(start, min(start + count, len(row))):
        v = clean(row[i]) if i < len(row) else ""
        if v:
            parts.append(v)
    return parts


def section_key(section: str) -> str:
    return SECTION_TO_KEY.get(
        section, section.lower().replace(" ", "_").replace("&", "and")
    )


def _prompt_var_name(key: str) -> str:
    """Sanitize prompt key for use as variable name (e.g. in ${SECTION_xxx})."""
    if not key:
        return ""
    return key.replace(" ", "_").replace("&", "and")


def resolve_subsection_prompt(
    section_key_str: str,
    subs: list[str],
    prompts: dict,
) -> tuple[str, str]:
    """Return (lookup_key, prompt_text). lookup_key is empty if no subsection match."""
    parts = [section_key_str]
    parts.extend(s for s in subs if s and s != "?")
    if len(parts) >= 5:
        key = _SEP.join(parts[:5])
        if key in prompts["SUB_SECTION_4_PROMPTS"]:
            return (key, prompts["SUB_SECTION_4_PROMPTS"][key])
    if len(parts) >= 4:
        key = _SEP.join(parts[:4])
        if key in prompts["SUB_SECTION_3_PROMPTS"]:
            return (key, prompts["SUB_SECTION_3_PROMPTS"][key])
    if len(parts) >= 3:
        key = _SEP.join(parts[:3])
        if key in prompts["SUB_SECTION_2_PROMPTS"]:
            return (key, prompts["SUB_SECTION_2_PROMPTS"][key])
    if len(parts) >= 2:
        key = _SEP.join(parts[:2])
        if key in prompts["SUB_SECTION_1_PROMPTS"]:
            return (key, prompts["SUB_SECTION_1_PROMPTS"][key])
    return ("", "")


def escape_for_line(s: str) -> str:
    """Escape for use inside a single-line double-quoted string."""
    if not s:
        return ""
    return (
        s
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", " ")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def build_lean_question_prompt(question: str, answer_type: str) -> str:
    """Build a lean per-question prompt — question + answer type only.

    Response format (JSON schema) is defined globally in the batch file as [RESPONSE_FORMAT]
    and is injected once when assembling the full prompt, so the prompt is not overloaded.
    {context} is injected at runtime by the RAG pipeline.
    """
    return f"Question: {question}\nAnswer type: {answer_type or 'free_text'}"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prompts = _load_prompts()

    rows: list[list[str]] = []
    with open(CSV_PATH, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        next(reader)  # header
        for row in reader:
            if len(row) < 6:
                continue
            section = clean(row[0])
            question = clean(row[5]) if len(row) > 5 else ""
            if not section or not question:
                continue
            rows.append(row)

    rows = rows[:TOTAL_QUESTIONS]
    n = len(rows)
    print(f"Loaded {n} question rows from CSV.")

    # Global prompt registries: variable_name -> description text (role stripped)
    global_section_prompts: dict[str, str] = {}
    global_sub_prompts: dict[str, str] = {}

    # Per-question data
    question_items: list[dict] = []

    for i, row in enumerate(rows):
        q_num = i + 1
        section = clean(row[0])
        subs = get_subsections(row, 1, 4)
        question = clean(row[5]) if len(row) > 5 else ""
        answer_type = clean(row[7]) if len(row) > 7 else "free_text"
        type_val = clean(row[7]) if len(row) > 7 else ""
        picklist = clean(row[8]) if len(row) > 8 else ""
        artifacts = clean(row[9]) if len(row) > 9 else ""
        comments = clean(row[13]) if len(row) > 13 else ""
        default_ans = clean(row[16]) if len(row) > 16 else ""
        metadata_parts = [p for p in [type_val, artifacts, comments, default_ans] if p]
        if picklist and len(picklist) < 300:
            metadata_parts.append(f"Picklist/options: {picklist}")
        elif picklist:
            metadata_parts.append("Picklist/options: [see full picklist in source]")
        metadata = " | ".join(metadata_parts) if metadata_parts else ""

        sk = section_key(section)
        section_template = prompts["SECTION_PROMPTS"].get(sk, "")
        sub_key, sub_section_template = resolve_subsection_prompt(sk, subs, prompts)

        # Variable names for global prompts
        section_ref = f"SECTION_{sk}"
        sub_section_ref = f"SUB_{_prompt_var_name(sub_key)}" if sub_key else ""

        # Register global prompts — strip role AND question/JSON suffix
        if sk and section_template:
            global_section_prompts[section_ref] = strip_prompt_to_description(
                section_template
            )
        if sub_key and sub_section_template:
            global_sub_prompts[sub_section_ref] = strip_prompt_to_description(
                sub_section_template
            )

        # Lean question prompt — just question + answer_type + JSON format (no {context})
        lean_prompt = build_lean_question_prompt(question, answer_type)
        lean_prompt_flat = escape_for_line(lean_prompt)

        question_items.append({
            "q_num": q_num,
            "question": escape_for_line(question),
            "question_based_prompt": lean_prompt_flat,
            "section_ref": section_ref,
            "sub_section_ref": sub_section_ref,
            "metadata": escape_for_line(metadata),
        })

    per_batch = QUESTIONS_PER_BATCH
    for b in range(BATCH_SIZE):
        start = b * per_batch
        end = min(start + per_batch, len(question_items))
        if start >= len(question_items):
            break
        batch_items = question_items[start:end]

        # Collect variable names used in this batch
        section_refs_used = sorted({
            q["section_ref"] for q in batch_items if q["section_ref"]
        })
        sub_refs_used = sorted({
            q["sub_section_ref"] for q in batch_items if q["sub_section_ref"]
        })

        # Build output
        lines: list[str] = []
        lines.append(
            f"# LLM Batch {b + 1} — Questions {start + 1} to {end} (total {len(batch_items)})"
        )
        lines.append("")

        # ── Role (defined ONCE) ──
        lines.append("## Role")
        lines.append("")
        lines.append("[ROLE]")
        lines.append(ROLE_PROMPT)
        lines.append("")

        # ── Few-Shot Examples ──
        lines.append("## Few-Shot Examples")
        lines.append("")
        for ex in FEW_SHOT_EXAMPLES:
            lines.append(f"[{ex['label']}]")
            lines.append(f"Question: {ex['question']}")
            lines.append(f"Answer type: {ex['answer_type']}")
            lines.append(f"Context: {ex['context']}")
            lines.append(f"Response: {ex['response']}")
            lines.append("")

        # ── Global Section Prompts (role stripped) ──
        lines.append("## Global Section Prompts")
        lines.append(
            "# (Role is defined once above — these contain section descriptions only)"
        )
        lines.append("")
        for ref in section_refs_used:
            text = global_section_prompts.get(ref, "")
            lines.append(f"[{ref}]")
            lines.append(text)
            lines.append("")

        # ── Global Sub Section Prompts (role stripped) ──
        lines.append("## Global Sub Section Prompts")
        lines.append(
            "# (Role is defined once above — these contain subsection descriptions only)"
        )
        lines.append("")
        for ref in sub_refs_used:
            text = global_sub_prompts.get(ref, "")
            lines.append(f"[{ref}]")
            lines.append(text)
            lines.append("")

        # ── Response format (global, defined once; injected when assembling prompt) ──
        lines.append("## Response Format (global)")
        lines.append("")
        lines.append("[RESPONSE_FORMAT]")
        lines.append(RESPONSE_FORMAT)
        lines.append("")

        # ── Question blocks (context = RAG chunks for this question at runtime) ──
        for q in batch_items:
            section_var = f"${{{q['section_ref']}}}" if q["section_ref"] else ""
            sub_var = f"${{{q['sub_section_ref']}}}" if q["sub_section_ref"] else ""

            lines.append(f'question {q["q_num"]}: "{q["question"]}"')
            lines.append(f'question_based_prompt: "{q["question_based_prompt"]}"')
            lines.append(f'section_prompt: "{section_var}"')
            lines.append(f'sub_section_prompt: "{sub_var}"')
            lines.append(f'metadata: "{q["metadata"]}"')
            lines.append("")

        out_path = OUT_DIR / f"llm_batch_{b + 1}_questions_{start + 1}_to_{end}.txt"
        out_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        print(
            f"Wrote {out_path.name} ({len(batch_items)} questions, {len(section_refs_used)} section vars, {len(sub_refs_used)} subsection vars)."
        )

    print("Done.")


if __name__ == "__main__":
    main()
