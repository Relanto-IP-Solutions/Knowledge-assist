from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from src.services.database_manager.models.auth_models import Opportunity, OpportunitySource, User
from src.services.database_manager.opportunity_state import STATUS_DISCOVERED
from src.services.database_manager.orm import get_db, get_engine
from src.services.database_manager.user_connection_utils import get_active_connection
from src.services.plugins.onedrive_plugin import (
    find_onedrive_project_folder,
    sync_onedrive_source,
)
from src.services.storage import Storage
from src.utils.opportunity_id import gcs_opportunity_prefix, normalize_opportunity_oid


integrations_onedrive_router = APIRouter(
    prefix="/integrations/onedrive", tags=["onedrive"]
)


def _ensure_onedrive_source(
    db: Session, oid: str, owner: User
) -> tuple[Opportunity, OpportunitySource]:
    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == oid).first()
    if not opp:
        opp = Opportunity(
            opportunity_id=oid,
            name=oid,
            owner_id=owner.id,
            status=STATUS_DISCOVERED,
            total_documents=0,
            processed_documents=0,
        )
        db.add(opp)
        db.flush()

    source = (
        db.query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "onedrive",
        )
        .first()
    )
    if not source:
        source = OpportunitySource(
            opportunity_id=opp.id,
            source_type="onedrive",
            status="PENDING_AUTHORIZATION",
        )
        db.add(source)
        db.flush()
    return opp, source


async def _run_onedrive_sync_background(oid: str) -> None:
    with Session(get_engine()) as db:
        opp = db.query(Opportunity).filter(Opportunity.opportunity_id == oid).first()
        if not opp:
            return
        source = (
            db.query(OpportunitySource)
            .options(joinedload(OpportunitySource.opportunity).joinedload(Opportunity.owner))
            .filter(
                OpportunitySource.opportunity_id == opp.id,
                OpportunitySource.source_type == "onedrive",
            )
            .first()
        )
        if not source:
            return
        await sync_onedrive_source(db, source)


def _onedrive_files_uploaded_count(storage: Storage, oid: str) -> int:
    names = storage.list_objects("raw", gcs_opportunity_prefix(oid), "onedrive")
    return len(names)


@integrations_onedrive_router.post("/connect/{oid}")
async def connect_onedrive_project(
    oid: str,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    user_email: str | None = Query(default=None),
):
    normalized_oid = normalize_opportunity_oid(oid)
    email = (user_email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="user_email query parameter is required.")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User not found for email '{email}'.")

    conn = get_active_connection(db, user.id, "onedrive")
    if not conn or not (conn.refresh_token or "").strip():
        raise HTTPException(
            status_code=400,
            detail="No active OneDrive connection found for this user.",
        )

    _, source = _ensure_onedrive_source(db, normalized_oid, user)
    folder_id, _folder_name = await find_onedrive_project_folder(
        conn.access_token, normalized_oid
    )
    if not folder_id:
        raise HTTPException(
            status_code=404,
            detail=(
                f"We found your OneDrive, but we couldn't find a folder for {normalized_oid}. "
                "Please create it manually and click 'Retry Sync'."
            ),
        )

    source.channel_id = folder_id
    source.status = "ACTIVE"
    db.commit()
    background_tasks.add_task(_run_onedrive_sync_background, normalized_oid)
    return {
        "oid": normalized_oid,
        "status": "ACTIVE",
        "folder_id": folder_id,
        "sync_started": True,
    }


@integrations_onedrive_router.get("/metrics/{oid}")
def onedrive_metrics_for_project(
    oid: str,
    db: Annotated[Session, Depends(get_db)],
):
    normalized_oid = normalize_opportunity_oid(oid)
    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == normalized_oid).first()
    if not opp:
        return {
            "total_files": 0,
            "last_synced_at": None,
            "status": "PENDING_AUTHORIZATION",
        }

    source = (
        db.query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "onedrive",
        )
        .first()
    )
    storage = Storage()
    return {
        "total_files": _onedrive_files_uploaded_count(storage, normalized_oid),
        "last_synced_at": (
            source.last_synced_at.isoformat()
            if source and source.last_synced_at is not None
            else None
        ),
        "status": (source.status if source else "PENDING_AUTHORIZATION"),
    }


@integrations_onedrive_router.get("/authorize-info/{oid}")
def onedrive_authorize_info(
    oid: str,
    db: Annotated[Session, Depends(get_db)],
    user_email: str | None = Query(default=None),
):
    normalized_oid = normalize_opportunity_oid(oid)
    email = (user_email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="user_email query parameter is required.")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User not found for email '{email}'.")

    conn = get_active_connection(db, user.id, "onedrive")
    has_connection = bool(conn and (conn.refresh_token or "").strip())

    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == normalized_oid).first()
    source = None
    if opp:
        source = (
            db.query(OpportunitySource)
            .filter(
                OpportunitySource.opportunity_id == opp.id,
                OpportunitySource.source_type == "onedrive",
            )
            .first()
        )
    return {
        "oid": normalized_oid,
        "has_onedrive_connection": has_connection,
        "is_folder_pinned": bool(source and (source.channel_id or "").strip()),
    }
