"""Prompt construction for SASE opportunities Q&A extraction batches.

System prompts are built from ``BatchDefinition`` objects (``batch_registry.py``)
and ``FieldDefinition`` objects loaded from PostgreSQL (``field_loader.py``).
The DB is the single source of truth for question text, picklist options, and prompts:
- Section-level prompt: ``sase_batches.section_level_prompt`` → "## Section instructions" block.
- Question-level prompt: ``sase_questions.question_prompt`` → ``prompt`` key in each field JSON.
Worker agents receive these via the system prompt built here.

Usage
-----
    from src.services.agent.prompt_builder import build_system_prompt, build_user_prompt
    from src.services.agent.batch_registry import get_batches

    batch_def = get_batches()[0]
    system = build_system_prompt(batch_def)
    user   = build_user_prompt(batch_def.batch_id, context_string)
"""

from __future__ import annotations

import json

from src.services.agent.field_loader import FieldDefinition, load_batch_fields


_prompt_builder: PromptBuilder | None = None

# ---------------------------------------------------------------------------
# Shared prompt components — constant across all batches
# ---------------------------------------------------------------------------

_AGENT_INTRO = (
    "You are a Solutions Engineer assistant. Your job is to capture opportunity "
    "requirements for a SASE customer engagement by extracting structured "
    "information from customer-facing documents (call transcripts, discovery notes, "
    "emails, ASR reports, etc.)."
)

_EXTRACTION_RULES = """\
## Extraction rules

1. Extract only what is explicitly stated. Do not infer, assume, or generalise.
2. If a field is not addressed in the context, set `answer` to null.
3. CANONICALIZE FIRST (always) — before writing ANY value anywhere in your response \
(in `answer`, in `conflict_details[].value`, or anywhere else), convert raw mentions into \
canonical values so you do NOT create duplicate candidates.
   - Canonicalization means: remove surface-form differences that do not change meaning \
and keep ONE best representation (usually the most explicit / complete).
   - Apply canonicalization to BOTH `answer` and every `conflict_details[].value`.
   - After canonicalizing across all sources, compute how many DISTINCT canonical values remain:
     - ONE distinct value → `conflict=false`, set `answer` to that value.
     - TWO OR MORE distinct values → `conflict=true`, set `answer=null`, and write EXACTLY \
       one `conflict_details` entry per distinct canonical value (no duplicates/paraphrases).

   General canonicalization patterns (examples):
   - Same number + same unit expressed differently → ONE value:
     "24" = "24h" = "24 hours" = "within 24 hours" → "24 hours"
   - Same range expressed differently → ONE value:
     "24-48" = "24 to 48 hours" = "24–48 hours" → "24-48 hours"
   - Same percentage expressed differently → ONE value:
     "99.9" = "99.9%" = "99.9 percent" → "99.9%"
   - Case/format noise does not create new values:
     "annually" = "Annually" (for picklists: output MUST match an option exactly)

   Keep values separate (these are genuinely different facts and MUST be conflicts):
   - Different numbers or ranges: "24 hours" vs "48 hours" vs "24-48 hours"
   - Different frequencies: "Quarterly" vs "Annually" vs "Continuous"
   - Different vendors/products: "Zscaler" vs "Palo Alto"
   - Yes vs No: "in scope" vs "not in scope"
   - Any two distinct picklist option values

   Picklist mapping example:
   Options: Quarterly, Semi-Annually, Annually, Continuous
   Text: "annual external testing and quarterly internal testing"
   → conflict with values "Annually" and "Quarterly" (exact option strings); do NOT combine \
     into a descriptive sentence.
4. For picklist fields:
   - The `answer` MUST be one of the exact option strings listed in ``options``, \
or null. NEVER return a description, paraphrase, or combined phrase — even if the \
document text uses different wording, you must map it to the closest matching option \
string or null.
   - In ``conflict_details``, every ``value`` entry MUST also be one of the exact \
option strings, not free text.
   - If the document mentions content that maps to TWO OR MORE different picklist \
options (e.g. "annual external audit and quarterly internal red team" maps to both \
"Annually" and "Quarterly"), treat this as a conflict: set `answer` to null, \
`conflict` to true, and list each applicable picklist option as a separate entry \
in `conflict_details`.
5. For multi-select fields, return a JSON array of matching option strings, or null.
6. For integer fields, return a number or null.\
"""

_OUTPUT_FORMAT = """\
## Output format

Respond ONLY with a single JSON object — no markdown fences, no explanation, \
no trailing text.

Every field in the JSON object has this structure:
```
{
  "answer":           <value | null>,
  "conflict":         <boolean>,
  "conflict_reason":  <one-sentence explanation string | null>,
  "conflict_details": [{"value": <str>, "source": <str>, "excerpt": <str>, "source_type": <str>}, ...],
  "answer_basis":     [{"source": <str>, "excerpt": <str>, "source_type": <str>}, ...],
  "sources":          [<source_name>, ...]
}
```
- `conflict_reason`: a single sentence describing the contradiction \
(e.g. "acme_overview.pdf states Cortex XDR is in scope while the Zoom transcript \
explicitly states it is not part of this opportunity"). Set to null when conflict=false.
- `conflict_details`: when conflict=true, each entry has value, source, excerpt, \
and source_type (from the context header, e.g. 'zoom_transcript', 'pdf'). \
CRITICAL: every `value` in this list must be unique — no two entries may \
express the same underlying fact with different phrasing. Canonicalize first \
(see Rule 3), then write one entry per distinct canonical value only.
- `answer_basis`: the specific source(s) and verbatim excerpt(s) that directly \
produced the final answer. Include source_type from the context header \
(e.g. 'zoom_transcript', 'document', 'slack_message'). Leave as [] when `answer` is null.\
"""

_FEW_SHOT_EXAMPLES = """\
## Few-shot examples

**Example 1 — text field extracted successfully**
```json
{
  "answer": "Legacy Cisco AnyConnect VPN; no MFA enforced; split-tunnel not configured",
  "conflict": false,
  "conflict_reason": null,
  "conflict_details": [],
  "answer_basis": [
    {"source": "SE discovery call notes 2025-11-14", "excerpt": "Current VPN is Cisco AnyConnect. No MFA. Split-tunnel is not configured.", "source_type": "zoom_transcript"}
  ],
  "sources": ["SE discovery call notes 2025-11-14"]
}
```

**Example 2 — picklist field**
```json
{
  "answer": "Professional Services Team",
  "conflict": false,
  "conflict_reason": null,
  "conflict_details": [],
  "answer_basis": [
    {"source": "signed SOW v2", "excerpt": "Professional Services delivery will be handled by the Professional Services team.", "source_type": "document"}
  ],
  "sources": ["signed SOW v2"]
}
```

**Example 3 — conflict detected (explicit direct contradiction between sources)**
```json
{
  "answer": null,
  "conflict": true,
  "conflict_reason": "acme_pov_plan.pdf states the POV is in scope while slack://channel/opp-pov explicitly states it is not committed.",
  "conflict_details": [
    {"value": "Yes — POV is in scope", "source": "acme_pov_plan.pdf", "excerpt": "The SASE design is in scope for the proof of value.", "source_type": "document"},
    {"value": "No — POV is not committed", "source": "slack://channel/opp-pov", "excerpt": "Leadership sees this as design-first; POV may follow but is not committed.", "source_type": "slack_message"}
  ],
  "answer_basis": [],
  "sources": ["acme_pov_plan.pdf", "slack://channel/opp-pov"]
}
```

**Example 3b — NOT a conflict (one source has more detail, no direct negation)**
```json
{
  "answer": ["Prisma Access", "Prisma SD-WAN"],
  "conflict": false,
  "conflict_reason": null,
  "conflict_details": [],
  "answer_basis": [
    {"source": "acme_overview.pdf", "excerpt": "In-scope products: Prisma Access and Prisma SD-WAN for Phase 1.", "source_type": "document"}
  ],
  "sources": ["acme_overview.pdf", "slack://channel/opp-q1"]
}
```

**Example 3c — NOT a conflict (same fact, different phrasings — canonicalize to most complete)**
Sources say "24", "24 hours", "24-hour notification" — all mean the same thing.
```json
{
  "answer": "24-hour notification",
  "conflict": false,
  "conflict_reason": null,
  "conflict_details": [],
  "answer_basis": [
    {"source": "breach_policy.pdf", "excerpt": "Customers must be notified within 24 hours of a confirmed breach.", "source_type": "document"}
  ],
  "sources": ["breach_policy.pdf", "content.txt"]
}
```

**Example 3d — IS a conflict (genuinely different numbers/ranges)**
Sources say "24", "24 hours", "24-48 hours", and "24-48" — first canonicalize: "24" = "24 hours" (ONE entry), "24-48" = "24-48 hours" (ONE entry). After canonicalization there are two distinct values: "24 hours" vs "24-48 hours". These are different ranges → flag as conflict with exactly TWO entries (not four).
```json
{
  "answer": null,
  "conflict": true,
  "conflict_reason": "content.txt states 24-hour notification while sla_addendum.pdf states a 24-48 hour window.",
  "conflict_details": [
    {"value": "24 hours", "source": "content.txt", "excerpt": "Notification within 24 hours of confirmed breach.", "source_type": "document"},
    {"value": "24-48 hours", "source": "sla_addendum.pdf", "excerpt": "SLA requires breach notification within 24-48 hours.", "source_type": "document"}
  ],
  "answer_basis": [],
  "sources": ["content.txt", "sla_addendum.pdf"]
}
```

**Example 3e — picklist field: document mentions two different option values**
Question is a picklist with options: `Quarterly`, `Semi-Annually`, `Annually`, `Continuous`.
Document says: "annual external pen test by Trail of Bits and quarterly internal red team exercises".
Both "Annually" and "Quarterly" are distinct picklist options → conflict; do NOT combine into a description.
```json
{
  "answer": null,
  "conflict": true,
  "conflict_reason": "Document references both annual external testing and quarterly internal testing, mapping to two distinct picklist options.",
  "conflict_details": [
    {"value": "Annually", "source": "security_policy.pdf", "excerpt": "Annual external pen test by Trail of Bits.", "source_type": "document"},
    {"value": "Quarterly", "source": "security_policy.pdf", "excerpt": "Quarterly internal red team exercises.", "source_type": "document"}
  ],
  "answer_basis": [],
  "sources": ["security_policy.pdf"]
}
```

**Example 4 — information absent**
```json
{
  "answer": null,
  "conflict": false,
  "conflict_reason": null,
  "conflict_details": [],
  "answer_basis": [],
  "sources": []
}
```\
"""


class PromptBuilder:
    """Build system and user prompts for SASE opportunities Q&A extraction batches."""

    def _field_list_to_json(self, fields: list[FieldDefinition]) -> str:
        """Serialise FieldDefinition objects to a JSON array for the system prompt."""
        return json.dumps(
            [f.to_prompt_dict() for f in fields], indent=2, ensure_ascii=False
        )

    def _make_system_prompt(
        self,
        batch_id: str,
        batch_label: str,
        batch_description: str,
        include_few_shot: bool = False,
        section_level_prompt: str | None = None,
    ) -> str:
        """Build a system prompt from PostgreSQL-backed FieldDefinition objects."""
        fields = load_batch_fields(batch_id)
        field_json = self._field_list_to_json(fields)
        n_fields = len(fields)

        parts = [
            _AGENT_INTRO,
            "",
            _EXTRACTION_RULES,
            "",
            _OUTPUT_FORMAT,
            "",
            "---",
            "",
            f"## Fields to extract ({batch_label} — {n_fields} fields)",
            "",
            batch_description,
            "",
        ]
        if section_level_prompt and section_level_prompt.strip():
            parts += [
                "## Section instructions",
                "",
                section_level_prompt.strip(),
                "",
            ]
        parts += [
            "The fields are defined as a JSON array below. For each field:",
            "- Use ``field_name`` (e.g. ``OPP_001``) as the JSON key in your output.",
            "- ``q_id`` is the question identifier for reference only.",
            "- ``answer_type`` tells you what kind of value to return.",
            "- ``options`` lists the only valid values for picklist/multi-select fields (empty = free text).",
            "- If a field includes a ``prompt`` (extraction hint), use it to guide how you extract the answer.",
            "",
            field_json,
        ]
        if include_few_shot:
            parts += ["", "---", "", _FEW_SHOT_EXAMPLES]

        return "\n".join(parts)

    def _user_prompt_suffix(self, batch_id: str) -> str:
        """Build the closing extraction instruction for the user-turn message."""
        fields = load_batch_fields(batch_id)
        q_first, q_last = fields[0].q_id, fields[-1].q_id
        return (
            f"Extract all {len(fields)} fields ({q_first}–{q_last}) "
            "from the context documents above and return the JSON object described "
            "in the system prompt. Output ONLY the JSON — no other text.\n"
        )

    def build_system_prompt(self, batch_def: object) -> str:
        """Build the system prompt for batch_def."""
        return self._make_system_prompt(
            batch_id=batch_def.batch_id,  # type: ignore[attr-defined]
            batch_label=batch_def.label,  # type: ignore[attr-defined]
            batch_description=batch_def.description,  # type: ignore[attr-defined]
            include_few_shot=batch_def.include_few_shot,  # type: ignore[attr-defined]
            section_level_prompt=getattr(batch_def, "section_level_prompt", None),
        )

    def build_user_prompt(self, batch_id: str, context: str) -> str:
        """Build the user-turn message for any batch."""
        suffix = self._user_prompt_suffix(batch_id)
        return f"## Context documents\n\n{context}\n\n---\n\n{suffix}"

    def get_all_system_prompts(self) -> dict[str, str]:
        """Return {batch_key: system_prompt} for all batches."""
        from src.services.agent.batch_registry import get_batches

        return {
            f"batch{b.batch_order}": self.build_system_prompt(b) for b in get_batches()
        }


def get_prompt_builder() -> PromptBuilder:
    """Return the singleton PromptBuilder instance."""
    global _prompt_builder
    if _prompt_builder is None:
        _prompt_builder = PromptBuilder()
    return _prompt_builder


def build_system_prompt(batch_def: object) -> str:
    """Build the system prompt for batch_def."""
    return get_prompt_builder().build_system_prompt(batch_def)


def build_user_prompt(batch_id: str, context: str) -> str:
    """Build the user-turn message for any batch."""
    return get_prompt_builder().build_user_prompt(batch_id, context)


def get_all_system_prompts() -> dict[str, str]:
    """Return {batch_key: system_prompt} for all batches."""
    return get_prompt_builder().get_all_system_prompts()
