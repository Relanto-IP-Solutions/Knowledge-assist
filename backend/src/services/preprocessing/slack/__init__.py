"""Slack preprocessing package.

Public surface
--------------
SlackPreprocessor       — text extraction and cleaning from raw Slack exports
SlackOrchestrator       — end-to-end: preprocessing + LLM channel analysis
SlackAnalysisFormatter  — render ChannelAnalysis as RAG-ready plain text
ChannelAnalysis         — Pydantic model for structured LLM output
format_analysis_as_text — module-level wrapper for SlackAnalysisFormatter
"""

from src.services.preprocessing.slack.formatter import (
    SlackAnalysisFormatter,
    format_analysis_as_text,
)
from src.services.preprocessing.slack.orchestrator import SlackOrchestrator
from src.services.preprocessing.slack.preprocessor import SlackPreprocessor
from src.services.preprocessing.slack.schemas import ChannelAnalysis


__all__ = [
    "ChannelAnalysis",
    "SlackAnalysisFormatter",
    "SlackOrchestrator",
    "SlackPreprocessor",
    "format_analysis_as_text",
]
