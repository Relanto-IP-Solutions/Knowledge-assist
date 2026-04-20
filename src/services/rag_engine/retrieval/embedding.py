"""Vertex AI embeddings and GCP auth for retrieval."""

from __future__ import annotations

import google.auth
import google.auth.transport.requests

from configs.settings import get_settings
from src.utils.logger import get_logger
from src.utils.retry import retry_on_transient


logger = get_logger(__name__)

CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

# text-embedding-004: max 20,000 tokens per request; max 250 instances per request.
# Cap below 20k so token-dense chunks (code, numbers) don't push real count over.
MAX_TOKENS_PER_BATCH = 8_000  # len//2 + this cap keeps real tokens under 20k
MAX_TEXTS_PER_BATCH = 230


def _approx_tokens(text: str) -> int:
    """Conservative token estimate for batching (~2 chars per token).
    Vertex tokenizer often yields more tokens than len/4; using len/2 avoids exceeding 20k/batch."""
    return max(1, len(text) // 2)


_embedding_service: EmbeddingService | None = None


class EmbeddingService:
    """Vertex AI embeddings and GCP auth for retrieval."""

    def __init__(self) -> None:
        self._client = None

    def get_access_token(self) -> str:
        """Get OAuth2 access token for Vector Search and reranking HTTP calls."""
        project_id = (
            get_settings().retrieval.gcp_project_id
            or get_settings().ingestion.gcp_project_id
        )
        logger.debug(
            "Acquiring GCP access token (project_id=%s)", project_id or "default"
        )
        creds, _ = google.auth.default(
            scopes=[CLOUD_PLATFORM_SCOPE],
            quota_project_id=project_id or None,
        )
        req = google.auth.transport.requests.Request()
        creds.refresh(req)
        logger.debug("Access token acquired")
        return creds.token

    def _get_client(self):
        """Lazily initialize and return the google-genai Client for Vertex AI."""
        if self._client is None:
            from google import genai

            settings = get_settings().retrieval
            project_id = (
                settings.gcp_project_id or get_settings().ingestion.gcp_project_id
            )
            logger.info(
                "Initializing Vertex AI embedder: project=%s, location=%s",
                project_id,
                settings.vertex_ai_location,
            )
            self._client = genai.Client(
                vertexai=True,
                project=project_id,
                location=settings.vertex_ai_location,
            )
            logger.debug("google-genai Client initialized for text-embedding-004")
        return self._client

    @retry_on_transient()
    def embed_question(self, question: str) -> list[float]:
        """Embed a single question using RETRIEVAL_QUERY task type; returns vector of floats. Retries on transient errors."""
        from google.genai import types

        client = self._get_client()
        result = client.models.embed_content(
            model="text-embedding-004",
            contents=question,
            config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
        )
        vec = list(result.embeddings[0].values)
        logger.debug(
            "Embedded question (len=%d chars -> dim=%d)", len(question), len(vec)
        )
        return vec

    @retry_on_transient()
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts (e.g. for ingestion) using RETRIEVAL_DOCUMENT; returns list of vectors. Retries on transient errors.
        Batches by token count (max 20k/request) and by instance count (max 250/request)."""
        if not texts:
            return []
        from google.genai import types

        client = self._get_client()
        all_vectors: list[list[float]] = []
        batch_number = 0
        i = 0
        while i < len(texts):
            batch: list[str] = []
            batch_tokens = 0
            while i < len(texts) and len(batch) < MAX_TEXTS_PER_BATCH:
                t = texts[i]
                est = _approx_tokens(t)
                if batch_tokens + est > MAX_TOKENS_PER_BATCH and batch:
                    break
                batch.append(t)
                batch_tokens += est
                i += 1
            if not batch:
                # Single text exceeds token limit; send alone (API may error or truncate)
                batch = [texts[i]]
                i += 1
            batch_est_tokens = sum(_approx_tokens(t) for t in batch)
            batch_number += 1
            logger.info(
                "Embedding batch %d (%d texts, ~%d tokens)",
                batch_number,
                len(batch),
                batch_est_tokens,
            )
            result = client.models.embed_content(
                model="text-embedding-004",
                contents=batch,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
            )
            batch_vectors = [list(e.values) for e in result.embeddings]
            all_vectors.extend(batch_vectors)
        return all_vectors


def get_embedding_service() -> EmbeddingService:
    """Return the singleton EmbeddingService instance."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


def get_access_token() -> str:
    """Get OAuth2 access token for Vector Search and reranking HTTP calls."""
    return get_embedding_service().get_access_token()


def embed_question(question: str) -> list[float]:
    """Embed a single question; returns vector of floats."""
    return get_embedding_service().embed_question(question)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts (e.g. for ingestion); returns list of vectors. Retries on transient errors."""
    return get_embedding_service().embed_texts(texts)
