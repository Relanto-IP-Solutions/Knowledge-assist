"""SSE notification stream + REST digest for missed events (authenticated)."""

from __future__ import annotations

import asyncio
import queue
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.apis.deps.firebase_auth import get_existing_firebase_user
from src.apis.deps.rbac import is_admin
from src.services.database_manager.models.auth_models import User
from src.services.database_manager.orm import get_db
from src.services.notifications.hub import format_sse, subscribe, unsubscribe
from src.utils.logger import get_logger


logger = get_logger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _parse_after_iso(value: str | None) -> datetime:
    """Lower bound for digest queries (timezone-aware UTC)."""
    if value and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    return datetime.now(UTC) - timedelta(days=30)


class ReviewedDigestItem(BaseModel):
    type: str = Field(default="opportunity_request.reviewed")
    request_id: str
    status: str
    opportunity_title: str
    admin_remarks: str | None = None
    opportunity_id: str | None = None


class CreatedDigestItem(BaseModel):
    type: str = Field(default="opportunity_request.created")
    request_id: str
    submitter_user_id: int
    organization_name: str
    opportunity_title: str
    opportunity_id: str


class NotificationsDigestResponse(BaseModel):
    reviewed: list[ReviewedDigestItem]
    created: list[CreatedDigestItem]
    next_cursor: datetime


def _get_with_timeout(q: queue.Queue[bytes], timeout: float) -> bytes | None:
    try:
        return q.get(timeout=timeout)
    except queue.Empty:
        return None


@router.get("/digest", response_model=NotificationsDigestResponse)
def notifications_digest(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_existing_firebase_user)],
    after: str | None = Query(
        None,
        description="ISO-8601 lower bound; rows with reviewed_at/submitted_at strictly after this.",
    ),
):
    """Return opportunity-request activity since ``after`` (for when SSE was disconnected).

    - **reviewed**: this user's APPROVED/REJECTED rows (dashboard catch-up).
    - **created**: PENDING rows for **admins** only (admin queue catch-up).
    """
    uid = int(user.id)
    admin = bool(is_admin(user))
    after_dt = _parse_after_iso(after)
    now = datetime.now(UTC)

    reviewed_rows = db.execute(
        text(
            """
            SELECT
                r.request_id,
                r.status,
                r.opportunity_title,
                r.admin_remarks,
                o.opportunity_id AS opportunity_id
            FROM opportunity_requests r
            LEFT JOIN opportunities o ON o.id = r.created_opportunity_id
            WHERE r.user_id = :uid
              AND r.status IN ('APPROVED', 'REJECTED')
              AND r.reviewed_at IS NOT NULL
              AND r.reviewed_at > :after
            ORDER BY r.reviewed_at ASC
            LIMIT 100
            """
        ),
        {"uid": uid, "after": after_dt},
    ).all()

    reviewed: list[ReviewedDigestItem] = [
        ReviewedDigestItem(
            request_id=str(r[0]),
            status=str(r[1]),
            opportunity_title=str(r[2] or "").strip() or "Opportunity",
            admin_remarks=r[3],
            opportunity_id=str(r[4]) if r[4] is not None else None,
        )
        for r in reviewed_rows
    ]

    created: list[CreatedDigestItem] = []
    if admin:
        created_rows = db.execute(
            text(
                """
                SELECT
                    r.request_id,
                    r.user_id,
                    r.organization_name,
                    r.opportunity_title,
                    o.opportunity_id AS opportunity_id
                FROM opportunity_requests r
                LEFT JOIN opportunities o ON o.id = r.created_opportunity_id
                WHERE r.status = 'PENDING'
                  AND r.submitted_at > :after
                ORDER BY r.submitted_at ASC
                LIMIT 100
                """
            ),
            {"after": after_dt},
        ).all()
        created = [
            CreatedDigestItem(
                request_id=str(r[0]),
                submitter_user_id=int(r[1]),
                organization_name=str(r[2] or "").strip() or "",
                opportunity_title=str(r[3] or "").strip() or "Opportunity",
                opportunity_id=str(r[4]) if r[4] is not None else "",
            )
            for r in created_rows
        ]

    reviewed_meta = db.execute(
        text(
            """
            SELECT MAX(r.reviewed_at)
            FROM opportunity_requests r
            WHERE r.user_id = :uid
              AND r.status IN ('APPROVED', 'REJECTED')
              AND r.reviewed_at IS NOT NULL
              AND r.reviewed_at > :after
            """
        ),
        {"uid": uid, "after": after_dt},
    ).scalar()

    created_meta = None
    if admin:
        created_meta = db.execute(
            text(
                """
                SELECT MAX(r.submitted_at)
                FROM opportunity_requests r
                WHERE r.status = 'PENDING'
                  AND r.submitted_at > :after
                """
            ),
            {"after": after_dt},
        ).scalar()

    times: list[datetime] = [after_dt]
    if reviewed_meta is not None:
        t = reviewed_meta
        if getattr(t, "tzinfo", None) is None:
            t = t.replace(tzinfo=UTC)
        times.append(t.astimezone(UTC))
    if created_meta is not None:
        t = created_meta
        if getattr(t, "tzinfo", None) is None:
            t = t.replace(tzinfo=UTC)
        times.append(t.astimezone(UTC))

    if reviewed or created:
        next_cursor = max(times)
    else:
        next_cursor = max(after_dt, now)

    return NotificationsDigestResponse(
        reviewed=reviewed,
        created=created,
        next_cursor=next_cursor,
    )


@router.get("/stream")
async def notifications_stream(
    user: Annotated[User, Depends(get_existing_firebase_user)],
):
    """Server-Sent Events stream for the signed-in user.

    Admins are also registered for broadcast events (e.g. new opportunity requests).
    """
    uid = int(user.id)
    admin = bool(is_admin(user))
    q = subscribe(uid, is_admin=admin)
    logger.info(
        "notifications SSE subscribe user_id={} is_admin={} email={!r}",
        uid,
        admin,
        (user.email or "")[:120],
    )

    async def gen():
        try:
            yield format_sse(
                {"type": "connected", "user_id": uid, "is_admin": admin},
                event="notification",
            )
            while True:
                item = await asyncio.to_thread(_get_with_timeout, q, 25.0)
                if item is None:
                    yield b": ping\n\n"
                else:
                    yield item
        except asyncio.CancelledError:
            logger.info("notifications SSE cancelled user_id={}", uid)
            raise
        finally:
            unsubscribe(uid, q, is_admin=admin)
            logger.info("notifications SSE closed user_id={} is_admin={}", uid, admin)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
