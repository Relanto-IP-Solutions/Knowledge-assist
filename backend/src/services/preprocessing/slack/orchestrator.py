"""Slack channel orchestrator: text reconstruction + LLM summarisation.

This module is the single entry point for processing a raw Slack file end-to-end.
It combines SlackPreprocessor (Phase 1) with the LLMClient (Phase 2) and is
designed to be called by gcs_pipeline._process_slack (Phase 3) with all content
passed as arguments — no GCS I/O happens here.

Responsibilities
----------------
- Parse and clean raw Slack bytes into dialogue text (SlackPreprocessor).
- Build the correct prompt depending on whether a prior analysis exists.
- Call the generic LLMClient to produce a validated ChannelAnalysis.
- Return (ChannelAnalysis, latest_ts) for the caller to persist, or None if
  there are no new messages.

What this module does NOT do
-----------------------------
- Read from or write to GCS.
- Manage state files (_state.json).
- Know about opportunity IDs beyond passing them to the prompt.
"""

from __future__ import annotations

from src.services.llm.client import LLMClient
from src.services.preprocessing.slack.preprocessor import SlackPreprocessor
from src.services.preprocessing.slack.prompts import (
    SYSTEM_PROMPT,
    build_first_run_prompt,
    build_incremental_prompt,
)
from src.services.preprocessing.slack.schemas import ChannelAnalysis
from src.utils.logger import get_logger


logger = get_logger(__name__)


class SlackOrchestrator:
    """Orchestrate Slack text reconstruction and LLM channel analysis.

    Args:
        llm: Optional pre-constructed LLMClient. When None a default instance
             is created on first use, which is the normal production path.
             Pass an explicit instance in tests to inject a mock.
    """

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm or LLMClient()

    def process(
        self,
        raw_bytes: bytes,
        channel: str,
        opportunity_id: str,
        since_ts: float | None = None,
        user_map: dict | None = None,
        previous_analysis: ChannelAnalysis | None = None,
    ) -> tuple[ChannelAnalysis, float] | None:
        """Preprocess raw Slack bytes and return an updated ChannelAnalysis.

        Args:
            raw_bytes:         Raw content of a Slack JSON-array or NDJSON file.
            channel:           Channel stem used as a label in the prompt
                               (e.g. 'general', 'opp-acme-sase').
            opportunity_id:    Opportunity identifier passed to the prompt for
                               context.
            since_ts:          Unix timestamp of the last processed message.
                               Only messages newer than this are included in the
                               current batch. Pass None for a cold start (all
                               messages treated as new).
            user_map:          Optional {user_id: display_name} dict for
                               @mention resolution. When None, raw user IDs are
                               kept as-is in the dialogue.
            previous_analysis: The ChannelAnalysis produced on the previous run,
                               or None if this is the first time the channel is
                               processed.

        Returns:
            (analysis, latest_ts) where:
            - analysis    : updated ChannelAnalysis — the caller should persist
                            this to GCS.
            - latest_ts   : float ts of the newest message in this batch — the
                            caller should save this as the new checkpoint.
            Returns None when there are no new messages since `since_ts`
            (i.e. nothing to do; caller should skip GCS writes).

        Raises:
            LLMError: Propagated from LLMClient if the Vertex AI call or
                      schema validation fails.
        """
        extras = {"opportunity_id": opportunity_id}
        try:
            # Step 1 — reconstruct dialogue from raw bytes
            dialogue, latest_ts = SlackPreprocessor().preprocess(
                raw_bytes, user_map=user_map, since_ts=since_ts
            )
        except Exception:
            logger.error(
                "Slack preprocessing failed",
                exc_info=True,
                extra=extras,
            )
            raise

        if not dialogue or latest_ts is None:
            logger.info(
                "No new Slack messages to process",
                extra=extras,
            )
            return None

        logger.info(
            "Slack dialogue reconstructed",
            extra=extras,
        )

        # Step 2 — build prompt
        if previous_analysis is None:
            user_prompt = build_first_run_prompt(dialogue, channel, opportunity_id)
        else:
            user_prompt = build_incremental_prompt(
                dialogue, channel, opportunity_id, previous_analysis
            )

        full_prompt = SYSTEM_PROMPT + "\n\n" + user_prompt

        # Step 3 — call LLM and get structured output
        logger.info(
            "Calling LLM for Slack channel analysis",
            extra=extras,
        )

        try:
            analysis = self._llm.generate(full_prompt, ChannelAnalysis)
        except Exception:
            logger.error(
                "Slack LLM channel analysis failed",
                exc_info=True,
                extra=extras,
            )
            raise

        logger.info(
            "Slack channel analysis produced",
            extra=extras,
        )

        return analysis, latest_ts
