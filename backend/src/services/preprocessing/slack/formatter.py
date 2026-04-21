"""RAG-friendly plain-text formatter for ChannelAnalysis output.

Converts a structured ChannelAnalysis Pydantic model into a clean, numbered
plain-text document that downstream RAG chunkers can split on section
boundaries.  Intended to be the single source of truth for this layout so
both gcs_pipeline and the smoke script produce identical output.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from src.services.preprocessing.slack.schemas import ChannelAnalysis


class SlackAnalysisFormatter:
    """Formats ChannelAnalysis as RAG-friendly plain text."""

    def format_analysis_as_text(
        self,
        analysis: ChannelAnalysis,
        channel: str,
        opportunity_id: str,
        checkpoint_ts: float,
    ) -> str:
        """Render a ChannelAnalysis as clean, RAG-friendly plain text.

        Each section is headed with a clear label and items are numbered so that
        downstream chunkers can split on section boundaries if needed.

        Args:
            analysis:       Validated ChannelAnalysis produced by SlackOrchestrator.
            channel:        Slack channel stem (e.g. 'all-pzf').
            opportunity_id: Opportunity identifier used as a label in the header.
            checkpoint_ts:  Unix timestamp of the newest message in this batch,
                            used to stamp the report header.

        Returns:
            Multi-line plain-text string ready to be written to GCS as .txt.
        """
        ts_str = datetime.fromtimestamp(checkpoint_ts, tz=UTC).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

        lines: list[str] = []

        def heading(title: str) -> None:
            lines.append("")
            lines.append("=" * 60)
            lines.append(title.upper())
            lines.append("=" * 60)

        def subheading(title: str) -> None:
            lines.append("")
            lines.append(f"--- {title} ---")

        def fmt_entities(items) -> str:
            return ", ".join(e.item for e in items)

        # Report header
        lines.append("CHANNEL ANALYSIS REPORT")
        lines.append(f"Channel         : {channel}")
        lines.append(f"Opportunity ID  : {opportunity_id}")
        lines.append(f"Last message at : {ts_str}")

        # Summary
        heading("Summary")
        lines.append(analysis.summary)

        # Requirements
        heading("Requirements")
        if analysis.requirements:
            for i, req in enumerate(analysis.requirements, 1):
                lines.append(f"{i}. {req.item}")
                lines.append(
                    f"   Confidence: {req.confidence:.0%}  |  Evidence ts: {', '.join(req.evidence_ts)}"
                )
        else:
            lines.append("None captured.")

        # Decisions
        heading("Decisions")
        if analysis.decisions:
            for i, dec in enumerate(analysis.decisions, 1):
                lines.append(f"{i}. {dec.item}")
                lines.append(
                    f"   Confidence: {dec.confidence:.0%}  |  Evidence ts: {', '.join(dec.evidence_ts)}"
                )
        else:
            lines.append("None captured.")

        # Action Items
        heading("Action Items")
        if analysis.action_items:
            for i, act in enumerate(analysis.action_items, 1):
                owner = f"  [Owner: {act.owner}]" if act.owner else ""
                lines.append(f"{i}. {act.item}{owner}")
                lines.append(
                    f"   Confidence: {act.confidence:.0%}  |  Evidence ts: {', '.join(act.evidence_ts)}"
                )
        else:
            lines.append("None captured.")

        # Open Questions
        heading("Open Questions")
        if analysis.open_questions:
            for i, q in enumerate(analysis.open_questions, 1):
                lines.append(f"{i}. {q.item}")
                lines.append(
                    f"   Confidence: {q.confidence:.0%}  |  Evidence ts: {', '.join(q.evidence_ts)}"
                )
        else:
            lines.append("None captured.")

        # Risks / Constraints
        heading("Risks and Constraints")
        if analysis.risks_or_constraints:
            for i, risk in enumerate(analysis.risks_or_constraints, 1):
                lines.append(f"{i}. {risk.item}")
                lines.append(
                    f"   Confidence: {risk.confidence:.0%}  |  Evidence ts: {', '.join(risk.evidence_ts)}"
                )
        else:
            lines.append("None captured.")

        # Entities
        heading("Entities")
        ent = analysis.entities
        if ent.products:
            subheading("Products")
            lines.append(fmt_entities(ent.products))
        if ent.features:
            subheading("Features")
            lines.append(fmt_entities(ent.features))
        if ent.integrations:
            subheading("Integrations")
            lines.append(fmt_entities(ent.integrations))
        if ent.people:
            subheading("People")
            lines.append(fmt_entities(ent.people))
        if ent.teams:
            subheading("Teams")
            lines.append(fmt_entities(ent.teams))
        if ent.vendors:
            subheading("Vendors")
            lines.append(fmt_entities(ent.vendors))
        if not any([
            ent.products,
            ent.features,
            ent.integrations,
            ent.people,
            ent.teams,
            ent.vendors,
        ]):
            lines.append("None captured.")

        lines.append("")
        return "\n".join(lines)


def format_analysis_as_text(
    analysis: ChannelAnalysis,
    channel: str,
    opportunity_id: str,
    checkpoint_ts: float,
) -> str:
    """Render a ChannelAnalysis as clean, RAG-friendly plain text (module-level wrapper)."""
    return SlackAnalysisFormatter().format_analysis_as_text(
        analysis, channel, opportunity_id, checkpoint_ts
    )
