"""Admin + request workflow routes for opportunities.

This module hosts the opportunity-request approval workflow endpoints:
- POST /opportunities/create
- GET  /opportunities/requests
- POST /opportunities/requests
"""

import time
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Session

from src.apis.deps.firebase_auth import get_existing_firebase_user
from src.apis.deps.rbac import is_admin
from src.services.database_manager.models.auth_models import Opportunity, User
from src.services.database_manager.opportunity_state import STATUS_DISCOVERED
from src.services.database_manager.orm import get_db
from src.utils.logger import get_logger


logger = get_logger(__name__)
router = APIRouter(prefix="/opportunities", tags=["opportunities"])


class CreateOpportunityBody(BaseModel):
    name: str = Field(..., min_length=1, description="Human-readable opportunity name.")


class CreateOpportunityResponse(BaseModel):
    request_id: uuid.UUID
    user_id: int
    opportunity_title: str
    submitted_at: datetime
    status: str


class OpportunityRequestOut(BaseModel):
    request_id: uuid.UUID
    user_id: int
    user_name: str | None = None
    opportunity_title: str
    submitted_at: datetime
    status: str
    admin_remarks: str | None = None
    reviewed_at: datetime | None = None
    reviewed_by: int | None = None
    created_opportunity_id: int | None = None


class OpportunityRequestsListResponse(BaseModel):
    requests: list[OpportunityRequestOut]


class ReviewOpportunityRequestBody(BaseModel):
    request_id: uuid.UUID
    status: str = Field(..., description="APPROVED or REJECTED")
    admin_remarks: str | None = None
    reviewed_at: datetime | None = None


@router.post("/create", response_model=CreateOpportunityResponse)
def create_opportunity_request(
    body: CreateOpportunityBody,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_existing_firebase_user)],
):
    """Submit an opportunity creation request for admin approval."""
    title = (body.name or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="name is required.")

    t0 = time.perf_counter()
    row = db.execute(
        text(
            """
            INSERT INTO opportunity_requests (user_id, opportunity_title, status)
            VALUES (:user_id, :title, 'PENDING')
            RETURNING request_id, submitted_at, status
            """
        ),
        {"user_id": int(user.id), "title": title},
    ).first()
    db.commit()

    logger.info(
        "create_opportunity_request timing | sql_ms={} user_id={} title_len={}",
        int((time.perf_counter() - t0) * 1000),
        int(user.id),
        len(title),
    )

    return CreateOpportunityResponse(
        request_id=row[0],
        user_id=int(user.id),
        opportunity_title=title,
        submitted_at=row[1],
        status=str(row[2]),
    )


@router.get("/requests", response_model=OpportunityRequestsListResponse)
def list_opportunity_requests(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_existing_firebase_user)],
    status: str | None = None,
    limit: int = 200,
):
    """List opportunity requests from `opportunity_requests` (admin-only)."""
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required.")

    limit = min(max(int(limit), 1), 2000)
    status_u = status.strip().upper() if status else None

    t0 = time.perf_counter()
    rows = db.execute(
        text(
            """
            SELECT
                r.request_id,
                r.user_id,
                u.name AS user_name,
                r.opportunity_title,
                r.submitted_at,
                r.status,
                r.admin_remarks,
                r.reviewed_at,
                r.reviewed_by,
                r.created_opportunity_id
            FROM opportunity_requests r
            JOIN users u ON u.id = r.user_id
            WHERE (CAST(:status AS VARCHAR) IS NULL OR r.status = CAST(:status AS VARCHAR))
            ORDER BY r.submitted_at DESC
            LIMIT :limit
            """
        ),
        {"status": status_u, "limit": limit},
    ).all()

    logger.info(
        "list_opportunity_requests timing | sql_ms={} rows={} status={!r} limit={}",
        int((time.perf_counter() - t0) * 1000),
        len(rows),
        status_u,
        limit,
    )

    return OpportunityRequestsListResponse(
        requests=[
            OpportunityRequestOut(
                request_id=r[0],
                user_id=int(r[1]),
                user_name=r[2],
                opportunity_title=str(r[3]),
                submitted_at=r[4],
                status=str(r[5]),
                admin_remarks=r[6],
                reviewed_at=r[7],
                reviewed_by=int(r[8]) if r[8] is not None else None,
                created_opportunity_id=int(r[9]) if r[9] is not None else None,
            )
            for r in rows
        ]
    )


@router.post("/requests")
def review_opportunity_request(
    body: ReviewOpportunityRequestBody,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_existing_firebase_user)],
):
    """Approve or reject an opportunity request (admin-only)."""
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required.")

    t_req0 = time.perf_counter()
    status_u = (body.status or "").strip().upper()
    if status_u not in {"APPROVED", "REJECTED"}:
        raise HTTPException(status_code=400, detail="status must be APPROVED or REJECTED.")

    remarks = (body.admin_remarks or "").strip() or None
    if status_u == "REJECTED" and not remarks:
        raise HTTPException(status_code=400, detail="admin_remarks is required for REJECTED.")

    reviewed_at = body.reviewed_at or datetime.now(UTC)
    reviewed_by = int(getattr(user, "id"))

    try:
        if status_u == "APPROVED":
            t_sql0 = time.perf_counter()
            for attempt in range(2):
                try:
                    row = db.execute(
                        text(
                            """
                            WITH req AS (
                                SELECT request_id, user_id, opportunity_title
                                FROM opportunity_requests
                                WHERE request_id = :request_id
                                FOR UPDATE
                            ),
                            opp AS (
                                INSERT INTO opportunities (
                                    name, owner_id, status, total_documents, processed_documents
                                )
                                SELECT
                                    req.opportunity_title,
                                    req.user_id,
                                    :status_discovered,
                                    0,
                                    0
                                FROM req
                                RETURNING id, opportunity_id
                            )
                            UPDATE opportunity_requests r
                            SET
                                status = 'APPROVED',
                                admin_remarks = :admin_remarks,
                                reviewed_at = :reviewed_at,
                                reviewed_by = :reviewed_by,
                                created_opportunity_id = opp.id
                            FROM req, opp
                            WHERE r.request_id = req.request_id
                              AND r.status = 'PENDING'
                            RETURNING r.request_id, opp.id AS created_opportunity_id, opp.opportunity_id
                            """
                        ),
                        {
                            "request_id": str(body.request_id),
                            "admin_remarks": remarks,
                            "reviewed_at": reviewed_at,
                            "reviewed_by": reviewed_by,
                            "status_discovered": STATUS_DISCOVERED,
                        },
                    ).first()
                    if not row:
                        exists = db.execute(
                            text(
                                "SELECT status FROM opportunity_requests WHERE request_id = :request_id"
                            ),
                            {"request_id": str(body.request_id)},
                        ).first()
                        if not exists:
                            raise HTTPException(status_code=404, detail="Request not found.")
                        raise HTTPException(status_code=409, detail="Request already reviewed.")
                    break
                except (IntegrityError, DatabaseError) as exc:
                    db.rollback()
                    msg = str(exc).lower()
                    if ("23505" not in msg) and ("duplicate key" not in msg):
                        raise
                    if attempt >= 1:
                        raise
                    db.execute(
                        text(
                            """
                            SELECT setval(
                                'opportunity_oid_seq',
                                COALESCE(
                                    (
                                        SELECT MAX(CAST(SUBSTRING(opportunity_id FROM 4) AS INTEGER))
                                        FROM opportunities
                                        WHERE opportunity_id ~ '^oid[0-9]+$'
                                    ),
                                    0
                                ) + 1,
                                false
                            )
                            """
                        )
                    )

            t_commit0 = time.perf_counter()
            db.commit()
            logger.info(
                "review_opportunity_request timing | sql_ms={} commit_ms={} total_ms={} status={}",
                int((time.perf_counter() - t_sql0) * 1000),
                int((time.perf_counter() - t_commit0) * 1000),
                int((time.perf_counter() - t_req0) * 1000),
                status_u,
            )
            return {
                "request_id": str(row[0]),
                "status": "APPROVED",
                "created_opportunity_id": int(row[1]),
                "opportunity_id": str(row[2]),
            }

        # REJECTED
        t_sql0 = time.perf_counter()
        row = db.execute(
            text(
                """
                UPDATE opportunity_requests
                SET
                    status = 'REJECTED',
                    admin_remarks = :admin_remarks,
                    reviewed_at = :reviewed_at,
                    reviewed_by = :reviewed_by
                WHERE request_id = :request_id
                  AND status = 'PENDING'
                RETURNING request_id
                """
            ),
            {
                "request_id": str(body.request_id),
                "admin_remarks": remarks,
                "reviewed_at": reviewed_at,
                "reviewed_by": reviewed_by,
            },
        ).first()
        if not row:
            exists = db.execute(
                text("SELECT status FROM opportunity_requests WHERE request_id = :request_id"),
                {"request_id": str(body.request_id)},
            ).first()
            if not exists:
                raise HTTPException(status_code=404, detail="Request not found.")
            raise HTTPException(status_code=409, detail="Request already reviewed.")

        t_commit0 = time.perf_counter()
        db.commit()
        logger.info(
            "review_opportunity_request timing | sql_ms={} commit_ms={} total_ms={} status={}",
            int((time.perf_counter() - t_sql0) * 1000),
            int((time.perf_counter() - t_commit0) * 1000),
            int((time.perf_counter() - t_req0) * 1000),
            status_u,
        )
        return {"request_id": str(row[0]), "status": "REJECTED"}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("review_opportunity_request failed")
        raise HTTPException(status_code=500, detail=str(exc)) from None

