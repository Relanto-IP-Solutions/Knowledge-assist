"""Pydantic models for Slack channel LLM extraction.

Structure
---------
EvidencedItem       — a single extracted item with confidence + supporting message timestamps
ActionItem          — EvidencedItem variant with an optional owner field
Entities            — named-entity buckets extracted from the conversation
ChannelAnalysis     — top-level response model written to GCS processed/slack/

These models are intentionally free of any LLM or GCS imports — they can be
used anywhere in the codebase (serialisation, testing, downstream consumers).
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------


class EvidencedItem(BaseModel):
    """A single item extracted from a Slack conversation with supporting evidence."""

    item: str = Field(description="The extracted item text.")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Extraction confidence between 0.0 and 1.0. "
            "Lower the score rather than omitting uncertain items."
        ),
    )
    evidence_ts: list[str] = Field(
        default_factory=list,
        description=(
            "Slack message ts strings (e.g. '1715856500.000900') "
            "that are the primary evidence for this item."
        ),
    )


class ActionItem(BaseModel):
    """A concrete task or follow-up action extracted from the conversation."""

    item: str = Field(description="The action to be taken.")
    owner: str | None = Field(
        default=None,
        description="Person responsible for the action, if explicitly named.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Extraction confidence between 0.0 and 1.0.",
    )
    evidence_ts: list[str] = Field(
        default_factory=list,
        description="Slack message ts strings that are the primary evidence for this action.",
    )


def _coerce_dict_to_evidenced_item(item: dict) -> dict:
    """Map alternate LLM keys (e.g. ``name`` for people) onto EvidencedItem fields."""
    out = dict(item)
    if not out.get("item"):
        if out.get("name") is not None:
            out["item"] = str(out["name"])
        elif out.get("slack_id"):
            out["item"] = str(out["slack_id"])
    if "confidence" not in out:
        out["confidence"] = 0.8
    if "evidence_ts" not in out:
        out["evidence_ts"] = []
    return out


def _coerce_entity_list(value: list) -> list[dict]:
    """Normalise a list of entity items that may be plain strings or EvidencedItem dicts.

    The LLM sometimes returns plain strings, sometimes objects.  This validator
    promotes plain strings to minimal EvidencedItem dicts so Pydantic can
    validate them uniformly.

    Dicts may use ``name`` / ``slack_id`` instead of ``item`` (common for
    ``entities.people``); those are coerced before validation.
    """
    result = []
    for item in value:
        if isinstance(item, str):
            result.append({"item": item, "confidence": 1.0, "evidence_ts": []})
        elif isinstance(item, dict):
            result.append(_coerce_dict_to_evidenced_item(item))
        else:
            result.append(item)
    return result


class Entities(BaseModel):
    """Named entities extracted from the Slack conversation.

    Each list contains EvidencedItem objects so that entity mentions are
    traceable back to specific Slack messages via evidence_ts.
    The field validators accept both plain strings and EvidencedItem dicts
    because the LLM response format is non-deterministic across runs.
    """

    products: list[EvidencedItem] = Field(
        default_factory=list,
        description="Product names mentioned (e.g. 'Prisma Access', 'CrowdStrike').",
    )
    features: list[EvidencedItem] = Field(
        default_factory=list,
        description="Product features or capabilities discussed (e.g. 'SSO', 'RBAC', 'DLP').",
    )
    integrations: list[EvidencedItem] = Field(
        default_factory=list,
        description="Third-party systems or integration points referenced (e.g. 'Salesforce', 'Okta').",
    )
    people: list[EvidencedItem] = Field(
        default_factory=list,
        description="Named individuals mentioned in the conversation.",
    )
    teams: list[EvidencedItem] = Field(
        default_factory=list,
        description="Teams or departments referenced (e.g. 'Security Ops', 'Procurement').",
    )
    vendors: list[EvidencedItem] = Field(
        default_factory=list,
        description="External vendor or partner names (competitors/partners).",
    )

    @field_validator(
        "products",
        "features",
        "integrations",
        "people",
        "teams",
        "vendors",
        mode="before",
    )
    @classmethod
    def coerce_entity_items(cls, v: list) -> list:
        return _coerce_entity_list(v)


# ---------------------------------------------------------------------------
# Top-level response model
# ---------------------------------------------------------------------------


class ChannelAnalysis(BaseModel):
    """Structured LLM extraction output for a single Slack channel.

    Persisted as JSON to GCS at:
        {opp_id}/processed/slack/{channel}_analysis.json

    On each 30-min pipeline run the model is updated incrementally:
    the previous ChannelAnalysis is fed back as context together with
    the new cleaned dialogue, and the LLM produces a single merged result.
    """

    summary: str = Field(
        description=(
            "Rolling prose summary of the full conversation so far. "
            "Should capture the arc of the discussion, not just the latest batch."
        ),
    )
    requirements: list[EvidencedItem] = Field(
        default_factory=list,
        description="Technical and business requirements captured from the conversation.",
    )
    decisions: list[EvidencedItem] = Field(
        default_factory=list,
        description="Decisions made or agreed upon by the participants.",
    )
    action_items: list[ActionItem] = Field(
        default_factory=list,
        description="Concrete tasks or follow-ups, with owners where mentioned.",
    )
    open_questions: list[EvidencedItem] = Field(
        default_factory=list,
        description="Unresolved questions or topics pending clarification.",
    )
    risks_or_constraints: list[EvidencedItem] = Field(
        default_factory=list,
        description="Risks, blockers, or constraints that could affect the engagement.",
    )
    entities: Entities = Field(
        default_factory=Entities,
        description="Named entities extracted across the full conversation history.",
    )
