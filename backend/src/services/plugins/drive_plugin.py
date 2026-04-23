"""Drive Plugin service for fetching documents recursively and writing to GCS."""

import io
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from sqlalchemy.orm import Session

from configs.settings import get_settings
from src.services.database_manager.models.auth_models import OpportunitySource, User
from src.services.database_manager.user_connection_utils import get_active_connection
from src.services.storage.service import Storage
from src.utils.logger import get_logger
from src.utils.opportunity_id import find_opportunity_oid, gcs_opportunity_prefix, normalize_opportunity_oid


logger = get_logger(__name__)


def _escape_drive_query_string(value: str) -> str:
    """Escape single quotes for Drive 'q' parameter."""
    # Drive query strings use single quotes; escape embedded quotes with a backslash.
    return (value or "").replace("'", "\\'")


def drive_folder_name_matches_opportunity(folder_name: str, normalized_oid: str) -> bool:
    """True when the folder name parses to the same canonical opportunity id (flexible tokens)."""
    tok = find_opportunity_oid(folder_name or "")
    if not tok:
        return False
    try:
        return normalize_opportunity_oid(tok) == normalized_oid
    except ValueError:
        return False


def _drive_list_query_pages(
    service: Any, q: str, fields: str, supports_all_drives: bool
) -> list[dict]:
    out: list[dict] = []
    page_token = None
    while True:
        kwargs: dict = {
            "q": q,
            "spaces": "drive",
            "fields": fields,
            "pageToken": page_token,
        }
        kwargs["supportsAllDrives"] = True
        kwargs["includeItemsFromAllDrives"] = True
        r = service.files().list(**kwargs).execute()
        out.extend(r.get("files") or [])
        page_token = r.get("nextPageToken")
        if not page_token:
            break
    return out


def find_drive_project_folder(
    service: Any,
    opportunity_id_str: str,
    *,
    supports_all_drives: bool,
) -> tuple[str | None, str | None]:
    """Resolve the Drive folder id for an opportunity (shared root or user-drive flexible search)."""
    try:
        normalized_oid = normalize_opportunity_oid(opportunity_id_str)
    except ValueError:
        normalized_oid = (opportunity_id_str or "").strip()
    if not normalized_oid:
        return None, None

    # We now ignore DRIVE_ROOT_FOLDER_NAME for surgical discovery and search the whole Drive.

    digits = normalized_oid[3:] if normalized_oid.startswith("oid") else ""
    terms = [normalized_oid]
    if digits:
        terms.extend([f"oid {digits}", f"OID {digits}", f"Project {normalized_oid}"])
    seen: dict[str, dict] = {}
    for term in terms:
        qq = (
            "mimeType = 'application/vnd.google-apps.folder' "
            f"and name contains '{_escape_drive_query_string(term)}' "
            "and trashed = false"
        )
        for f in _drive_list_query_pages(
            service, qq, "nextPageToken, files(id, name)", supports_all_drives
        ):
            seen[f["id"]] = f
    matched = [
        f
        for f in seen.values()
        if drive_folder_name_matches_opportunity(f.get("name") or "", normalized_oid)
    ]
    matched.sort(key=lambda x: (x.get("name") or ""))
    if not matched:
        return None, None
    f0 = matched[0]
    return f0["id"], f0.get("name") or normalized_oid


def _get_credentials(
    refresh_token: str, client_id: str, client_secret: str
) -> Credentials | None:
    if not client_id or not client_secret:
        return None
    token = (refresh_token or "").strip()
    if not token:
        return None
    creds = Credentials(
        token=None,
        refresh_token=token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        # Must match scopes granted at OAuth (see oauth_service.get_google_auth_url). Do not add
        # drive.metadata.readonly here unless it is also added to the authorize URL — refresh
        # otherwise returns invalid_scope.
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    try:
        creds.refresh(Request())
        return creds
    except Exception as e:
        logger.warning("Failed to refresh Drive creds: {}", e)
        return None


def sync_drive_source(
    db: Session, source: OpportunitySource, client_id: str, client_secret: str, user: User | None = None
) -> int:
    """Sync Google Drive documents matching the OID and upload to GCS raw/."""
    opp = source.opportunity
    gcs_opp_prefix = gcs_opportunity_prefix(str(opp.opportunity_id))
    if gcs_opp_prefix != str(opp.opportunity_id).strip():
        logger.warning(
            "Drive sync: DB opportunity_id {} differs from canonical GCS prefix {} — "
            "writing under {} (Drive folder name may still be lowercase oid…).",
            repr(opp.opportunity_id),
            repr(gcs_opp_prefix),
            repr(gcs_opp_prefix),
        )
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Personal Drive connection required.",
        )
    conn = get_active_connection(db, user.id, "drive")
    if not conn or not (conn.refresh_token or "").strip():
        raise HTTPException(
            status_code=401,
            detail="Please login to your Google Drive first.",
        )
    creds = _get_credentials(conn.refresh_token, client_id, client_secret)
    if not creds:
        logger.warning(
            "Drive sync: failed to build credentials for user {} opportunity_id={}",
            user.id,
            opp.opportunity_id,
        )
        return 0

    try:
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        logger.exception("Failed to build Drive service: {}", e)
        return 0

    # 2. List all files recursively in that folder tree
    def list_files_in_folder(folder_id: str, path_breadcrumb: str, seen_ids: set[str] | None = None) -> list[dict]:
        if seen_ids is None:
            seen_ids = set()
            
        if folder_id in seen_ids:
            logger.warning("Drive sync: circular folder reference detected at {}", path_breadcrumb)
            return []
        seen_ids.add(folder_id)

        all_files = []
        page_token = None
        while True:
            # Look for all files AND folders inside this directory
            query = f"'{folder_id}' in parents and trashed = false"
            kwargs = {
                "q": query,
                "spaces": "drive",
                "fields": "nextPageToken, files(id, name, mimeType, modifiedTime, size)",
                "pageToken": page_token,
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            }
            try:
                results = service.files().list(**kwargs).execute()
            except Exception as e:
                logger.warning("Drive sync error listing folder {}: {}", folder_id, e)
                break

            items = results.get("files", [])
            for item in items:
                if item["mimeType"] == "application/vnd.google-apps.folder":
                    # Recurse into subdirectories
                    all_files.extend(list_files_in_folder(item["id"], f"{path_breadcrumb}/{item.get('name')}", seen_ids))
                else:
                    all_files.append(item)

            page_token = results.get("nextPageToken")
            if not page_token:
                break
        return all_files

    # Always search user's full visibility scope (My Drive + Shared Drives).
    supports_all_drives = True
    try:
        normalized_oid = normalize_opportunity_oid(str(opp.opportunity_id))
    except ValueError:
        normalized_oid = str(opp.opportunity_id).strip().lower()

    # 2) Candidate folder loop: try every OID-matching folder until one has files.
    digits = normalized_oid[3:] if normalized_oid.startswith("oid") else ""
    terms = [normalized_oid]
    if digits:
        terms.extend([f"oid {digits}", f"OID {digits}", f"Project {normalized_oid}"])
    seen: dict[str, dict] = {}
    for term in terms:
        qq = (
            "mimeType = 'application/vnd.google-apps.folder' "
            f"and name contains '{_escape_drive_query_string(term)}' "
            "and trashed = false"
        )
        for f in _drive_list_query_pages(
            service, qq, "nextPageToken, files(id, name)", supports_all_drives
        ):
            seen[f["id"]] = f
    candidates = [
        f
        for f in seen.values()
        if drive_folder_name_matches_opportunity(f.get("name") or "", normalized_oid)
    ]
    candidates.sort(key=lambda x: (x.get("name") or ""))
    if not candidates:
        logger.info("No Drive folder found for opportunity_id: {}", opp.opportunity_id)
        return 0

    files_to_sync: list[dict] = []
    root_folder_display = None
    for candidate in candidates:
        root_folder_id = candidate.get("id")
        root_folder_display = (candidate.get("name") or "").strip() or normalized_oid
        if not root_folder_id:
            continue
        logger.info(
            "Drive sync: trying candidate folder {} ({})",
            repr(root_folder_display),
            root_folder_id,
        )
        files_to_sync = list_files_in_folder(
            root_folder_id,
            f"/{root_folder_display or str(opp.opportunity_id)}",
        )
        if files_to_sync:
            logger.info(
                "Drive sync: selected non-empty candidate folder {} ({}) with files={}",
                repr(root_folder_display),
                root_folder_id,
                len(files_to_sync),
            )
            break
        logger.info(
            "Drive sync: candidate folder {} ({}) is empty; trying next.",
            repr(root_folder_display),
            root_folder_id,
        )

    if not files_to_sync:
        logger.info(
            "Drive sync: all candidate folders for {} are empty; uploaded=0",
            opp.opportunity_id,
        )
        return 0

    # Load previous sync checkpoint (used here as a dict of {file_id: last_modified_time})
    import json

    try:
        checkpoint = (
            json.loads(source.sync_checkpoint) if source.sync_checkpoint else {}
        )
    except Exception:
        checkpoint = {}

    logger.info(
        "Drive sync: db_opp_id={} gcs_prefix={} root={} files_seen={} "
        "checkpoint_file_ids={}",
        opp.opportunity_id,
        gcs_opp_prefix,
        repr(root_folder_display),
        len(files_to_sync),
        len(checkpoint),
    )

    storage = Storage()
    count = 0
    skipped_unchanged = 0
    skipped_unsupported_mime = 0
    # Only advance checkpoint for files we *successfully* uploaded.
    # Otherwise a transient GCS failure can cause future runs to skip files forever.
    new_checkpoint: dict[str, str | None] = dict(checkpoint)

    for file in files_to_sync:
        file_id = file["id"]
        file_name = file["name"]
        mime = file["mimeType"]
        modified_time = file.get("modifiedTime")  # e.g. "2024-01-01T12:00:00.000Z"

        # Skip if we already synced this exact version
        if checkpoint.get(file_id) == modified_time:
            skipped_unchanged += 1
            continue

        try:
            # Support Google Docs export to PDF
            if "google-apps" in mime:
                if mime in (
                    "application/vnd.google-apps.document",
                    "application/vnd.google-apps.presentation",
                    "application/vnd.google-apps.spreadsheet",
                ):
                    req = service.files().export_media(
                        fileId=file_id, mimeType="application/pdf"
                    )
                    file_name += ".pdf"
                else:
                    skipped_unsupported_mime += 1
                    logger.info(
                        "Drive sync: skip unsupported Google type db_opp_id={} file={} mime={}",
                        opp.opportunity_id,
                        file_name,
                        mime,
                    )
                    continue  # We don't export maps/drawings/etc right now
            else:
                # Regular file download
                req = service.files().get_media(fileId=file_id)

            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, req)
            done = False
            while done is False:
                _status, done = downloader.next_chunk()

            # Upload to GCS raw/ tier under drive source (use canonical oid prefix for path)
            storage.write(
                tier="raw",
                opportunity_id=gcs_opp_prefix,
                source="drive",
                object_name=file_name,
                content=fh.getvalue(),
                content_type="application/octet-stream",
            )
            count += 1
            new_checkpoint[file_id] = modified_time
            logger.info(
                "Drive→GCS uploaded db_opp_id={} gcs_prefix={} object=raw/drive/{}",
                opp.opportunity_id,
                gcs_opp_prefix,
                file_name,
            )

        except Exception as e:
            logger.exception("Failed to fetch file {}: {}", file_name, e)

    # Update Sync Tracker
    source.last_synced_at = datetime.utcnow()
    source.sync_checkpoint = json.dumps(new_checkpoint)
    db.commit()

    logger.info(
        "Drive sync complete: db_opp_id={} gcs_prefix={} uploaded_this_run={} "
        "files_seen={} skipped_unchanged_checkpoint={} skipped_unsupported_google_mime={}",
        opp.opportunity_id,
        gcs_opp_prefix,
        count,
        len(files_to_sync),
        skipped_unchanged,
        skipped_unsupported_mime,
    )
    return count
