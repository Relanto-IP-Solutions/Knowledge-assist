"""Prompt templates for Slack channel LLM extraction.

Usage
-----
    from src.services.preprocessing.slack.prompts import (
        SYSTEM_PROMPT,
        build_first_run_prompt,
        build_incremental_prompt,
    )
    from src.services.preprocessing.slack.schemas import ChannelAnalysis

    # First run (no prior analysis):
    prompt = SYSTEM_PROMPT + "\\n\\n" + build_first_run_prompt(dialogue, channel, opp_id)

    # Subsequent runs (update existing analysis):
    prompt = SYSTEM_PROMPT + "\\n\\n" + build_incremental_prompt(
        dialogue, channel, opp_id, previous_analysis
    )

    result: ChannelAnalysis = LLMClient().generate(prompt, ChannelAnalysis)
"""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from src.services.preprocessing.slack.schemas import ChannelAnalysis


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a Solutions Engineer assistant. Your job is to maintain a running \
structured analysis of a Slack channel used during a SASE sales engagement.

## Extraction rules

1. Extract only what is explicitly stated in the conversation. Do not infer, \
assume, or generalise beyond what the participants actually say.
2. For each extracted item (requirements, decisions, action_items, \
open_questions, risks_or_constraints):
   - Set `item` to a concise, self-contained description.
   - Set `confidence` to a float between 0.0 and 1.0 reflecting how \
certain you are the item was genuinely stated or agreed. Lower confidence \
rather than omitting uncertain items.
   - Set `evidence_ts` to the list of Slack message `ts` strings \
(e.g. "1715856500.000900") visible in the conversation that most directly \
support the item. Use only ts values present in the provided dialogue.
3. For `action_items`, populate `owner` only when a specific person is \
explicitly named as responsible; otherwise leave it null.
4. For `entities`, extract:
   - `products`      — product names (e.g. Prisma Access, Cortex XDR, \
Prisma Cloud) and competing products mentioned.
   - `features`      — specific capabilities or feature names discussed \
(e.g. SSO, RBAC, DLP, Zero Trust).
   - `integrations`  — third-party systems the customer uses or wants to \
integrate (e.g. Salesforce, Okta, ServiceNow).
   - `people`        — named individuals mentioned by first name, full name, \
or role title when a name is attached.
   - `teams`         — internal or customer-side teams referenced \
(e.g. "Security Ops", "Procurement").
   - `vendors`       — external vendor or partner names that are not the \
primary platform vendor (e.g. Cisco, Zscaler, other competitors).
5. Write `summary` as flowing prose that covers the arc of the conversation. \
It should be understandable without reading the raw messages.

## Output format

Respond ONLY with a single JSON object — no markdown fences, no explanation, \
no trailing text. The JSON must conform to the ChannelAnalysis schema.
"""

# ---------------------------------------------------------------------------
# User prompt builders
# ---------------------------------------------------------------------------

_FIRST_RUN_TEMPLATE = """\
## Context

Channel  : {channel}
Opportunity: {opportunity_id}

## Conversation

{dialogue}

---

Produce a complete ChannelAnalysis JSON for the conversation above. \
This is the first analysis for this channel — there is no prior summary to merge.
"""

_INCREMENTAL_TEMPLATE = """\
## Context

Channel  : {channel}
Opportunity: {opportunity_id}

## Existing analysis

{previous_analysis_json}

## New messages since last analysis

{dialogue}

---

Produce an updated ChannelAnalysis JSON that:
- Extends `summary` to incorporate new developments while preserving the \
history already captured.
- Adds new items to requirements, decisions, action_items, open_questions, \
and risks_or_constraints found in the new messages.
- Updates `confidence` and `evidence_ts` on existing items that are \
reinforced or contradicted by the new messages.
- Removes items that are clearly resolved, completed, or superseded.
- Merges new entity mentions into the existing entity lists (no duplicates).
"""


def build_first_run_prompt(
    dialogue: str,
    channel: str,
    opportunity_id: str,
) -> str:
    """Build the user-turn message for a first-time channel analysis.

    Args:
        dialogue:       Cleaned Slack dialogue produced by SlackPreprocessor.
        channel:        Channel stem (e.g. 'general', 'opp-acme-sase').
        opportunity_id: Opportunity identifier for context.

    Returns:
        Formatted string to append after SYSTEM_PROMPT.
    """
    return _FIRST_RUN_TEMPLATE.format(
        channel=channel,
        opportunity_id=opportunity_id,
        dialogue=dialogue,
    )


def build_incremental_prompt(
    dialogue: str,
    channel: str,
    opportunity_id: str,
    previous_analysis: ChannelAnalysis,
) -> str:
    """Build the user-turn message for updating an existing channel analysis.

    Args:
        dialogue:          Cleaned Slack dialogue for the new batch of messages.
        channel:           Channel stem.
        opportunity_id:    Opportunity identifier for context.
        previous_analysis: The ChannelAnalysis produced on the last run.

    Returns:
        Formatted string to append after SYSTEM_PROMPT.
    """
    return _INCREMENTAL_TEMPLATE.format(
        channel=channel,
        opportunity_id=opportunity_id,
        previous_analysis_json=previous_analysis.model_dump_json(indent=2),
        dialogue=dialogue,
    )
