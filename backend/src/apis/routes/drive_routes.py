"""Google Drive discovery helpers (Requirements/<OID> -> DB upsert).

This endpoint is meant to remove manual SQL when new opportunity folders are created
under a shared Drive parent folder (e.g. Requirements/).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload, sessionmaker

from configs.settings import get_settings
from src.apis.deps.firebase_auth import get_firebase_user
from src.services.database_manager.models.auth_models import (
    Opportunity,
    OpportunitySource,
    User,
)
from src.services.database_manager.opportunity_state import STATUS_DISCOVERED
from src.services.database_manager.orm import get_db, get_engine
from src.services.database_manager.user_connection_utils import get_active_connection
from src.services.plugins import oauth_service
from src.services.plugins.drive_plugin import find_drive_project_folder, sync_drive_source
from src.services.storage.service import Storage
from src.utils.logger import get_logger
from src.utils.opportunity_id import find_opportunity_oid, gcs_opportunity_prefix, normalize_opportunity_oid


logger = get_logger(__name__)

router = APIRouter(prefix="/drive", tags=["drive"])
integrations_drive_router = APIRouter(prefix="/integrations/drive", tags=["drive"])


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
    try:
        return service.files().list(**kwargs).execute()
    except HttpError as exc:
        err = str(exc)
        if "failedPrecondition" in err:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Google Workspace domain policies are restricting access. "
                    "Your administrator has blocked Google Drive API access for this "
                    "account or OAuth app."
                ),
            ) from exc
        raise


class DriveDiscoverResponse(BaseModel):
    connector_user_email: str
    folders_total: int
    folders_parsed: int
    opportunities_created: int
    opportunity_sources_created: int
    skipped: list[str] = Field(
        default_factory=list,
        description="Folder names skipped (no opportunity id token like 'oid1234').",
    )
    mode: str = Field(
        default="user_scoped",
        description="Discovery mode (always user_scoped global Drive search).",
    )
    matched_folder_name: str | None = Field(
        default=None,
        description="First folder linked in user_scoped mode.",
    )


class DriveProfessionalConnectResponse(BaseModel):
    oid: str
    status: str = "ACTIVE"
    connected_user: str
    total_files: int
    files_uploaded: int
    matched_folder: str | None = None
    last_synced_at: str | None = None


def discover_drive_folders(
    db: Session,
    *,
    user: User | None,
    oid_filter: str | None = None,
) -> DriveDiscoverResponse:
    """Discover folders via global user-scoped Drive search.

    When ``oid_filter`` is set, surgically search for folders matching that OID only.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized: user is required.")

    service = _drive_service_for_user(db, user)
    supports_all_drives = bool(get_settings().drive.drive_supports_all_drives)
    mode = "user_scoped"

    folders_to_scan = []
    normalized_filter = normalize_opportunity_oid(oid_filter) if oid_filter else None

    if user and oid_filter:
        # Professional targeted discovery inside user's personal/shared drive
        folder_id, folder_name = find_drive_project_folder(
            service, normalized_filter, supports_all_drives=supports_all_drives
        )
        if folder_id:
            folders_to_scan = [{"id": folder_id, "name": folder_name}]
    else:
        # Default to global user-scoped search across full Drive visibility.
        query = (
            "mimeType = 'application/vnd.google-apps.folder' "
            "and name contains 'oid' "
            "and trashed = false"
        )
        folders_to_scan = _list_files(service, query, "files(id, name)").get("files", []) or []

    created_opps = 0
    created_sources = 0
    parsed = 0
    skipped: list[str] = []

    for f in folders_to_scan:
        name = (f.get("name") or "").strip()
        oid = find_opportunity_oid(name)
        if not oid:
            skipped.append(name or "(unnamed)")
            continue
        try:
            oid = normalize_opportunity_oid(oid)
        except ValueError:
            skipped.append(name)
            continue

        if normalized_filter and oid != normalized_filter:
            continue
            
        parsed += 1
        opp = db.query(Opportunity).filter(Opportunity.opportunity_id == oid).first()
        if not opp:
            opp = Opportunity(
                opportunity_id=oid,
                name=name or oid,
                owner_id=user.id,
                status=STATUS_DISCOVERED,
                total_documents=0,
                processed_documents=0,
            )
            db.add(opp)
            db.flush()
            created_opps += 1
        
        src = _ensure_drive_source(db, opp)
        if not src.id:
            created_sources += 1

    db.commit()

    return DriveDiscoverResponse(
        connector_user_email=user.email,
        folders_total=len(folders_to_scan),
        folders_parsed=parsed,
        opportunities_created=created_opps,
        opportunity_sources_created=created_sources,
        skipped=skipped,
        mode=mode,
        matched_folder_name=folders_to_scan[0]["name"] if folders_to_scan else None,
    )


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


def _drive_gcs_metrics_payload(storage: Storage, db: Session, oid: str):
    normalized_oid = normalize_opportunity_oid(oid)
    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == normalized_oid).first()
    if not opp:
        return {"total_files": 0, "status": "PENDING_AUTHORIZATION", "last_synced_at": None}
    
    source = (
        db.query(OpportunitySource)
        .filter(OpportunitySource.opportunity_id == opp.id, OpportunitySource.source_type == "drive")
        .first()
    )
    names = storage.list_objects("raw", normalized_oid, "drive")
    return {
        "total_files": len(names),
        "last_synced_at": (source.last_synced_at.isoformat() if source and source.last_synced_at else None),
        "status": (source.status if source else "PENDING_AUTHORIZATION"),
    }


@integrations_drive_router.get("/authorize-info/{oid}")
async def drive_authorize_info_integrations(
    oid: str,
    db: Annotated[Session, Depends(get_db)],
    user_email: str | None = Query(default=None),
    redirect_uri: str | None = Query(default=None),
):
    """Project-centric login check: returns true if the email has an active Drive connection."""
    normalized_oid = normalize_opportunity_oid(oid)
    stats = _drive_gcs_metrics_payload(Storage(), db, normalized_oid)
    
    email = (user_email or "").strip().lower()
    user = db.query(User).filter(User.email == email).first() if email else None
    
    conn = get_active_connection(db, user.id, "drive") if user else None
    has_conn = bool(conn and (conn.refresh_token or "").strip())
    
    auth_url = None
    if not has_conn and redirect_uri:
        # Build OAuth URL if not logged in
        state = oauth_service.build_google_oauth_state("drive", normalized_oid)
        auth_url = await oauth_service.get_google_auth_url(redirect_uri, provider="drive", state=state)
    
    return {
        "oid": normalized_oid,
        "status": stats["status"],
        "has_drive_connection": has_conn,
        "connector_user_email": (email if has_conn else None),
        "auth_url": auth_url,
        "message": "Login to Google Drive if has_drive_connection is false.",
    }


@integrations_drive_router.get("/metrics/{oid}")
def drive_metrics_integrations(
    oid: str,
    db: Annotated[Session, Depends(get_db)],
):
    storage = Storage()
    return _drive_gcs_metrics_payload(storage, db, oid)


@router.post("/discover", response_model=DriveDiscoverResponse)
def discover_drive_folders_endpoint(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_firebase_user)],
):
    return discover_drive_folders(db=db, user=user)


def discover_drive_folders_impl(db: Session) -> DriveDiscoverResponse:
    raise HTTPException(
        status_code=401,
        detail="Unauthorized: user is required for Drive discovery.",
    )


@integrations_drive_router.post("/connect/{oid}", response_model=DriveProfessionalConnectResponse)
async def drive_professional_connect_integrations(
    oid: str,
    db: Annotated[Session, Depends(get_db)],
    user_email: str | None = Query(default=None),
):
    """Professional ingestion: verify user + Drive OAuth, discover folder, ACTIVE, sync to GCS (awaited)."""
    try:
        normalized_oid = normalize_opportunity_oid(oid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Resolve identity by email (Non-Firebase matching Gmail flow)
    email = (user_email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="user_email query parameter is required.")
        
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User not found for email '{email}'. Login with Drive first.")

    conn = get_active_connection(db, user.id, "drive")
    if not conn or not (conn.refresh_token or "").strip():
        raise HTTPException(
            status_code=401,
            detail="Please login to your Google Drive first.",
        )

    try:
        discovery_result = discover_drive_folders(db, user=user, oid_filter=normalized_oid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == normalized_oid).first()
    if not opp:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No opportunity found for '{normalized_oid}'. "
                "Ensure a Drive folder name includes this project id (e.g. oid560, OID 560)."
            ),
        )

    source = _ensure_drive_source(db, opp)
    source.status = "ACTIVE"
    db.commit()

    source = (
        db.query(OpportunitySource)
        .options(joinedload(OpportunitySource.opportunity))
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "drive",
        )
        .first()
    )
    if not source or not source.opportunity:
        raise HTTPException(status_code=500, detail="Drive source missing after connect.")

    o = get_settings().oauth_plugin
    files_uploaded = sync_drive_source(db, source, o.google_client_id, o.google_client_secret, user)
    db.refresh(source)

    metrics = _drive_gcs_metrics_payload(Storage(), db, normalized_oid)
    return DriveProfessionalConnectResponse(
        oid=normalized_oid,
        status=str(metrics["status"]),
        connected_user=email,
        total_files=int(metrics["total_files"]),
        matched_folder=discovery_result.matched_folder_name,
        last_synced_at=metrics.get("last_synced_at"),
        files_uploaded=files_uploaded,
    )
