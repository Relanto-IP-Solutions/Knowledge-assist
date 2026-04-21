"""Admin + request workflow routes for opportunities.

This module hosts the opportunity-request approval workflow endpoints:
- POST /opportunities/create
- GET  /opportunities/requests
- POST /opportunities/requests
"""

import re
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


def _is_name_reserved(db: Session, title: str) -> bool:
    """True when name already exists or is pending approval."""
    existing_opportunity = db.execute(
        text("SELECT 1 FROM opportunities WHERE LOWER(name) = LOWER(:name) LIMIT 1"),
        {"name": title},
    ).first()
    if existing_opportunity:
        return True

    pending_request = db.execute(
        text(
            """
            SELECT 1
            FROM opportunity_requests
            WHERE LOWER(opportunity_title) = LOWER(:name)
              AND status = 'PENDING'
            LIMIT 1
            """
        ),
        {"name": title},
    ).first()
    return bool(pending_request)


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


class OpportunityNameExistsResponse(BaseModel):
    exists: bool


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
    if not re.match(r"^[A-Za-z0-9\- ]+$", title):
        raise HTTPException(
            status_code=400, detail="Only uppercase, lowercase, hyphen, and space are allowed."
        )
    if _is_name_reserved(db, title):
        raise HTTPException(
            status_code=409,
            detail="Opportunity name already exists or is already requested.",
        )

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


@router.get("/name-exists", response_model=OpportunityNameExistsResponse)
def opportunity_name_exists(
    name: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_existing_firebase_user)],
):
    """Check whether an opportunity name already exists (case-insensitive)."""
    _ = user  # auth required for parity with create endpoint
    title = (name or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="name is required.")
    if not re.match(r"^[A-Za-z0-9\- ]+$", title):
        raise HTTPException(
            status_code=400, detail="Only uppercase, lowercase, hyphen, and space are allowed."
        )

    return OpportunityNameExistsResponse(exists=_is_name_reserved(db, title))


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
            max_id_retries = 20
            for attempt in range(max_id_retries):
                try:
                    req = db.execute(
                        text(
                            """
                            SELECT request_id, user_id, opportunity_title, status
                            FROM opportunity_requests
                            WHERE request_id = :request_id
                            FOR UPDATE
                            """
                        ),
                        {"request_id": str(body.request_id)},
                    ).first()
                    if not req:
                        raise HTTPException(status_code=404, detail="Request not found.")
                    if str(req[3]).upper() != "PENDING":
                        raise HTTPException(status_code=409, detail="Request already reviewed.")

                    title = (str(req[2]) if req[2] is not None else "").strip()
                    if not title:
                        raise HTTPException(status_code=400, detail="name is required.")
                    if not re.match(r"^[A-Za-z0-9\- ]+$", title):
                        raise HTTPException(
                            status_code=400, detail="Invalid characters in name"
                        )

                    exists = db.execute(
                        text("SELECT 1 FROM opportunities WHERE LOWER(name) = LOWER(:name)"),
                        {"name": title},
                    ).first()
                    if exists:
                        raise HTTPException(
                            status_code=409, detail="Opportunity name already exists"
                        )

                    next_n_row = db.execute(
                        text("SELECT nextval('opportunity_oid_seq')")
                    ).first()
                    generated_oid = f"oid{int(next_n_row[0]):04d}"

                    opp_row = db.execute(
                        text(
                            """
                            INSERT INTO opportunities (
                                opportunity_id,
                                name,
                                owner_id,
                                status,
                                total_documents,
                                processed_documents
                            )
                            VALUES (
                                :opportunity_id,
                                :name,
                                :owner_id,
                                :status_discovered,
                                0,
                                0
                            )
                            RETURNING id, opportunity_id
                            """
                        ),
                        {
                            "opportunity_id": generated_oid,
                            "name": title,
                            "owner_id": int(req[1]),
                            "status_discovered": STATUS_DISCOVERED,
                        },
                    ).first()

                    row = db.execute(
                        text(
                            """
                            UPDATE opportunity_requests
                            SET
                                status = 'APPROVED',
                                admin_remarks = :admin_remarks,
                                reviewed_at = :reviewed_at,
                                reviewed_by = :reviewed_by,
                                created_opportunity_id = :created_opportunity_id
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
                            "created_opportunity_id": int(opp_row[0]),
                        },
                    ).first()
                    if not row:
                        raise HTTPException(status_code=409, detail="Request already reviewed.")
                    break
                except HTTPException:
                    raise
                except IntegrityError as exc:
                    db.rollback()
                    msg = str(exc).lower()
                    if ("name" in msg) or ("unique_opportunity_name" in msg):
                        raise HTTPException(
                            status_code=409, detail="Opportunity name already exists"
                        ) from None
                    if "opportunity_id" in msg:
                        # With nextval() collisions should be rare; if they keep happening,
                        # nudge the sequence forward to self-heal drift.
                        if (attempt + 1) % 5 == 0:
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
                            db.commit()
                        if attempt < (max_id_retries - 1):
                            logger.warning(
                                "opportunity_id collision on approval retry {}/{} request_id={}",
                                attempt + 1,
                                max_id_retries,
                                str(body.request_id),
                            )
                            continue
                        raise HTTPException(
                            status_code=503,
                            detail="Could not allocate a unique opportunity_id right now. Please retry.",
                        ) from None
                    if ("23505" not in msg) and ("duplicate key" not in msg):
                        raise
                    raise
                except DatabaseError:
                    db.rollback()
                    raise

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
                "created_opportunity_id": int(opp_row[0]),
                "opportunity_id": str(opp_row[1]),
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

