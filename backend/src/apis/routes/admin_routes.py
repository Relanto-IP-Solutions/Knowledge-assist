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

from fastapi import APIRouter, Depends, HTTPException, Query
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

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _require_safe_identifier(kind: str, value: str) -> str:
    v = (value or "").strip()
    if not v:
        raise HTTPException(status_code=400, detail=f"{kind} is required.")
    if not _IDENT_RE.match(v):
        raise HTTPException(status_code=400, detail=f"Invalid {kind}.")
    return v


def _require_table_column_exist(db: Session, table: str, column: str) -> None:
    # Avoid leaking metadata from non-public schemas.
    row = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table
              AND column_name = :column
            LIMIT 1
            """
        ),
        {"table": table, "column": column},
    ).first()
    if not row:
        raise HTTPException(
            status_code=404, detail="Table/column not found in public schema."
        )


class GenericSearchResponse(BaseModel):
    rows: list[dict[str, object]]


def _run_generic_search(
    *,
    db: Session,
    table: str,
    column: str | None,
    query: str | None,
    limit: int | None,
) -> GenericSearchResponse:
    table_n = _require_safe_identifier("table", table)
    q = (query or "").strip() if query is not None else ""
    column_n: str | None = None
    if q:
        if column is None:
            raise HTTPException(status_code=400, detail="column is required when query is set.")
        column_n = _require_safe_identifier("column", column)

    limit_raw = 50 if limit is None else int(limit)
    limit_n = min(max(int(limit_raw), 1), 200)
    if column_n is not None:
        _require_table_column_exist(db, table_n, column_n)

    if column_n is not None and q:
        sql = text(
            f"""
            SELECT *
            FROM "{table_n}"
            WHERE CAST("{column_n}" AS TEXT) ILIKE :pattern
            LIMIT :limit
            """
        )
        params = {"pattern": f"%{q}%", "limit": limit_n}
    else:
        sql = text(
            f"""
            SELECT *
            FROM "{table_n}"
            LIMIT :limit
            """
        )
        params = {"limit": limit_n}

    rows = db.execute(sql, params).mappings().all()
    return GenericSearchResponse(rows=[dict(r) for r in rows])


def _require_columns_exist(db: Session, table: str, columns: list[str]) -> None:
    for c in columns:
        _require_table_column_exist(db, table, c)


def _parse_filter_expr(raw: str) -> tuple[str, str, str]:
    # Format: column|op|value
    parts = [p.strip() for p in (raw or "").split("|", 2)]
    if len(parts) != 3 or not parts[0] or not parts[1]:
        raise HTTPException(
            status_code=400, detail="Invalid filter format. Use: filter=column|op|value"
        )
    return parts[0], parts[1].lower(), parts[2]


def _build_advanced_search_sql(
    *,
    db: Session,
    table: str,
    filters: list[str],
    select: list[str] | None,
    group_by: list[str] | None,
    agg: str | None,
    order_by: list[str] | None,
    limit: int,
    offset: int,
) -> tuple[any, dict[str, object]]:
    table_n = _require_safe_identifier("table", table)

    select_cols = [(_require_safe_identifier("select", c), c) for c in (select or [])]
    group_cols = [(_require_safe_identifier("group_by", c), c) for c in (group_by or [])]

    where_clauses: list[str] = []
    params: dict[str, object] = {"limit": int(limit), "offset": int(offset)}
    referenced_cols: list[str] = []

    allowed_ops = {"=", "!=", "like", "ilike", "is", "isnot"}
    for i, f in enumerate(filters or []):
        col_raw, op, val = _parse_filter_expr(f)
        if op not in allowed_ops:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported op '{op}'. Allowed: {', '.join(sorted(allowed_ops))}",
            )
        col_n = _require_safe_identifier("column", col_raw)
        referenced_cols.append(col_n)
        vnorm = (val or "").strip().lower()
        if op in {"is", "isnot"}:
            if vnorm != "null":
                raise HTTPException(
                    status_code=400,
                    detail="For op 'is'/'isnot', value must be NULL. Example: filter=team_id|is|NULL",
                )
            where_clauses.append(
                f'"{col_n}" IS {"NOT " if op == "isnot" else ""}NULL'
            )
        else:
            pname = f"p{i}"
            # Type-safe across unknown schemas: compare on text representations.
            if op in {"like", "ilike"}:
                where_clauses.append(f'CAST("{col_n}" AS TEXT) {op.upper()} :{pname}')
                params[pname] = str(val)
            else:
                where_clauses.append(f'CAST("{col_n}" AS TEXT) {op} :{pname}')
                params[pname] = str(val)

    # Validate all referenced columns exist in public schema.
    need_cols = set(referenced_cols)
    need_cols.update([c for c, _ in select_cols])
    need_cols.update([c for c, _ in group_cols])
    _require_columns_exist(db, table_n, sorted(need_cols))

    # SELECT clause
    agg_n = (agg or "").strip().lower() or None
    select_sql: str
    if group_cols:
        if agg_n != "count":
            raise HTTPException(
                status_code=400,
                detail="When group_by is set, agg must be 'count' (for now).",
            )
        gb_cols_sql = ", ".join([f'"{c}"' for c, _ in group_cols])
        select_sql = f"{gb_cols_sql}, COUNT(*)::bigint AS count"
        group_by_sql = f" GROUP BY {gb_cols_sql}"
    else:
        group_by_sql = ""
        if agg_n is not None:
            raise HTTPException(
                status_code=400, detail="agg is only supported with group_by."
            )
        if select_cols:
            select_sql = ", ".join([f'"{c}"' for c, _ in select_cols])
        else:
            select_sql = "*"

    # ORDER BY clause
    order_sql = ""
    if order_by:
        order_parts: list[str] = []
        for ob in order_by:
            bits = [b.strip() for b in (ob or "").split("|", 1)]
            col = _require_safe_identifier("order_by", bits[0] if bits else "")
            direction = (bits[1].lower() if len(bits) == 2 else "asc").strip()
            if direction not in {"asc", "desc"}:
                raise HTTPException(
                    status_code=400, detail="order_by direction must be asc or desc."
                )
            # Ensure column exists
            _require_table_column_exist(db, table_n, col)
            order_parts.append(f'"{col}" {direction.upper()}')
        if order_parts:
            order_sql = " ORDER BY " + ", ".join(order_parts)

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sql = text(
        f"""
        SELECT {select_sql}
        FROM "{table_n}"
        {where_sql}
        {group_by_sql}
        {order_sql}
        LIMIT :limit OFFSET :offset
        """
    )
    return sql, params




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


@router.get("/search", response_model=GenericSearchResponse)
def generic_search(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_existing_firebase_user)],
    table: str = Query(..., description="Target table name (public schema only)."),
    column: str | None = Query(
        None, description="Target column name to search (required when query is set)."
    ),
    query: str | None = Query(None, description="Search query (substring match)."),
    filter: list[str] = Query(
        default_factory=list,
        description="Repeatable. Format: filter=column|op|value. Ops: =, !=, like, ilike. ANDed together.",
    ),
    select: list[str] | None = Query(
        None, description="Optional repeatable select columns: select=col&select=col2"
    ),
    group_by: list[str] | None = Query(
        None,
        description="Optional repeatable group_by columns (requires agg=count): group_by=col",
    ),
    agg: str | None = Query(
        None, description="Optional aggregate. Currently only supports agg=count with group_by."
    ),
    order_by: list[str] | None = Query(
        None, description="Optional repeatable. Format: order_by=column|asc (or |desc)"
    ),
    limit: int = 50,
    offset: int = 0,
):
    """Generic admin-only search across a table.

    Supports two modes on the same endpoint:
    - Simple mode: table + (optional) column + (optional) query (ILIKE)
    - Advanced mode: repeated filter params + optional select/group_by/agg/order_by/offset
    """
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required.")

    limit_n = min(max(int(limit), 1), 200)
    offset_n = max(int(offset), 0)

    # If any advanced parameter is used, switch to advanced builder.
    advanced_mode = bool(
        filter
        or select
        or group_by
        or (agg is not None)
        or order_by
        or (offset_n != 0)
    )
    if advanced_mode:
        sql, params = _build_advanced_search_sql(
            db=db,
            table=table,
            filters=filter,
            select=select,
            group_by=group_by,
            agg=agg,
            order_by=order_by,
            limit=limit_n,
            offset=offset_n,
        )
        rows = db.execute(sql, params).mappings().all()
        return GenericSearchResponse(rows=[dict(r) for r in rows])

    # Simple mode fallback.
    return _run_generic_search(
        db=db, table=table, column=column, query=query, limit=limit_n
    )


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

