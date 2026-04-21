"""Zoom webhook handler for processing recording.completed events."""

import hashlib
import hmac
from typing import Any

from configs.settings import get_settings
from src.services.zoom.sync_service import ZoomSyncService
from src.utils.logger import get_logger


logger = get_logger(__name__)


class ZoomWebhookHandler:
    """Handles Zoom webhook events, specifically recording.completed."""

    def __init__(self) -> None:
        self.settings = get_settings().zoom
        self.sync_service = ZoomSyncService()

    def verify_signature(self, message: str, signature: str) -> bool:
        """Verify the Zoom webhook signature using the Secret Token."""
        if not self.settings.webhook_secret_token:
            logger.warning(
                "ZOOM_WEBHOOK_SECRET_TOKEN not set, skipping signature verification"
            )
            return True

        hashed = hmac.new(
            self.settings.webhook_secret_token.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(hashed, signature)

    def handle_url_verification(self, challenge: str) -> str:
        """Respond to Zoom's URL verification challenge."""
        return hmac.new(
            self.settings.webhook_secret_token.encode("utf-8"),
            challenge.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def process_event(
        self, event: str, payload: dict[str, Any], download_token: str | None = None
    ) -> None:
        """Process a Zoom webhook event."""
        if event in ["recording.completed", "recording.transcript_completed"]:
            await self._handle_recording_completed(payload, download_token)
        else:
            logger.debug("Ignoring Zoom event type: {}", event)

    async def _handle_recording_completed(
        self, payload: dict[str, Any], download_token: str | None = None
    ) -> None:
        """Delegate recording ingestion to ZoomSyncService."""
        ok = await self.sync_service.sync_meeting(
            payload,
            download_token=download_token,
        )
        if ok:
            logger.info("Zoom webhook: meeting transcript ingested successfully.")
        else:
            logger.info(
                "Zoom webhook: meeting skipped or transcript ingestion failed."
            )
