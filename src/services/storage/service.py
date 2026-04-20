"""GCS storage service: read, write, delete, and list objects in the ingestion bucket."""

import contextlib
from datetime import datetime
from pathlib import Path
from typing import Literal

from google.cloud import storage as gcs
from google.cloud.exceptions import NotFound
from google.oauth2 import service_account

from configs.settings import get_settings
from src.utils.logger import get_logger
from src.utils.retry import retry_on_transient


logger = get_logger(__name__)

StorageTier = Literal["raw", "processed"]


def _blob_path(tier: str, opportunity_id: str, source: str, object_name: str) -> str:
    """Build path: {opportunity_id}/{tier}/{source}/{object_name}."""
    return f"{opportunity_id}/{tier}/{source}/{object_name}"


class Storage:
    """GCS bucket service. Path: {opportunity_id}/{tier}/{source}/{object_name}.

    tier is 'raw' (files as-is from source) or 'processed' (transformed content).
    Can be used across the project wherever bucket access is needed.
    """

    def __init__(self) -> None:
        self._bucket = None

    def _get_bucket(self):
        """Return the ingestion bucket."""
        if self._bucket is not None:
            return self._bucket
        settings = get_settings()
        bucket_name = (settings.ingestion.gcs_bucket_ingestion or "").strip()
        if not bucket_name:
            raise ValueError(
                "GCS_BUCKET_INGESTION is empty. Set it in configs/.env or configs/secrets/.env "
                "(e.g. eighth-bivouac-490806-s2-ingestion)."
            )
        key_path = (settings.ingestion.google_application_credentials or "").strip()
        if key_path:
            path_resolved = Path(key_path).expanduser().resolve()
            credentials = service_account.Credentials.from_service_account_file(
                str(path_resolved)
            )
            client = gcs.Client(
                project=settings.ingestion.gcp_project_id, credentials=credentials
            )
        else:
            client = gcs.Client(project=settings.ingestion.gcp_project_id)
        self._bucket = client.bucket(bucket_name)
        return self._bucket

    def write_response(
        self,
        opportunity_id: str,
        object_name: str,
        content: str | bytes,
        content_type: str | None = "application/json",
    ) -> str:
        """Write to {opportunity_id}/responses/{object_name}. Returns the GCS URI."""
        extras = {"opportunity_id": opportunity_id}
        try:
            return self._write_response_impl(
                opportunity_id, object_name, content, content_type, extras
            )
        except Exception:
            logger.bind(**extras).exception("Storage write_response failed")
            raise

    @retry_on_transient()
    def _write_response_impl(
        self,
        opportunity_id: str,
        object_name: str,
        content: str | bytes,
        content_type: str | None,
        extras: dict,
    ) -> str:
        bucket = self._get_bucket()
        path = f"{opportunity_id}/responses/{object_name}"
        blob = bucket.blob(path)
        data = content.encode("utf-8") if isinstance(content, str) else content
        blob.upload_from_string(data, content_type=content_type or "application/json")
        uri = f"gs://{bucket.name}/{path}"
        logger.bind(**extras).info("Wrote response object")
        return uri

    def list_response_objects(self, opportunity_id: str) -> list[str]:
        """Return filenames under ``{opportunity_id}/responses/`` (``oid_*_*_extract_*`` / ``oid_*_results_*``).

        Legacy objects may use older ``dor_*`` or ``opp_*`` prefixes.
        """
        return self._list_response_objects_impl(opportunity_id)

    @retry_on_transient()
    def _list_response_objects_impl(self, opportunity_id: str) -> list[str]:
        bucket = self._get_bucket()
        prefix = f"{opportunity_id}/responses/"
        blobs = bucket.list_blobs(prefix=prefix)
        names: list[str] = []
        for blob in blobs:
            if blob.name.endswith("/"):
                continue
            if blob.name.startswith(prefix) and len(blob.name) > len(prefix):
                names.append(blob.name[len(prefix) :])
        return sorted(names)

    def read_response_object(self, opportunity_id: str, object_name: str) -> bytes:
        """Read ``{opportunity_id}/responses/{object_name}``. Raises FileNotFoundError if missing."""
        extras = {"opportunity_id": opportunity_id}
        try:
            bucket = self._get_bucket()
            path = f"{opportunity_id}/responses/{object_name}"
            return self._read_blob_bytes(bucket, path)
        except NotFound as e:
            logger.debug("Response object not found", extra=extras)
            raise FileNotFoundError(
                f"Response object not found: gs://{bucket.name}/{path}"
            ) from e
        except Exception:
            logger.bind(**extras).exception("Storage read_response_object failed")
            raise

    def write(
        self,
        tier: StorageTier,
        opportunity_id: str,
        source: str,
        object_name: str,
        content: bytes | str,
        content_type: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Create or overwrite an object. Returns the GCS URI (gs://bucket/path)."""
        extras = {"opportunity_id": opportunity_id}
        try:
            return self._write_impl(
                tier,
                opportunity_id,
                source,
                object_name,
                content,
                content_type,
                metadata,
                extras,
            )
        except Exception:
            logger.error(
                "Storage write failed",
                exc_info=True,
                extra=extras,
            )
            raise

    @retry_on_transient()
    def _write_impl(
        self,
        tier: StorageTier,
        opportunity_id: str,
        source: str,
        object_name: str,
        content: bytes | str,
        content_type: str | None,
        metadata: dict | None,
        extras: dict,
    ) -> str:
        bucket = self._get_bucket()
        path = _blob_path(tier, opportunity_id, source, object_name)
        blob = bucket.blob(path)
        data = content.encode("utf-8") if isinstance(content, str) else content
        blob.upload_from_string(
            data,
            content_type=content_type or "application/octet-stream",
        )
        if metadata:
            blob.metadata = metadata
            blob.patch()
        uri = f"gs://{bucket.name}/{path}"
        logger.bind(**extras).info("Wrote object")
        return uri

    def read(
        self, tier: StorageTier, opportunity_id: str, source: str, object_name: str
    ) -> bytes:
        """Return object content. Raises FileNotFoundError if the object does not exist."""
        extras = {"opportunity_id": opportunity_id}
        try:
            bucket = self._get_bucket()
            path = _blob_path(tier, opportunity_id, source, object_name)
            data = self._read_blob_bytes(bucket, path)
            return data
        except NotFound as e:
            logger.bind(**extras).debug("Storage object not found")
            raise FileNotFoundError(
                f"Object not found: gs://{bucket.name}/{path}"
            ) from e
        except Exception:
            logger.bind(**extras).exception("Storage read failed")
            raise

    @retry_on_transient()
    def _read_blob_bytes(self, bucket, path: str) -> bytes:
        blob = bucket.blob(path)
        return blob.download_as_bytes()

    def delete(
        self, tier: StorageTier, opportunity_id: str, source: str, object_name: str
    ) -> None:
        """Delete an object. Idempotent: no error if the object does not exist.

        In versioned buckets, deletes all generations of the object so it no longer
        appears in the bucket (including archived versions).
        """
        bucket = self._get_bucket()
        path = _blob_path(tier, opportunity_id, source, object_name)
        extras = {"opportunity_id": opportunity_id}
        try:
            # List all versions of this object (versioned buckets may have multiple generations).
            iterator = bucket.list_blobs(prefix=path, versions=True)
            blobs_to_delete = [b for b in iterator if b.name == path]
            if not blobs_to_delete:
                # No versions found; try deleting current blob (handles non-versioned or missing).
                blob = bucket.blob(path)
                with contextlib.suppress(NotFound):
                    self._delete_blob(blob)
            else:
                for blob in blobs_to_delete:
                    self._delete_blob(blob)
            logger.bind(**extras).info("Deleted object")
        except NotFound:
            pass
        except Exception:
            logger.bind(**extras).exception("Storage delete failed")
            raise

    @retry_on_transient()
    def _delete_blob(self, blob) -> None:
        blob.delete()

    def list_objects(
        self, tier: StorageTier, opportunity_id: str, source: str
    ) -> list[str]:
        """Return object names under {opportunity_id}/{tier}/{source}/."""
        return self._list_objects_impl(tier, opportunity_id, source)

    @retry_on_transient()
    def _list_objects_impl(
        self, tier: StorageTier, opportunity_id: str, source: str
    ) -> list[str]:
        bucket = self._get_bucket()
        prefix = f"{opportunity_id}/{tier}/{source}/"
        blobs = bucket.list_blobs(prefix=prefix)
        return [blob.name[len(prefix) :] for blob in blobs if blob.name != prefix]

    def list_all_processed(
        self,
        opportunity_id: str | None = None,
        since: datetime | None = None,
    ) -> list[tuple[str, str, str]]:
        """Return objects in the processed tier as (opportunity_id, source, object_name) tuples.

        Args:
            opportunity_id: If provided, scope the scan to this opportunity only.
                            If None, scan all opportunities in the bucket.
            since: UTC-aware datetime; only blobs whose time_created is at or after
                   this value are returned. Pass None to return all blobs.

        Returns:
            List of (opportunity_id, source, object_name) for every matching blob under
            {opportunity_id}/processed/{source}/{object_name}.
        """
        return self._list_all_processed_impl(opportunity_id, since)

    @retry_on_transient()
    def _list_all_processed_impl(
        self,
        opportunity_id: str | None,
        since: datetime | None,
    ) -> list[tuple[str, str, str]]:
        bucket = self._get_bucket()
        prefix = f"{opportunity_id}/processed/" if opportunity_id else ""
        blobs = bucket.list_blobs(prefix=prefix or None)
        results: list[tuple[str, str, str]] = []
        for blob in blobs:
            # Skip GCS directory marker blobs (empty objects whose name ends with /)
            if blob.name.endswith("/"):
                continue
            # Apply time filter using blob.time_created (UTC-aware)
            if since is not None and blob.time_created < since:
                continue
            # Expected path: {opp_id}/processed/{source}/{object_name}
            parts = blob.name.split("/")
            if len(parts) < 4:
                continue
            opp_id, tier, source, *rest = parts
            if tier != "processed" or not rest:
                continue
            object_name = "/".join(rest)
            results.append((opp_id, source, object_name))
        return results

    def exists(
        self, tier: StorageTier, opportunity_id: str, source: str, object_name: str
    ) -> bool:
        """Return True if the object exists in GCS, False otherwise."""
        bucket = self._get_bucket()
        path = _blob_path(tier, opportunity_id, source, object_name)
        return bucket.blob(path).exists()

    def blob_size(
        self,
        tier: StorageTier,
        opportunity_id: str,
        source: str,
        object_name: str,
    ) -> int | None:
        """Return the size of the blob in bytes, or None if it does not exist."""
        bucket = self._get_bucket()
        path = _blob_path(tier, opportunity_id, source, object_name)
        blob = bucket.blob(path)
        try:
            return self._reload_blob_size(blob)
        except NotFound:
            return None

    @retry_on_transient()
    def _reload_blob_size(self, blob) -> int | None:
        blob.reload()
        return blob.size

    def blob_updated_at(
        self,
        tier: StorageTier,
        opportunity_id: str,
        source: str,
        object_name: str,
    ) -> datetime | None:
        """Return the last-updated UTC timestamp of an object, or None if it does not exist.

        Uses blob.updated (set by GCS on every write) rather than time_created so
        that re-uploads of the same object name are detected correctly.
        """
        bucket = self._get_bucket()
        path = _blob_path(tier, opportunity_id, source, object_name)
        blob = bucket.blob(path)
        try:
            return self._reload_blob_updated(blob)
        except NotFound:
            return None

    @retry_on_transient()
    def _reload_blob_updated(self, blob) -> datetime | None:
        blob.reload()
        return blob.updated

    def count_blobs_under_prefix(self, prefix: str) -> int:
        """Count non-directory objects under a bucket prefix (excludes trailing ``/`` markers)."""
        return self._count_blobs_under_prefix_impl(prefix)

    @retry_on_transient()
    def _count_blobs_under_prefix_impl(self, prefix: str) -> int:
        bucket = self._get_bucket()
        blobs = bucket.list_blobs(prefix=prefix or None)
        return sum(1 for b in blobs if not b.name.endswith("/"))

    def list_blobs_since(self, prefix: str, since: datetime | None = None) -> list[str]:
        """Return full blob names under prefix, optionally filtered to time_created >= since.

        Unlike list_objects(), this operates at the raw bucket level and returns
        full object paths (e.g. '{opp_id}/raw/zoom/meeting.vtt') rather than
        stripping a prefix. This allows the caller to extract the opportunity ID
        and source from the returned paths.

        Args:
            prefix: GCS path prefix to scope the listing (use "" for the whole bucket).
            since: UTC-aware datetime; only blobs created at or after this time are
                returned. Pass None to return all blobs under prefix.

        Returns:
            List of full object names (paths within the bucket).
        """
        return self._list_blobs_since_impl(prefix, since)

    @retry_on_transient()
    def _list_blobs_since_impl(self, prefix: str, since: datetime | None) -> list[str]:
        bucket = self._get_bucket()
        blobs = bucket.list_blobs(prefix=prefix or None)
        if since is None:
            return [blob.name for blob in blobs]
        return [blob.name for blob in blobs if blob.time_created >= since]
