"""Pub/Sub publisher: thin wrapper around the GCP Pub/Sub client."""

import json
from pathlib import Path

from google.cloud import pubsub_v1
from google.oauth2 import service_account

from configs.settings import get_settings
from src.utils.logger import get_logger
from src.utils.retry import retry_on_transient


logger = get_logger(__name__)


class Publisher:
    """GCP Pub/Sub publisher. Publishes structured JSON messages to a configured topic."""

    def __init__(self, topic: str | None = None) -> None:
        """Initialize the publisher.

        Args:
            topic: Pub/Sub topic resource name (projects/{project}/topics/{name}),
                   or topic name only. If not provided, reads PUBSUB_TOPIC_RAG_INGESTION from settings.
        """
        settings = get_settings()
        project = settings.ingestion.gcp_project_id
        topic_name = topic or settings.ingestion.pubsub_topic_rag_ingestion
        if topic_name and topic_name.startswith("projects/"):
            self._topic_path = topic_name
        else:
            self._topic_path = f"projects/{project}/topics/{topic_name}"

        key_path = (settings.ingestion.google_application_credentials or "").strip()
        if key_path:
            path_resolved = Path(key_path).expanduser().resolve()
            credentials = service_account.Credentials.from_service_account_file(
                str(path_resolved),
                scopes=["https://www.googleapis.com/auth/pubsub"],
            )
            self._client = pubsub_v1.PublisherClient(credentials=credentials)
        else:
            self._client = pubsub_v1.PublisherClient()

        logger.info("Publisher initialised", extra={})

    def publish(self, message: dict, opportunity_id: str | None = None) -> str:
        """Serialize message to JSON and publish to the Pub/Sub topic.

        Retries on GCP transient errors (e.g. DeadlineExceeded, Unavailable).

        Args:
            message: Structured dict matching the RAG ingestion message schema.
            opportunity_id: Optional opportunity ID for log extras.

        Returns:
            Pub/Sub message ID string.
        """
        extras = {"opportunity_id": opportunity_id} if opportunity_id else {}
        try:
            return self._publish_impl(message, extras)
        except Exception:
            logger.error(
                "Failed to publish message",
                exc_info=True,
                extra=extras,
            )
            raise

    @retry_on_transient()
    def _publish_impl(self, message: dict, extras: dict) -> str:
        data = json.dumps(message, ensure_ascii=False).encode("utf-8")
        future = self._client.publish(self._topic_path, data=data)
        message_id = future.result()
        logger.info(
            "Published message",
            extra=extras,
        )
        return message_id
