"""Pub/Sub pipeline: scan GCS processed/ objects and publish RAG ingestion events."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import requests
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token

from configs.settings import get_settings
from src.services.pubsub.publisher import Publisher
from src.services.storage import Storage
from src.utils.logger import get_logger


logger = get_logger(__name__)

# GCS source directory name → pubsub source_type value.
# Bucket layout:
#   {opp_id}/processed/documents/                     → all files dispatched → rag-ingestion-queue
#   {opp_id}/processed/zoom_transcripts/              → .txt files only      → rag-ingestion-queue
#   {opp_id}/processed/slack_messages/{channel_id}/   → .txt files only      → rag-ingestion-queue
#   {opp_id}/processed/gmail_messages/{thread_id}/    → .txt files only      → rag-ingestion-queue
_SOURCE_TYPE_MAP: dict[str, str] = {
    "documents": "documents",
    "zoom_transcripts": "zoom_transcripts",
    "slack_messages": "slack_messages",
    "gmail_messages": "gmail_messages",
}


def parse_document_deleted_pubsub_body(body: dict) -> tuple[str, str] | None:
    """Extract (opportunity_id, object_name) from document_deleted Pub/Sub body.

    Supports action_type=document_deleted + data_path + metadata, or legacy
    event=document_deleted + top-level opportunity_id/object_name.
    """
    if body.get("action_type") == "document_deleted":
        if body.get("source_type") != "documents":
            return None
        data_path = (body.get("data_path") or "").strip()
        if not data_path.startswith("gs://"):
            return None
        parts = data_path[5:].split("/")
        if len(parts) < 5 or parts[2] != "processed" or parts[3] != "documents":
            return None
        meta = body.get("metadata") or {}
        opportunity_id = str(meta.get("opportunity_id") or parts[1] or "").strip()
        object_name = "/".join(parts[4:]).strip()
        if not opportunity_id or not object_name:
            return None
        return opportunity_id, object_name
    if body.get("event") == "document_deleted":
        oid = body.get("opportunity_id")
        oname = body.get("object_name")
        if oid and oname:
            return str(oid).strip(), str(oname).strip()
    return None


class PubsubPipeline:
    """Scans GCS processed/ objects and publishes RAG ingestion events to Pub/Sub."""

    def __init__(self, storage: Storage | None = None) -> None:
        self._storage = storage or Storage()

    def _get_topic_name(self, source: str) -> str:
        """Return the Pub/Sub topic name. All sources publish to rag-ingestion-queue."""
        return get_settings().ingestion.pubsub_topic_rag_ingestion

    def _parse_processed_document_gs_uri(
        self, gs_uri: str
    ) -> tuple[str, str, str] | None:
        """Parse gs://bucket/opp/processed/documents/object_name → (bucket, opportunity_id, object_name)."""
        s = (gs_uri or "").strip()
        if not s.startswith("gs://"):
            return None
        parts = s[5:].split("/")
        if len(parts) < 5 or parts[2] != "processed" or parts[3] != "documents":
            return None
        bucket, opp = parts[0], parts[1]
        object_name = "/".join(parts[4:])
        if not bucket or not opp or not object_name:
            return None
        return bucket, opp, object_name

    def _build_message(
        self,
        bucket: str,
        opportunity_id: str,
        source: str,
        object_name: str,
        action_type: Literal[
            "document_ingested", "document_deleted"
        ] = "document_ingested",
    ) -> dict:
        """Build a structured Pub/Sub message for a single processed GCS object."""
        gcs_path = f"{opportunity_id}/processed/{source}/{object_name}"
        filename = object_name.rsplit("/", maxsplit=1)[-1]
        msg: dict[str, Any] = {
            "action_type": action_type,
            "source_type": _SOURCE_TYPE_MAP.get(source, source),
            "data_path": f"gs://{bucket}/{gcs_path}",
            "metadata": {
                "opportunity_id": opportunity_id,
                "channel": "gdrive" if filename.startswith("drive_") else "raw",
                "source_id": filename,
                "document_id": gcs_path,
            },
        }
        if action_type == "document_ingested":
            msg["ingestion_type"] = "file"
        return msg

    def _should_dispatch(self, source: str, object_name: str) -> bool:
        """Return True if this object should be dispatched to Pub/Sub."""
        if source in ("zoom_transcripts", "slack_messages", "gmail_messages"):
            filename = object_name.rsplit("/", maxsplit=1)[-1]
            return filename.lower().endswith(".txt")
        return True

    def publish_deletions_via_dispatch(
        self,
        dispatch_url: str,
        deleted_uris: list[str],
        *,
        identity_token: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> list[dict[str, Any]]:
        """For each orphan-deleted gs:// URI, HTTP POST to pubsub-dispatch. Returns per-URI results."""
        url = (dispatch_url or "").strip().rstrip("/")
        if not url:
            return [
                {"gs_uri": uri, "ok": False, "error": "PUBSUB_DISPATCH_URL empty"}
                for uri in deleted_uris
            ]

        if identity_token:
            token = identity_token
        else:
            try:
                token = id_token.fetch_id_token(GoogleAuthRequest(), url)
            except Exception as e:
                logger.exception("publish_deletions_via_dispatch: id_token failed")
                return [
                    {
                        "gs_uri": uri,
                        "ok": False,
                        "message": str(e),
                        "dispatch_response": {},
                    }
                    for uri in deleted_uris
                ]

        results: list[dict[str, Any]] = []
        for gs_uri in deleted_uris:
            parsed = self._parse_processed_document_gs_uri(gs_uri)
            if not parsed:
                results.append({
                    "gs_uri": gs_uri,
                    "ok": False,
                    "error": "unparseable_uri",
                })
                continue
            bucket, opp, oname = parsed

            payload = self._build_message(
                bucket, opp, "documents", oname, action_type="document_deleted"
            )
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    timeout=timeout_seconds,
                )
            except requests.RequestException as e:
                logger.warning(
                    "publish_deletions_via_dispatch: POST failed — opportunity_id=%s object_name=%s error=%s",
                    opp,
                    oname,
                    e,
                )
                results.append({
                    "gs_uri": gs_uri,
                    "ok": False,
                    "message": str(e),
                    "dispatch_response": {},
                })
                continue

            try:
                body = resp.json() if resp.content else {}
            except json.JSONDecodeError:
                body = {"raw": (resp.text[:500] if resp.text else "")}

            if resp.status_code == 200 and body.get("published") is True:
                results.append({
                    "gs_uri": gs_uri,
                    "ok": True,
                    "message": "published",
                    "dispatch_response": body,
                })
            else:
                logger.warning(
                    "publish_deletions_via_dispatch: unexpected response status=%s body=%s",
                    resp.status_code,
                    body,
                )
                results.append({
                    "gs_uri": gs_uri,
                    "ok": False,
                    "message": f"HTTP {resp.status_code}: {body}",
                    "dispatch_response": body,
                })

        return results

    def run(
        self,
        opportunity_id: str | None = None,
        lookback_minutes: int = 15,
        deletion_payloads: list[dict] | None = None,
        run_ingestion_scan: bool = True,
    ) -> list[str]:
        """Publish to rag-ingestion-queue: optional deletion payloads, then scan GCS for ingestion.

        Args:
            opportunity_id: Scope scan to a single opportunity.
            lookback_minutes: Scan files created in the last N minutes (ignored if run_ingestion_scan=False).
            deletion_payloads: document_deleted bodies to publish (from gcs-file-processor POST).
            run_ingestion_scan: If False, skip GCS scan (deletion-only run).

        Returns:
            List of Pub/Sub message IDs published.
        """
        message_ids: list[str] = []
        extras = {"opportunity_id": opportunity_id} if opportunity_id else {}
        topic_name = self._get_topic_name("documents")
        publishers: dict[str, Publisher] = {topic_name: Publisher(topic=topic_name)}

        # 1. Publish deletion payloads first (if any)
        if deletion_payloads:
            logger.info(
                "Pubsub pipeline run started — publishing %d deletion(s)",
                len(deletion_payloads),
            )
            for payload in deletion_payloads:
                parsed = parse_document_deleted_pubsub_body(payload)
                opp = (parsed[0] if parsed else "") or (
                    payload.get("metadata") or {}
                ).get("opportunity_id", "")
                obj_name = (parsed[1] if parsed else "") or (
                    payload.get("metadata") or {}
                ).get("source_id", "")
                try:
                    msg_id = publishers[topic_name].publish(payload, opportunity_id=opp)
                    message_ids.append(msg_id)
                    logger.bind(
                        opportunity_id=opp,
                        document_file=obj_name,
                        pubsub_message_id=msg_id,
                    ).info(
                        "DOCUMENT_DELETION_PUSH_OK — message_id=%s document_file=%s opportunity_id=%s",
                        msg_id,
                        obj_name,
                        opp,
                    )
                except Exception as e:
                    logger.bind(opportunity_id=opp, document_file=obj_name).exception(
                        "DOCUMENT_DELETION_PUSH_FAILED — document_file=%s opportunity_id=%s error=%s",
                        obj_name,
                        opp,
                        e,
                    )
                    raise

        if not run_ingestion_scan:
            if deletion_payloads:
                logger.info(
                    "Pubsub pipeline complete — %d deletion(s) published",
                    len(message_ids),
                )
            return message_ids

        # 2. Scan GCS and publish ingestion
        settings = get_settings()
        bucket_name = settings.ingestion.gcs_bucket_ingestion
        since: datetime | None = None
        logger.bind(**extras).info("Pubsub pipeline run started")
        if lookback_minutes > 0:
            since = datetime.now(UTC) - timedelta(minutes=lookback_minutes)

        all_objects = self._storage.list_all_processed(
            opportunity_id=opportunity_id, since=since
        )

        for opp_id, source, object_name in all_objects:
            opp_extras = {"opportunity_id": opp_id}
            if source not in _SOURCE_TYPE_MAP:
                logger.debug("Skipping unsupported source directory", extra=opp_extras)
                continue

            if not self._should_dispatch(source, object_name):
                logger.debug(
                    "Skipping non-txt file",
                    extra=opp_extras,
                )
                continue

            topic_name = self._get_topic_name(source)
            if topic_name not in publishers:
                publishers[topic_name] = Publisher(topic=topic_name)

            try:
                message = self._build_message(bucket_name, opp_id, source, object_name)
                message_id = publishers[topic_name].publish(
                    message, opportunity_id=opp_id
                )
                message_ids.append(message_id)
                logger.info(
                    "Published RAG ingestion event",
                    extra=opp_extras,
                )
            except Exception:
                logger.error(
                    "Failed to publish RAG ingestion event",
                    exc_info=True,
                    extra=opp_extras,
                )
                raise

        logger.bind(**extras).info("Pubsub pipeline complete")
        return message_ids


__all__ = ["PubsubPipeline", "parse_document_deleted_pubsub_body"]
