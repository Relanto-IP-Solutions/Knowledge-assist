"""Drive Plugin service for fetching documents recursively and writing to GCS."""

import io
from datetime import datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from sqlalchemy.orm import Session

from configs.settings import get_settings
from src.services.database_manager.models.auth_models import OpportunitySource
from src.services.database_manager.user_connection_utils import get_active_connection
from src.services.plugins.google_connector_user import resolve_google_user_for_sync
from src.services.storage.service import Storage
from src.utils.logger import get_logger
from src.utils.opportunity_id import gcs_opportunity_prefix


logger = get_logger(__name__)


def _escape_drive_query_string(value: str) -> str:
    """Escape single quotes for Drive 'q' parameter."""
    # Drive query strings use single quotes; escape embedded quotes with a backslash.
    return (value or "").replace("'", "\\'")


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
    db: Session, source: OpportunitySource, client_id: str, client_secret: str
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
    user = resolve_google_user_for_sync(db, opp, provider="drive")
    if not user:
        logger.warning(
            "Drive sync: no user with active drive connection for opportunity_id={}",
            opp.opportunity_id,
        )
        return 0
    conn = get_active_connection(db, user.id, "drive")
    if not conn or not (conn.refresh_token or "").strip():
        logger.warning(
            "Drive sync: user {} has no active drive refresh token",
            user.id,
        )
        return 0
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

    settings = get_settings().drive
    supports_all_drives = bool(settings.drive_supports_all_drives)

    def _list_files(q: str, fields: str) -> dict:
        kwargs = {
            "q": q,
            "spaces": "drive",
            "fields": fields,
        }
        if supports_all_drives:
            kwargs.update({
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
            })
        return service.files().list(**kwargs).execute()

    # 1) Determine the folder to sync:
    #    - If DRIVE_ROOT_FOLDER_NAME is set: search within that root folder for a child folder containing the OID.
    #    - Else: fallback to the legacy behavior (any folder whose name contains the OID).
    root_name = (settings.drive_root_folder_name or "").strip()
    root_folder_id: str | None = None
    root_folder_display: str | None = None

    if root_name:
        root_name_esc = _escape_drive_query_string(root_name)
        q_root = (
            "mimeType = 'application/vnd.google-apps.folder' "
            f"and name = '{root_name_esc}' "
            "and trashed = false"
        )
        roots = _list_files(q_root, "files(id, name)")
        root_files = roots.get("files", []) or []
        if not root_files:
            logger.warning(
                "Drive root folder not found: {} (set DRIVE_ROOT_FOLDER_NAME or create it in Drive)",
                repr(root_name),
            )
            return 0
        parent_id = root_files[0]["id"]
        parent_name = root_files[0].get("name") or root_name

        q_child = (
            "mimeType = 'application/vnd.google-apps.folder' "
            f"and name contains '{_escape_drive_query_string(str(opp.opportunity_id))}' "
            f"and '{parent_id}' in parents "
            "and trashed = false"
        )
        children = _list_files(q_child, "files(id, name)")
        found_folders = children.get("files", []) or []
        if not found_folders:
            logger.info(
                "No Drive folder found under %r for opportunity_id: %s",
                parent_name,
                opp.opportunity_id,
            )
            return 0
        root_folder_id = found_folders[0]["id"]
        root_folder_display = f"{parent_name}/{found_folders[0].get('name')}"
    else:
        folder_query = (
            "mimeType = 'application/vnd.google-apps.folder' "
            f"and name contains '{_escape_drive_query_string(str(opp.opportunity_id))}' "
            "and trashed = false"
        )
        folders = _list_files(folder_query, "files(id, name)")
        found_folders = folders.get("files", []) or []
    if not found_folders:
        logger.info("No Drive folder found for opportunity_id: {}", opp.opportunity_id)
        return 0
    if root_folder_id is None:
        root_folder_id = found_folders[0]["id"]
        root_folder_display = found_folders[0].get("name") or "unknown"
    logger.info(
        "Found root folder {} with ID {}", repr(root_folder_display), root_folder_id
    )

    # 2. List all files recursively in that folder tree
    def list_files_in_folder(folder_id: str) -> list[dict]:
        all_files = []
        page_token = None

        while True:
            # Look for all files AND folders inside this directory
            query = f"'{folder_id}' in parents and trashed = false"
            kwargs = {
                "q": query,
                "spaces": "drive",
                "fields": "nextPageToken, files(id, name, mimeType, modifiedTime)",
                "pageToken": page_token,
            }
            if supports_all_drives:
                kwargs.update({
                    "supportsAllDrives": True,
                    "includeItemsFromAllDrives": True,
                })
            results = service.files().list(**kwargs).execute()
            items = results.get("files", [])
            for item in items:
                if item["mimeType"] == "application/vnd.google-apps.folder":
                    # Recurse into subdirectories
                    all_files.extend(list_files_in_folder(item["id"]))
                else:
                    all_files.append(item)

            page_token = results.get("nextPageToken")
            if not page_token:
                break
        return all_files

    files_to_sync = list_files_in_folder(root_folder_id)
    if not files_to_sync:
        logger.info(
            "Drive sync: no files under folder db_opp_id={} gcs_prefix={} root={}",
            opp.opportunity_id,
            gcs_opp_prefix,
            repr(root_folder_display),
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

            # Upload to GCS raw/ tier under documents source (use canonical oid prefix for path)
            storage.write(
                tier="raw",
                opportunity_id=gcs_opp_prefix,
                source="documents",  # the gcs_file_processor.py looks at 'documents' for PDFs/DOCXs
                object_name=file_name,
                content=fh.getvalue(),
                content_type="application/octet-stream",
            )
            count += 1
            new_checkpoint[file_id] = modified_time
            logger.info(
                "Drive→GCS uploaded db_opp_id={} gcs_prefix={} object=raw/documents/{}",
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
