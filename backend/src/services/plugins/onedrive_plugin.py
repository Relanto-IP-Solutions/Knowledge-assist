"""OneDrive plugin: find project folders and sync files to GCS raw/onedrive."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import httpx
from sqlalchemy.orm import Session

from configs.settings import get_settings
from src.services.database_manager.models.auth_models import OpportunitySource, User
from src.services.database_manager.user_connection_utils import get_active_connection
from src.services.storage.service import Storage
from src.utils.logger import get_logger
from src.utils.opportunity_id import gcs_opportunity_prefix, normalize_opportunity_oid


logger = get_logger(__name__)
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_OID_PREFIX_RE = re.compile(r"oid(\d+)", re.IGNORECASE)


def _resolve_onedrive_user(db: Session, source: OpportunitySource) -> User | None:
    opp = source.opportunity
    owner = opp.owner
    if owner and get_active_connection(db, owner.id, "onedrive"):
        return owner
    return None


async def _get_graph_access_token(refresh_token: str) -> str | None:
    ms = get_settings().onedrive
    client_id = (ms.client_id or "").strip()
    client_secret = (ms.client_secret or "").strip()
    tenant_id = (ms.tenant_id or "common").strip() or "common"
    if not (client_id and client_secret and refresh_token):
        return None

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            token_url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "offline_access openid profile Files.Read",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code != 200:
        logger.warning("OneDrive token refresh failed: status={}", resp.status_code)
        return None
    data = resp.json()
    return (data.get("access_token") or "").strip() or None


def _project_folder_matches(folder_name: str, oid: str) -> bool:
    name = (folder_name or "").strip()
    if not name:
        return False
    try:
        # Exact canonical folder names (e.g., "oid10034") should match directly.
        return normalize_opportunity_oid(name) == oid
    except ValueError:
        m = _OID_PREFIX_RE.search(name)
        if not m:
            return False
        try:
            return normalize_opportunity_oid(m.group(0)) == oid
        except ValueError:
            return False


async def find_onedrive_project_folder(
    token: str,
    opportunity_id_str: str,
) -> tuple[str | None, str | None]:
    """Find OneDrive folder using direct root path check, then global search fallback."""
    try:
        oid = normalize_opportunity_oid(opportunity_id_str)
    except ValueError:
        return None, None

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        logger.info("OneDrive: Checking root for direct path match: {}", oid)
        direct_url = f"{GRAPH_BASE}/me/drive/root:/{oid}?$select=id,name,folder"
        direct_resp = await client.get(direct_url, headers=headers)
        if direct_resp.status_code == 200:
            item = direct_resp.json()
            if item.get("folder") and _project_folder_matches(item.get("name") or "", oid):
                logger.info("OneDrive: Direct match found!")
                return (item.get("id") or None), (item.get("name") or oid)
        logger.info("OneDrive: Direct match failed, falling back to global search.")

        next_url = (
            f"{GRAPH_BASE}/me/drive/root/search(q='{oid}')"
            "?$top=200&select=id,name,folder"
        )
        logger.info("OneDrive search: oid={} url={}", oid, next_url)
        candidates: list[dict] = []
        while next_url:
            resp = await client.get(next_url, headers=headers)
            if resp.status_code != 200:
                logger.warning(
                    "OneDrive recursive search failed: status={}", resp.status_code
                )
                return None, None
            data = resp.json()
            logger.info(
                "OneDrive search page scanned: oid={} items={}",
                oid,
                len(data.get("value") or []),
            )
            for item in data.get("value") or []:
                if item.get("folder") and _project_folder_matches(item.get("name") or "", oid):
                    candidates.append(item)
            next_url = data.get("@odata.nextLink")

    if not candidates:
        return None, None
    candidates.sort(key=lambda x: (x.get("name") or "").lower())
    folder = candidates[0]
    return (folder.get("id") or None), (folder.get("name") or oid)


async def _list_files_recursive(
    client: httpx.AsyncClient,
    headers: dict,
    folder_id: str,
) -> list[dict]:
    out: list[dict] = []
    queue = [folder_id]
    while queue:
        current = queue.pop(0)
        logger.info("OneDrive sync: scanning folder_id={}", current)
        next_url = (
            f"{GRAPH_BASE}/me/drive/items/{current}/children"
            "?$top=200&$select=id,name,lastModifiedDateTime,file,folder"
        )
        while next_url:
            resp = await client.get(next_url, headers=headers)
            if resp.status_code != 200:
                logger.warning(
                    "OneDrive list folder children failed: folder_id={} status={}",
                    current,
                    resp.status_code,
                )
                break
            data = resp.json()
            for item in data.get("value") or []:
                if item.get("folder"):
                    child_id = (item.get("id") or "").strip()
                    if child_id:
                        queue.append(child_id)
                elif item.get("file"):
                    out.append(item)
            next_url = data.get("@odata.nextLink")
    return out


async def sync_onedrive_source(db: Session, source: OpportunitySource) -> int:
    """Sync files from pinned OneDrive folder to GCS raw/onedrive."""
    opp = source.opportunity
    user = _resolve_onedrive_user(db, source)
    if not user:
        logger.warning("Sync skipped: User has not connected their OneDrive account.")
        return 0

    conn = get_active_connection(db, user.id, "onedrive")
    if not conn or not (conn.refresh_token or "").strip():
        logger.warning("OneDrive sync: user {} has no active refresh token", user.id)
        return 0

    access_token = await _get_graph_access_token(conn.refresh_token)
    if not access_token:
        logger.warning("OneDrive sync: failed to refresh token for user {}", user.id)
        return 0

    pinned_folder_id = (source.channel_id or "").strip()
    if not pinned_folder_id:
        pinned_folder_id, pinned_name = await find_onedrive_project_folder(
            access_token, str(opp.opportunity_id)
        )
        if not pinned_folder_id:
            logger.info(
                "OneDrive sync: no root folder found for opportunity_id={}",
                opp.opportunity_id,
            )
            return 0
        source.channel_id = pinned_folder_id
        logger.info(
            "OneDrive sync: pinned folder {} ({}) for opportunity_id={}",
            pinned_name,
            pinned_folder_id,
            opp.opportunity_id,
        )

    checkpoint_raw = {}
    try:
        checkpoint_raw = json.loads(source.sync_checkpoint) if source.sync_checkpoint else {}
    except Exception:
        checkpoint_raw = {}
    file_checkpoint: dict[str, str | None] = checkpoint_raw.get("files", {})

    storage = Storage()
    gcs_oid = gcs_opportunity_prefix(str(opp.opportunity_id))
    uploaded = 0

    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=120.0) as client:
        logger.info(
            "OneDrive sync: searching files under pinned_folder_id={} opportunity_id={}",
            pinned_folder_id,
            opp.opportunity_id,
        )
        files = await _list_files_recursive(client, headers, pinned_folder_id)
        logger.info(
            "OneDrive sync: discovered files count={} opportunity_id={}",
            len(files),
            opp.opportunity_id,
        )
        for item in files:
            file_id = (item.get("id") or "").strip()
            file_name = (item.get("name") or "").strip()
            modified_at = item.get("lastModifiedDateTime")
            if not file_id or not file_name:
                continue
            logger.info(
                "OneDrive sync: discovered file id={} name={} modified_at={}",
                file_id,
                file_name,
                modified_at,
            )
            if file_checkpoint.get(file_id) == modified_at:
                continue

            content_resp = await client.get(
                f"{GRAPH_BASE}/me/drive/items/{file_id}/content",
                headers=headers,
                follow_redirects=True,
            )
            if content_resp.status_code != 200:
                logger.warning(
                    "OneDrive download failed: file_id={} name={} status={} body={}",
                    file_id,
                    file_name,
                    content_resp.status_code,
                    (content_resp.text or "")[:500],
                )
                continue

            storage.write(
                tier="raw",
                opportunity_id=gcs_oid,
                source="onedrive",
                object_name=file_name,
                content=content_resp.content,
                content_type="application/octet-stream",
            )
            uploaded += 1
            file_checkpoint[file_id] = modified_at

    source.last_synced_at = datetime.now(UTC).replace(tzinfo=None)
    source.sync_checkpoint = json.dumps(
        {
            "folder_id": source.channel_id,
            "files": file_checkpoint,
        }
    )
    db.commit()
    logger.info(
        "OneDrive sync complete for opportunity_id={} uploaded_files={}",
        opp.opportunity_id,
        uploaded,
    )
    return uploaded
