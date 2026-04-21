"""Central sync engine: list Zoom cloud recordings and ingest transcripts to GCS."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from configs.settings import get_settings
from src.services.database_manager.models.auth_models import (
    Opportunity,
    OpportunitySource,
    User,
)
from src.services.database_manager.orm import get_engine
from src.services.storage import Storage
from src.services.zoom.client import ZoomClient
from src.utils.logger import get_logger
from src.utils.opportunity_id import find_opportunity_oid, normalize_opportunity_oid

logger = get_logger(__name__)

_SYNC_LOOKBACK_DAYS = 90


def _connector_user_id_for_list() -> str:
    zcfg = get_settings().zoom
    connector_email = (zcfg.zoom_connector_user_email or "").strip()
    if not connector_email:
        raise ValueError(
            "ZOOM_CONNECTOR_USER_EMAIL is required for master-only Zoom ingestion flow."
        )
    return connector_email


def _transcript_vtt_file(recording_files: list[dict[str, Any]]) -> dict[str, Any] | None:
    for f in recording_files:
        if not isinstance(f, dict):
            continue
        file_type = (f.get("file_type") or "").upper()
        ext = (f.get("file_extension") or "").upper()
        
        # Zoom API returns transcripts variously as TRANSCRIPT, TIMELINE, AUDIO_TRANSCRIPT, CLOSED_CAPTION
        if file_type in ("TRANSCRIPT", "TIMELINE", "AUDIO_TRANSCRIPT", "CLOSED_CAPTION"):
            if ext in ("VTT", "TXT", ""):
                return f
        elif ext == "VTT":
            return f
    return None


class ZoomSyncService:
    """Download Zoom transcripts for meetings whose topic matches an OID and write to raw/zoom/."""

    async def sync_meeting(
        self,
        payload: dict[str, Any],
        download_token: str | None = None,
    ) -> bool:
        """Ingest one recording from a Zoom webhook payload (recording.completed).

        Returns True if a transcript was written to GCS; False if skipped or on failure.
        """
        obj = payload.get("object", {})
        topic = obj.get("topic", "")
        meeting_id = obj.get("id", "unknown")
        meeting_uuid = obj.get("uuid", str(meeting_id))

        logger.info(
            "Zoom sync_meeting: meeting={} topic={!r}",
            meeting_id,
            (topic or "")[:200],
        )

        oid_token = find_opportunity_oid(topic)
        if not oid_token:
            logger.warning(
                "No Opportunity ID in meeting topic: {}. Skipping.",
                topic,
            )
            return False

        opportunity_id = normalize_opportunity_oid(oid_token)
        logger.info("Zoom sync_meeting: mapped meeting {} to oid {}", meeting_id, opportunity_id)

        with Session(get_engine()) as db:
            source = (
                db.query(OpportunitySource)
                .join(Opportunity, OpportunitySource.opportunity_id == Opportunity.id)
                .filter(
                    Opportunity.opportunity_id == opportunity_id,
                    OpportunitySource.source_type == "zoom",
                )
                .first()
            )
            if not source:
                logger.warning(
                    "No zoom opportunity source for oid {}. Skipping.",
                    opportunity_id,
                )
                return False
            if (source.status or "").strip().upper() != "ACTIVE":
                logger.warning(
                    "Zoom source is not ACTIVE for oid {} (status={}). Skipping.",
                    opportunity_id,
                    source.status,
                )
                return False

        zoom_client = ZoomClient()
        storage = Storage()

        recording_files: list[dict[str, Any]] = list(obj.get("recording_files") or [])
        transcript_file: dict[str, Any] | None = None
        attempts = 0
        max_attempts = 3
        delay_sec = 60

        while attempts < max_attempts:
            transcript_file = _transcript_vtt_file(recording_files)
            if transcript_file:
                break
            attempts += 1
            if attempts < max_attempts:
                logger.info(
                    "Transcript not in payload for meeting %s. Waiting %ds (attempt %d/%d).",
                    meeting_id,
                    delay_sec,
                    attempts,
                    max_attempts,
                )
                await asyncio.sleep(delay_sec)
                try:
                    updated_obj = await zoom_client.get_recording_details(str(meeting_uuid))
                    recording_files = list(updated_obj.get("recording_files") or [])
                except Exception:
                    logger.exception(
                        "Failed to refresh recording details for meeting {}",
                        meeting_uuid,
                    )

        if not transcript_file:
            logger.warning(
                "No TRANSCRIPT file found after {} attempts for meeting {}",
                max_attempts,
                meeting_id,
            )
            return False

        download_url = transcript_file.get("download_url")
        if not download_url:
            logger.error(
                "TRANSCRIPT found but missing download_url for meeting {}",
                meeting_id,
            )
            return False

        try:
            logger.info("Downloading transcript from Zoom for meeting {}...", meeting_id)
            token_to_use = (
                download_token if "webhook_download" in download_url else None
            )
            content = await zoom_client.download_file(
                download_url, override_token=token_to_use
            )
        except Exception:
            logger.exception(
                "Failed to download transcript from Zoom for meeting {}",
                meeting_id,
            )
            return False

        object_name = f"{meeting_id}.vtt"
        try:
            uri = storage.write(
                tier="raw",
                opportunity_id=opportunity_id,
                source="zoom",
                object_name=object_name,
                content=content,
                content_type="text/vtt",
            )
            logger.info("Zoom sync_meeting: ingested transcript to {}", uri)
        except Exception:
            logger.exception(
                "Failed to save Zoom transcript to GCS for opportunity {}",
                opportunity_id,
            )
            return False

        return True

    async def sync_opportunity(self, oid: str, db: Session | None = None) -> dict[str, Any]:
        normalized_oid = normalize_opportunity_oid(oid)
        _ = db  # Signature compatibility; this method now uses short-lived sessions only.

        zcfg = get_settings().zoom
        if not (
            (zcfg.account_id or "").strip()
            and (zcfg.client_id or "").strip()
            and (zcfg.client_secret or "").strip()
        ):
            raise ValueError(
                "Zoom Server-to-Server OAuth is not configured "
                "(ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET)."
            )

        # 1) Read-only DB step in a short-lived session.
        with Session(get_engine()) as db_read:
            opp = (
                db_read.query(Opportunity)
                .filter(Opportunity.opportunity_id == normalized_oid)
                .first()
            )
            if not opp:
                raise ValueError(f"Opportunity not found for oid '{normalized_oid}'.")

            source = (
                db_read.query(OpportunitySource)
                .filter(
                    OpportunitySource.opportunity_id == opp.id,
                    OpportunitySource.source_type == "zoom",
                )
                .first()
            )
            if not source:
                raise ValueError(
                    f"No zoom opportunity source found for '{normalized_oid}'."
                )

            opp_db_id = int(opp.id)
            # Master-only flow: always list recordings from connector account.
            list_user = _connector_user_id_for_list()

        # 2) Long-running external work with no DB session open.
        items_synced = 0
        to_d = date.today()
        from_d = to_d - timedelta(days=_SYNC_LOOKBACK_DAYS)
        client = ZoomClient()
        recordings = await client.list_recordings(
            from_date=from_d.isoformat(),
            to_date=to_d.isoformat(),
            user_id=list_user,
        )

        storage = Storage()
        for meeting in recordings:
            if not isinstance(meeting, dict):
                continue
            topic = (meeting.get("topic") or "").strip()

            # Robustly find OID applying the exact same regex/normalization as discovery.
            extracted_oid = find_opportunity_oid(topic)
            if not extracted_oid or normalize_opportunity_oid(extracted_oid) != normalized_oid:
                continue

            meeting_id = meeting.get("id")
            if meeting_id is None:
                logger.warning(
                    "Zoom sync: skipping meeting without id (topic={!r})",
                    topic[:120],
                )
                continue
            mid_str = str(meeting_id)

            recording_files: list[dict[str, Any]] = list(meeting.get("recording_files") or [])
            if not recording_files:
                try:
                    detail = await client.get_recording_details(
                        str(meeting.get("uuid") or mid_str)
                    )
                    recording_files = list(detail.get("recording_files") or [])
                except Exception:
                    logger.exception(
                        "Zoom sync: failed to fetch recording details for meeting {}",
                        mid_str,
                    )
                    continue

            transcript = _transcript_vtt_file(recording_files)
            if not transcript:
                logger.debug(
                    "Zoom sync: no TRANSCRIPT/VTT for meeting_id={} topic={!r}",
                    mid_str,
                    topic[:120],
                )
                continue

            download_url = transcript.get("download_url")
            if not download_url:
                continue

            object_name = f"{mid_str}.vtt"
            if storage.exists(
                tier="raw",
                opportunity_id=normalized_oid,
                source="zoom",
                object_name=object_name,
            ):
                continue

            content = await client.download_file(download_url)
            storage.write(
                tier="raw",
                opportunity_id=normalized_oid,
                source="zoom",
                object_name=object_name,
                content=content,
                content_type="text/vtt",
            )
            items_synced += 1
            logger.info(
                "Zoom sync: wrote gs raw/zoom/{} for oid={}",
                object_name,
                normalized_oid,
            )

        # 3) Write-back DB step in a fresh short-lived session.
        with Session(get_engine()) as db_write:
            source = (
                db_write.query(OpportunitySource)
                .filter(
                    OpportunitySource.opportunity_id == opp_db_id,
                    OpportunitySource.source_type == "zoom",
                )
                .first()
            )
            if source:
                now = datetime.now(UTC)
                source.status = "ACTIVE"
                source.last_synced_at = now
                db_write.commit()

        return {"ok": True, "items_synced": items_synced}
