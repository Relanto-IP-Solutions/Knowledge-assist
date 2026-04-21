"""Generic LLM service — Vertex AI / Gemini client."""

from src.services.llm.client import LLMClient, LLMError


__all__ = ["LLMClient", "LLMError"]
