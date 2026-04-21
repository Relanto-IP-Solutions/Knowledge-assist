"""CRON trigger endpoint to orchestrate plugin syncs."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload, sessionmaker

from configs.settings import get_settings
from src.apis.routes.drive_routes import discover_drive_folders_impl
from src.apis.routes.gmail_routes import discover_gmail_threads_impl
from src.apis.routes.slack_routes import discover_slack_channels_impl
from src.services.database_manager.models.auth_models import (
    Opportunity,
    OpportunitySource,
)
from src.services.database_manager.orm import get_db, get_engine
from src.services.database_manager.opportunity_state import (
    refresh_opportunity_pipeline_state,
)
from src.services.plugins.drive_plugin import sync_drive_source
from src.services.plugins.gmail_plugin import sync_gmail_source
from src.services.plugins.slack_plugin import sync_slack_source
from src.services.plugins.zoom_plugin import sync_zoom_source
from src.utils.logger import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/sync", tags=["sync"])


def _sync_single_source_worker(source_id: int) -> dict[str, Any]:
    """Run one opportunity_sources sync in its own DB session (safe for parallel execution)."""
    engine = get_engine()
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    source: OpportunitySource | None = None
    oid = "unknown"
    try:
        source = (
            db.query(OpportunitySource)
            .options(
                joinedload(OpportunitySource.opportunity).joinedload(
                    Opportunity.owner
                )
            )
            .filter(OpportunitySource.id == source_id)
            .first()
        )
        if not source:
            return {
                "opportunity_id": "unknown",
                "source_type": "?",
                "source_id": source_id,
                "items_synced": 0,
                "ok": False,
                "error": "source not found",
            }

        oid = _opportunity_id_str(source)
        oauth = get_settings().oauth_plugin
        google_client_id = oauth.google_client_id
        google_client_secret = oauth.google_client_secret

        count = 0
        if source.source_type == "gmail":
            count = sync_gmail_source(
                db, source, google_client_id, google_client_secret
            )
        elif source.source_type == "slack":
            count = asyncio.run(sync_slack_source(db, source))
        elif source.source_type == "drive":
            count = sync_drive_source(
                db, source, google_client_id, google_client_secret
            )
        elif source.source_type == "zoom":
            user = source.opportunity.owner
            zs = get_settings().zoom
            acc_id = (user.zoom_account_id or "").strip() or (zs.account_id or "").strip()
            client_id = (user.zoom_client_id or "").strip() or (zs.client_id or "").strip()
            client_secret = (user.zoom_client_secret or "").strip() or (
                zs.client_secret or ""
            ).strip()
            count = asyncio.run(
                sync_zoom_source(db, source, acc_id, client_id, client_secret)
            )
        else:
            logger.warning(
                "Unknown source_type {} for source id={}",
                source.source_type,
                source.id,
            )
            return {
                "opportunity_id": oid,
                "source_type": source.source_type,
                "source_id": source.id,
                "items_synced": 0,
                "ok": False,
                "error": f"unsupported source_type: {source.source_type}",
            }

        return {
            "opportunity_id": oid,
            "source_type": source.source_type,
            "source_id": source.id,
            "items_synced": count,
            "ok": True,
            "error": None,
        }
    except Exception as e:
        logger.exception(
            "Failed sync for source {} ({}): {}",
            source_id,
            getattr(source, "source_type", "?"),
            e,
        )
        st = getattr(source, "source_type", "?") if source else "?"
        return {
            "opportunity_id": oid,
            "source_type": st,
            "source_id": source_id,
            "items_synced": 0,
            "ok": False,
            "error": str(e),
        }
    finally:
        db.close()


def _opportunity_id_str(source: OpportunitySource) -> str:
    """Stable string for API responses; DB rows may have NULL/blank ``opportunity_id``."""
    opp = source.opportunity
    if not opp:
        return "unknown"
    raw = opp.opportunity_id
    if raw is None:
        return "unknown"
    s = str(raw).strip()
    return s or "unknown"


class SyncSourceResult(BaseModel):
    """One row per opportunity_sources row processed."""

    opportunity_id: str = Field(
        description="opportunities.opportunity_id (GCS folder key)."
    )
    source_type: str
    source_id: int
    items_synced: int = Field(
        description="Plugin-specific count (e.g. Slack: merged messages written to raw tier).",
    )
    ok: bool
    error: str | None = None


class SyncTriggerResponse(BaseModel):
    status: str
    message: str
    sources_total: int
    items_total: int
    results: list[SyncSourceResult]


class SyncRunResponse(BaseModel):
    """Response for /sync/run (discover + sync)."""

    status: str
    slack_discover: dict[str, Any]
    gmail_discover: dict[str, Any]
    drive_discover: dict[str, Any]
    sync: SyncTriggerResponse


async def run_sync_job(db: Session) -> dict[str, Any]:
    """Run sync for all opportunity sources; return summary for HTTP response."""
    sources = (
        db
        .query(OpportunitySource)
        .options(joinedload(OpportunitySource.opportunity))
        .all()
    )
    n = len(sources)
    logger.info("Starting scheduled sync for {} sources (parallel).", n)

    app = get_settings().app
    max_workers = min(app.sync_max_workers, max(1, n))
    source_ids = [s.id for s in sources]

    loop = asyncio.get_running_loop()
    if n == 0:
        results = []
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            tasks = [
                loop.run_in_executor(pool, _sync_single_source_worker, sid)
                for sid in source_ids
            ]
            results = await asyncio.gather(*tasks)

    results = sorted(results, key=lambda r: r["source_id"])
    total_synced = sum(r["items_synced"] for r in results if r.get("ok"))

    logger.info("Sync job complete. {} items pushed to raw GCS tier.", total_synced)

    synced_oids = {
        r["opportunity_id"]
        for r in results
        if r.get("ok") and r.get("opportunity_id") not in (None, "unknown")
    }
    for oid_str in synced_oids:
        refresh_opportunity_pipeline_state(oid_str, "sync")

    msg = (
        f"Processed {len(sources)} source(s); {total_synced} item(s) pushed to raw GCS tier."
        if sources
        else "No opportunity_sources rows — nothing to sync."
    )
    return {
        "status": "completed",
        "message": msg,
        "sources_total": len(sources),
        "items_total": total_synced,
        "results": results,
    }


@router.post("/trigger", response_model=SyncTriggerResponse)
async def trigger_sync(db: Annotated[Session, Depends(get_db)]):
    """Run plugin sync for all opportunity sources and return per–opportunity-id stats.

    The handler **waits** until sync finishes so the response can include counts per
    ``opportunity_id``. Long-running workspaces may increase request duration.
    """
    payload = await run_sync_job(db)
    return payload


@router.post("/run", response_model=SyncRunResponse)
async def run_discover_then_sync(db: Annotated[Session, Depends(get_db)]):
    """Run Slack, Gmail, and Drive discovery, then plugin sync.

    Order: Slack discover → Gmail discover → Drive discover → sync (all ``opportunity_sources``).
    Intended for Cloud Scheduler: one call, deterministic order.
    """
    slack_disc = discover_slack_channels_impl(db)
    gmail_disc = discover_gmail_threads_impl(db)
    discover = discover_drive_folders_impl(db)
    sync_payload = await run_sync_job(db)
    return {
        "status": "completed",
        "slack_discover": slack_disc.model_dump(),
        "gmail_discover": gmail_disc.model_dump(),
        "drive_discover": discover.model_dump(),
        "sync": sync_payload,
    }
