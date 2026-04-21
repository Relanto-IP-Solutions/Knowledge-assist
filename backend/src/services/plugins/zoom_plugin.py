"""Zoom Plugin: orchestrate Zoom transcript sync via ZoomSyncService."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.services.database_manager.models.auth_models import OpportunitySource
from src.services.zoom.sync_service import ZoomSyncService
from src.utils.logger import get_logger


logger = get_logger(__name__)


class ZoomPlugin:
    """Delegates Zoom cloud recording sync to :class:`ZoomSyncService`."""

    def __init__(self) -> None:
        self.sync_service = ZoomSyncService()

    async def _sync_opportunity(
        self, opp_id: str, db: Session, since=None
    ) -> dict[str, Any]:
        """Sync transcripts for one opportunity OID (``since`` is reserved for future use)."""
        _ = since  # API compatibility; ZoomSyncService uses fixed lookback window.
        return await self.sync_service.sync_opportunity(opp_id, db=db)


async def sync_zoom_source(
    db: Session,
    source: OpportunitySource,
    account_id: str,
    client_id: str,
    client_secret: str,
) -> int:
    """Sync Zoom transcripts for a source row; delegate to :class:`ZoomPlugin` / :class:`ZoomSyncService`.

    ``account_id``, ``client_id``, and ``client_secret`` are kept for call-site
    compatibility; :meth:`ZoomSyncService.sync_opportunity` uses app settings.
    """
    _ = account_id, client_id, client_secret
    opp = source.opportunity
    try:
        result = await ZoomPlugin()._sync_opportunity(str(opp.opportunity_id), db)
        return int(result.get("items_synced", 0))
    except Exception as e:
        logger.warning("Zoom sync failed for opportunity_id=%s: %s", opp.opportunity_id, e)
        return 0
