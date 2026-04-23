from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Session

from src.apis.deps.firebase_auth import get_existing_firebase_user
from src.apis.deps.rbac import is_admin
from src.services.database_manager.models.auth_models import User
from src.services.database_manager.orm import get_db


router = APIRouter(prefix="/teams", tags=["teams"])


class TeamUserOut(BaseModel):
    id: int
    name: str | None = None
    email: str


class TeamMemberInput(BaseModel):
    user_id: int
    is_lead: bool = False


class TeamMemberOut(BaseModel):
    user_id: int
    name: str | None = None
    is_lead: bool


class TeamOut(BaseModel):
    id: int
    name: str
    is_active: bool
    created_at: datetime | None = None


class TeamDetailsResponse(BaseModel):
    team: TeamOut
    members: list[TeamMemberOut]
    opportunities: list[dict]


class CreateTeamBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=512)
    members: list[TeamMemberInput] = Field(default_factory=list)


class UpdateTeamBody(BaseModel):
    members: list[TeamMemberInput] = Field(default_factory=list)


class AssignOpportunitiesBody(BaseModel):
    opportunity_ids: list[int] = Field(..., min_length=1)
    allow_reassignment: bool = True


def _validate_team_members(members: list[TeamMemberInput]) -> list[int]:
    user_ids = [int(m.user_id) for m in members]
    if len(set(user_ids)) != len(user_ids):
        raise HTTPException(status_code=400, detail="Duplicate team members are not allowed")
    lead_count = sum(1 for m in members if m.is_lead)
    if lead_count > 2:
        raise HTTPException(status_code=400, detail="Max 2 leads allowed")
    return user_ids


def _ensure_admin(user: User) -> None:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required.")


def _sync_teams_id_sequence(db: Session) -> None:
    """Align teams.id sequence to current max(id)."""
    db.execute(
        text(
            """
            SELECT setval(
                pg_get_serial_sequence('teams', 'id'),
                COALESCE((SELECT MAX(id) FROM teams), 0) + 1,
                false
            )
            """
        )
    )
def _sync_team_members_id_sequence(db: Session) -> None:
    """Align team_members.id sequence to current max(id)."""
    db.execute(
        text(
            """
            SELECT setval(
                pg_get_serial_sequence('team_members', 'id'),
                COALESCE((SELECT MAX(id) FROM team_members), 0) + 1,
                false
            )
            """
        )
    )
def _create_team_row_with_retry(db: Session, team_name: str, max_retries: int = 3):
    # Prevent obvious sequence drift before first insert attempt.
    _sync_teams_id_sequence(db)
    for attempt in range(max_retries):
        try:
            with db.begin_nested():
                return db.execute(
                    text(
                        """
                        INSERT INTO teams (name)
                        VALUES (:name)
                        RETURNING id, name, is_active, created_at
                        """
                    ),
                    {"name": team_name},
                ).first()
        except IntegrityError as exc:
            msg = str(exc).lower()
            if ("teams_pkey" in msg) or ("key (id)=" in msg):
                _sync_teams_id_sequence(db)
                if attempt < (max_retries - 1):
                    continue
            raise
        except DatabaseError as exc:
            msg = str(exc).lower()
            if ("teams_pkey" in msg) or ("key (id)=" in msg):
                _sync_teams_id_sequence(db)
                if attempt < (max_retries - 1):
                    continue
            raise
    return None


def _insert_or_upsert_team_member_with_retry(
    db: Session,
    *,
    team_id: int,
    user_id: int,
    is_lead: bool,
    upsert: bool,
    max_retries: int = 3,
) -> None:
    # Keep team_members sequence aligned before write attempts.
    _sync_team_members_id_sequence(db)

    sql = """
        INSERT INTO team_members (team_id, user_id, is_lead, is_active, deleted_at)
        VALUES (:team_id, :user_id, :is_lead, TRUE, NULL)
    """
    if upsert:
        sql += """
        ON CONFLICT (team_id, user_id)
        DO UPDATE SET
            is_lead = EXCLUDED.is_lead,
            is_active = TRUE,
            deleted_at = NULL
        """

    for attempt in range(max_retries):
        try:
            with db.begin_nested():
                db.execute(
                    text(sql),
                    {"team_id": team_id, "user_id": user_id, "is_lead": is_lead},
                )
            return
        except IntegrityError as exc:
            msg = str(exc).lower()
            if ("team_members_pkey" in msg) or ("key (id)=" in msg):
                _sync_team_members_id_sequence(db)
                if attempt < (max_retries - 1):
                    continue
            raise
        except DatabaseError as exc:
            msg = str(exc).lower()
            if ("team_members_pkey" in msg) or ("key (id)=" in msg):
                _sync_team_members_id_sequence(db)
                if attempt < (max_retries - 1):
                    continue
            raise


@router.get("/users", response_model=list[TeamUserOut])
def list_active_users(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_existing_firebase_user)],
):
    _ensure_admin(user)
    rows = db.execute(
        text(
            """
            SELECT id, name, email
            FROM users
            WHERE is_active = TRUE
            ORDER BY name NULLS LAST, email ASC
            """
        )
    ).all()
    return [TeamUserOut(id=int(r[0]), name=r[1], email=str(r[2])) for r in rows]


@router.post("", response_model=TeamOut)
def create_team(
    body: CreateTeamBody,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_existing_firebase_user)],
):
    _ensure_admin(user)
    team_name = (body.name or "").strip()
    if not team_name:
        raise HTTPException(status_code=400, detail="Team name is required")

    members = body.members or []
    user_ids = _validate_team_members(members)
    now = datetime.now(UTC)

    try:
        team_row = _create_team_row_with_retry(db, team_name=team_name, max_retries=3)
        if not team_row:
            raise HTTPException(status_code=500, detail="Could not create team right now")

        if user_ids:
            existing_users = db.execute(
                text(
                    """
                    SELECT id
                    FROM users
                    WHERE is_active = TRUE
                      AND id = ANY(CAST(:user_ids AS INT[]))
                    """
                ),
                {"user_ids": user_ids},
            ).all()
            existing_user_ids = {int(r[0]) for r in existing_users}
            missing_user_ids = sorted(set(user_ids) - existing_user_ids)
            if missing_user_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown or inactive users: {missing_user_ids}",
                )

            for member in members:
                _insert_or_upsert_team_member_with_retry(
                    db,
                    team_id=int(team_row[0]),
                    user_id=int(member.user_id),
                    is_lead=bool(member.is_lead),
                    upsert=False,
                )

        db.execute(
            text("UPDATE teams SET updated_at = :updated_at WHERE id = :team_id"),
            {"updated_at": now, "team_id": int(team_row[0])},
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        if "uq_team_members_team_user" in str(exc):
            raise HTTPException(
                status_code=400, detail="Duplicate team members are not allowed"
            ) from None
        raise

    return TeamOut(
        id=int(team_row[0]),
        name=str(team_row[1]),
        is_active=bool(team_row[2]),
        created_at=team_row[3],
    )


@router.get("", response_model=list[TeamOut])
def list_teams(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_existing_firebase_user)],
):
    _ensure_admin(user)
    rows = db.execute(
        text(
            """
            SELECT id, name, is_active, created_at
            FROM teams
            WHERE is_active = TRUE
            ORDER BY created_at DESC, id DESC
            """
        )
    ).all()
    return [
        TeamOut(id=int(r[0]), name=str(r[1]), is_active=bool(r[2]), created_at=r[3])
        for r in rows
    ]


@router.get("/{team_id}", response_model=TeamDetailsResponse)
def get_team_details(
    team_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_existing_firebase_user)],
):
    _ensure_admin(user)

    team_row = db.execute(
        text(
            """
            SELECT id, name, is_active, created_at
            FROM teams
            WHERE id = :team_id
            """
        ),
        {"team_id": team_id},
    ).first()
    if not team_row:
        raise HTTPException(status_code=404, detail="Team not found")

    member_rows = db.execute(
        text(
            """
            SELECT tm.user_id, u.name, tm.is_lead
            FROM team_members tm
            JOIN users u ON u.id = tm.user_id
            WHERE tm.team_id = :team_id
              AND tm.is_active = TRUE
            ORDER BY tm.is_lead DESC, u.name NULLS LAST, tm.user_id ASC
            """
        ),
        {"team_id": team_id},
    ).all()

    opportunity_rows = db.execute(
        text(
            """
            SELECT id, opportunity_id, name, owner_id, team_id, status
            FROM opportunities
            WHERE team_id = :team_id
            ORDER BY created_at DESC, id DESC
            """
        ),
        {"team_id": team_id},
    ).mappings().all()

    return TeamDetailsResponse(
        team=TeamOut(
            id=int(team_row[0]),
            name=str(team_row[1]),
            is_active=bool(team_row[2]),
            created_at=team_row[3],
        ),
        members=[
            TeamMemberOut(user_id=int(r[0]), name=r[1], is_lead=bool(r[2]))
            for r in member_rows
        ],
        opportunities=[dict(r) for r in opportunity_rows],
    )


@router.put("/{team_id}", response_model=TeamDetailsResponse)
def update_team_members(
    team_id: int,
    body: UpdateTeamBody,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_existing_firebase_user)],
):
    _ensure_admin(user)
    members = body.members or []
    user_ids = _validate_team_members(members)

    team_exists = db.execute(
        text("SELECT 1 FROM teams WHERE id = :team_id AND is_active = TRUE"),
        {"team_id": team_id},
    ).first()
    if not team_exists:
        raise HTTPException(status_code=404, detail="Team not found")

    try:
        if user_ids:
            existing_users = db.execute(
                text(
                    """
                    SELECT id
                    FROM users
                    WHERE is_active = TRUE
                      AND id = ANY(CAST(:user_ids AS INT[]))
                    """
                ),
                {"user_ids": user_ids},
            ).all()
            existing_user_ids = {int(r[0]) for r in existing_users}
            missing_user_ids = sorted(set(user_ids) - existing_user_ids)
            if missing_user_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown or inactive users: {missing_user_ids}",
                )

        for member in members:
            _insert_or_upsert_team_member_with_retry(
                db,
                team_id=team_id,
                user_id=int(member.user_id),
                is_lead=bool(member.is_lead),
                upsert=True,
            )

        if user_ids:
            db.execute(
                text(
                    """
                    UPDATE team_members
                    SET is_active = FALSE, deleted_at = NOW()
                    WHERE team_id = :team_id
                      AND user_id <> ALL(CAST(:user_ids AS INT[]))
                      AND is_active = TRUE
                    """
                ),
                {"team_id": team_id, "user_ids": user_ids},
            )
        else:
            db.execute(
                text(
                    """
                    UPDATE team_members
                    SET is_active = FALSE, deleted_at = NOW()
                    WHERE team_id = :team_id
                      AND is_active = TRUE
                    """
                ),
                {"team_id": team_id},
            )

        db.execute(
            text("UPDATE teams SET updated_at = NOW() WHERE id = :team_id"),
            {"team_id": team_id},
        )
        db.commit()
    except HTTPException:
        db.rollback()
        raise

    return get_team_details(team_id=team_id, db=db, user=user)


@router.post("/{team_id}/assign-opportunities")
def assign_opportunities_to_team(
    team_id: int,
    body: AssignOpportunitiesBody,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_existing_firebase_user)],
):
    _ensure_admin(user)
    opp_ids = [int(v) for v in body.opportunity_ids]
    if not opp_ids:
        raise HTTPException(status_code=400, detail="opportunity_ids is required")

    team_exists = db.execute(
        text("SELECT 1 FROM teams WHERE id = :team_id AND is_active = TRUE"),
        {"team_id": team_id},
    ).first()
    if not team_exists:
        raise HTTPException(status_code=404, detail="Team not found")

    where_clause = "id = ANY(CAST(:opportunity_ids AS INT[]))"
    if not body.allow_reassignment:
        where_clause += " AND team_id IS NULL"

    updated_rows = db.execute(
        text(
            f"""
            UPDATE opportunities
            SET team_id = :team_id, updated_at = NOW()
            WHERE {where_clause}
            RETURNING id
            """
        ),
        {"team_id": team_id, "opportunity_ids": opp_ids},
    ).all()
    db.commit()
    return {"team_id": team_id, "updated_count": len(updated_rows)}
