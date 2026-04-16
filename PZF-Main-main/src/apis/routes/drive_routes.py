"""Google Drive discovery helpers (Requirements/<OID> -> DB upsert).

This endpoint is meant to remove manual SQL when new opportunity folders are created
under a shared Drive parent folder (e.g. Requirements/).
"""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import quote_plus

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import UTC, datetime
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, sessionmaker

from configs.settings import get_settings
from src.services.database_manager.models.auth_models import (
    Opportunity,
    OpportunitySource,
    User,
    UserConnection,
)
from src.services.database_manager.opportunity_state import STATUS_DISCOVERED
from src.services.database_manager.orm import get_db, get_engine
from src.services.database_manager.user_connection_utils import (
    get_active_connection,
    query_users_with_active_provider,
)
from src.services.plugins.drive_plugin import sync_drive_source
from src.services.storage.service import Storage
from src.utils.logger import get_logger
from src.utils.opportunity_id import find_opportunity_oid, normalize_opportunity_oid


logger = get_logger(__name__)

router = APIRouter(prefix="/drive", tags=["drive"])
dashboard_drive_router = APIRouter(tags=["drive"])


def _escape_drive_query_string(value: str) -> str:
    return (value or "").replace("'", "\\'")


def _get_connector_user(db: Session) -> User:
    """Pick the single Drive connector user with an active drive connection."""
    email = (get_settings().drive.drive_connector_user_email or "").strip().lower()
    now = datetime.now(UTC)

    # 1. If an email is hardcoded in .env, find that specific user
    if email:
        u = (
            db.query(User)
            .join(UserConnection, User.id == UserConnection.user_id)
            .filter(
                User.email == email,
                UserConnection.provider == "drive",
                or_(
                    UserConnection.expires_at.is_(None),
                    UserConnection.expires_at > now,
                ),
            )
            .first()
        )
        if not u:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"DRIVE_CONNECTOR_USER_EMAIL is set to {email!r} but no user with an "
                    "active drive connection was found."
                ),
            )
        return u

    # 2. Otherwise, pick the user belonging to the single most recent connection
    conn = (
        db.query(UserConnection)
        .filter(
            UserConnection.provider == "drive",
            or_(UserConnection.expires_at.is_(None), UserConnection.expires_at > now),
        )
        .order_by(UserConnection.id.desc())
        .first()
    )
    if not conn:
        raise HTTPException(
            status_code=400,
            detail=(
                "No active drive connection found. Complete Drive OAuth first "
                "(GET /auth/google/url?provider=drive -> POST /auth/google/callback)."
            ),
        )
    return conn.user


def _try_get_connector_user(db: Session) -> User | None:
    try:
        return _get_connector_user(db)
    except HTTPException:
        return None


def _drive_service_for_user(db: Session, user: User) -> Any:
    s = get_settings().oauth_plugin
    if (
        not (s.google_client_id or "").strip()
        or not (s.google_client_secret or "").strip()
    ):
        raise HTTPException(
            status_code=400,
            detail="GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are required.",
        )
    conn = get_active_connection(db=db, user_id=user.id, provider="drive")
    if not conn or not (conn.refresh_token or "").strip():
        raise HTTPException(
            status_code=400, detail=f"User {user.email!r} has no active drive refresh token."
        )
    creds = Credentials(
        token=None,
        refresh_token=conn.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=s.google_client_id,
        client_secret=s.google_client_secret,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    try:
        creds.refresh(GoogleRequest())
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Failed to refresh Drive credentials: {exc}"
        ) from exc
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _list_files(service: Any, q: str, fields: str) -> dict:
    ds = get_settings().drive
    kwargs = {"q": q, "spaces": "drive", "fields": fields}
    if ds.drive_supports_all_drives:
        kwargs.update({"supportsAllDrives": True, "includeItemsFromAllDrives": True})
    return service.files().list(**kwargs).execute()


class DriveDiscoverResponse(BaseModel):
    connector_user_email: str
    drive_root_folder_name: str
    folders_total: int
    folders_parsed: int
    opportunities_created: int
    opportunity_sources_created: int
    skipped: list[str] = Field(
        default_factory=list,
        description="Folder names skipped (no opportunity id token like 'oid1234').",
    )


@router.post("/discover", response_model=DriveDiscoverResponse)
def discover_drive_folders(db: Annotated[Session, Depends(get_db)]):
    """Discover subfolders under DRIVE_ROOT_FOLDER_NAME and upsert opportunities + drive sources.

    - Reads Drive using one connector user from ``user_connections(provider='drive')``.
    - Lists direct children under the Drive parent folder name (e.g. Requirements/).
    - Extracts opportunity id token from folder name (canonical: oid1234).
    - Upserts:
        - opportunities(opportunity_id, name, owner_id=connector_user)
        - opportunity_sources(opportunity_id, source_type='drive')
    This path is intentionally isolated from Gmail.

    After this, you can run POST /sync/trigger to upload raw/documents to GCS.
    """
    ds = get_settings().drive
    root_name = (ds.drive_root_folder_name or "").strip()
    if not root_name:
        raise HTTPException(
            status_code=400,
            detail="Set DRIVE_ROOT_FOLDER_NAME (e.g. Requirements) before using /drive/discover.",
        )

    connector = _get_connector_user(db)
    service = _drive_service_for_user(db, connector)

    q_root = (
        "mimeType = 'application/vnd.google-apps.folder' "
        f"and name = '{_escape_drive_query_string(root_name)}' "
        "and trashed = false"
    )
    roots = _list_files(service, q_root, "files(id, name)")
    root_files = roots.get("files", []) or []
    if not root_files:
        raise HTTPException(
            status_code=404, detail=f"Drive root folder not found: {root_name!r}"
        )
    root_id = root_files[0]["id"]

    q_children = (
        "mimeType = 'application/vnd.google-apps.folder' "
        f"and '{root_id}' in parents "
        "and trashed = false"
    )
    kids = _list_files(service, q_children, "files(id, name)")
    folders = kids.get("files", []) or []

    created_opps = 0
    created_sources = 0
    parsed = 0
    skipped: list[str] = []

    for f in folders:
        name = (f.get("name") or "").strip()
        oid = find_opportunity_oid(name)
        if not oid:
            skipped.append(name or "(unnamed)")
            continue
        oid = normalize_opportunity_oid(oid)
        parsed += 1

        opp = db.query(Opportunity).filter(Opportunity.opportunity_id == oid).first()
        if not opp:
            opp = Opportunity(
                opportunity_id=oid,
                name=name or oid,
                owner_id=connector.id,
                status=STATUS_DISCOVERED,
                total_documents=0,
                processed_documents=0,
            )
            db.add(opp)
            db.flush()
            created_opps += 1
        else:
            # Keep existing name/owner unless blank; do not override ownership unexpectedly.
            if not (opp.name or "").strip():
                opp.name = name or oid
            if not opp.owner_id:
                opp.owner_id = connector.id

        src = (
            db
            .query(OpportunitySource)
            .filter(
                OpportunitySource.opportunity_id == opp.id,
                OpportunitySource.source_type == "drive",
            )
            .first()
        )
        if not src:
            db.add(OpportunitySource(opportunity_id=opp.id, source_type="drive"))
            created_sources += 1

    db.commit()

    return DriveDiscoverResponse(
        connector_user_email=connector.email,
        drive_root_folder_name=root_name,
        folders_total=len(folders),
        folders_parsed=parsed,
        opportunities_created=created_opps,
        opportunity_sources_created=created_sources,
        skipped=skipped,
    )


def _drive_master_folder_url() -> str:
    ds = get_settings().drive
    if (ds.drive_master_folder_url or "").strip():
        return ds.drive_master_folder_url.strip()
        
    root = (ds.drive_root_folder_name or "").strip()
    if not root:
        return "https://drive.google.com/drive/my-drive"
    return f"https://drive.google.com/drive/search?q={quote_plus(root)}"


def _ensure_drive_source(db: Session, opp: Opportunity) -> OpportunitySource:
    source = (
        db.query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "drive",
        )
        .first()
    )
    if source:
        return source
    source = OpportunitySource(
        opportunity_id=opp.id,
        source_type="drive",
        status="PENDING_AUTHORIZATION",
    )
    db.add(source)
    db.flush()
    return source


def _SYNCLESS_DB_SESSION() -> Session:
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return SessionLocal()


def _run_drive_sync_background(oid: str) -> None:
    db = _SYNCLESS_DB_SESSION()
    try:
        opp = (
            db.query(Opportunity)
            .options(joinedload(Opportunity.sources))
            .filter(Opportunity.opportunity_id == oid)
            .first()
        )
        if not opp:
            return
        source = (
            db.query(OpportunitySource)
            .options(joinedload(OpportunitySource.opportunity))
            .filter(
                OpportunitySource.opportunity_id == opp.id,
                OpportunitySource.source_type == "drive",
            )
            .first()
        )
        if not source:
            return
        o = get_settings().oauth_plugin
        sync_drive_source(db, source, o.google_client_id, o.google_client_secret)
    except Exception:
        logger.exception("Drive authorize background sync failed for oid={}", oid)
    finally:
        db.close()


@dashboard_drive_router.get("/metrics/drive/{oid}")
def drive_metrics(
    oid: str,
    db: Annotated[Session, Depends(get_db)],
):
    normalized_oid = normalize_opportunity_oid(oid)
    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == normalized_oid).first()
    if not opp:
        raise HTTPException(status_code=404, detail=f"Opportunity not found for '{normalized_oid}'.")
    source = (
        db.query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "drive",
        )
        .first()
    )
    names = Storage().list_objects("raw", normalized_oid, "documents")
    return {
        "oid": normalized_oid,
        "total_files": len(names),
        "last_synced_at": (
            source.last_synced_at.isoformat() if source and source.last_synced_at else None
        ),
        "status": (source.status if source else "PENDING_AUTHORIZATION"),
    }


@dashboard_drive_router.get("/authorize-info/drive/{oid}")
def drive_authorize_info(
    oid: str,
    db: Annotated[Session, Depends(get_db)],
):
    normalized_oid = normalize_opportunity_oid(oid)
    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == normalized_oid).first()
    if not opp:
        raise HTTPException(status_code=404, detail=f"Opportunity not found for '{normalized_oid}'.")
    source = (
        db.query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "drive",
        )
        .first()
    )
    connector = _try_get_connector_user(db)
    has_conn = bool(
        connector and get_active_connection(db, connector.id, "drive")
    )
    ds = get_settings().drive
    root_name = (ds.drive_root_folder_name or "Requirements").strip()
    
    return {
        "oid": normalized_oid,
        "status": (source.status if source else "PENDING_AUTHORIZATION"),
        "has_drive_connection": has_conn,
        "connector_user_email": (connector.email if connector else None),
        "master_folder_url": _drive_master_folder_url(),
        "message": (
            f"Connecting will automatically fetch all documents from the folder named '{normalized_oid}' "
            f"within the shared '{root_name}' Google Drive. No personal files will be accessed."
        ),
    }


@dashboard_drive_router.post("/authorize/drive/{oid}")
def drive_authorize(
    oid: str,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
):
    normalized_oid = normalize_opportunity_oid(oid)
    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == normalized_oid).first()
    if not opp:
        raise HTTPException(status_code=404, detail=f"Opportunity not found for '{normalized_oid}'.")
    _get_connector_user(db)
    source = _ensure_drive_source(db, opp)
    source.status = "ACTIVE"
    db.commit()
    background_tasks.add_task(_run_drive_sync_background, normalized_oid)
    return {
        "oid": normalized_oid,
        "status": "ACTIVE",
        "sync_started": True,
        "message": "Drive source activated; sync started.",
    }


def discover_drive_folders_impl(db: Session) -> DriveDiscoverResponse:
    """Non-HTTP helper for orchestration endpoints (same behavior as POST /drive/discover)."""
    return discover_drive_folders(db=db)
