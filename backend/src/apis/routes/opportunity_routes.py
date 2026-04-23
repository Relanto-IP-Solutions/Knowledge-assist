"""REST helpers to create opportunities and Slack sources without manual SQL."""

import threading
import uuid
import time
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Session

from src.apis.deps.firebase_auth import get_existing_firebase_user, get_firebase_user
from src.apis.deps.opportunity_access import can_user_access_opportunity
from src.apis.deps.rbac import get_user_roles, has_role, is_admin
from src.services.database_manager.connection import get_db_connection
from src.services.database_manager.models.auth_models import (
    Opportunity,
    OpportunitySource,
    User,
)
from src.services.database_manager.opportunity_state import STATUS_DISCOVERED
from src.services.database_manager.orm import get_db
from src.services.database_manager.rag_data_service import RagDataService
from src.services.rag_engine.retrieval.embedding import embed_texts
from src.services.database_manager.user_connection_utils import get_active_connection
from src.utils.logger import get_logger
from src.utils.opportunity_id import (
    gcs_path_prefix_candidates,
    normalize_opportunity_oid,
)


logger = get_logger(__name__)

router = APIRouter(prefix="/opportunities", tags=["opportunities"])
# Non-prefixed endpoints that historically lived in main.py.
public_router = APIRouter(tags=["opportunities"])

# Global question count changes rarely; avoid COUNT(*) on sase_questions every /ids request.
_TOTAL_SASE_Q_LOCK = threading.Lock()
_TOTAL_SASE_Q_CACHE: tuple[int, float] | None = None
_TOTAL_SASE_Q_TTL_S = 120.0


def _get_total_sase_questions_count_cached(
    db: Session | None = None,
    *,
    raw_cursor: Any = None,
) -> int:
    """Return COUNT(sase_questions) with a short TTL to cut latency on list endpoints.

    When ``db`` is the request Session (e.g. from ``Depends(get_db)``), cache misses use
    that connection instead of ``get_db_connection()`` so we do not open a second Cloud SQL
    connection while the pool only has one warm connection.

    When ``raw_cursor`` is set (e.g. inside ``load_questions``), cache misses use that cursor
    so we do not open a second connection for COUNT alone.
    """
    global _TOTAL_SASE_Q_CACHE
    now = time.time()
    with _TOTAL_SASE_Q_LOCK:
        if _TOTAL_SASE_Q_CACHE and (now - _TOTAL_SASE_Q_CACHE[1]) < _TOTAL_SASE_Q_TTL_S:
            return _TOTAL_SASE_Q_CACHE[0]

    if db is not None:
        n = int(
            db.execute(text("SELECT COUNT(*)::int FROM sase_questions")).scalar_one()
        )
    elif raw_cursor is not None:
        raw_cursor.execute("SELECT COUNT(*)::int FROM sase_questions")
        row = raw_cursor.fetchone()
        n = int(row[0] or 0) if row else 0
    else:
        con = get_db_connection()
        try:
            cur = con.cursor()
            cur.execute("SELECT COUNT(*)::int FROM sase_questions")
            row = cur.fetchone()
            n = int(row[0] or 0) if row else 0
        finally:
            con.close()

    with _TOTAL_SASE_Q_LOCK:
        _TOTAL_SASE_Q_CACHE = (n, now)
    return n


class OpportunitySummaryOut(BaseModel):
    opportunity_id: str
    name: str
    owner_id: int
    status: str = ""
    human_count: int = 0
    ai_count: int = 0
    total_questions: int = 0
    percentage: float = 0.0
    human_percentage: float = 0.0
    ai_percentage: float = 0.0


class OpportunityListResponse(BaseModel):
    """List opportunity details from the opportunities table."""

    opportunities: list[OpportunitySummaryOut]


class MyOpportunityOut(BaseModel):
    id: int
    opportunity_id: str
    name: str
    owner_id: int
    team_id: int | None = None
    status: str | None = None
    can_edit: bool = False
    can_assign: bool = False


class MyOpportunitiesResponse(BaseModel):
    opportunities: list[MyOpportunityOut]


@router.get("/unassigned")
def list_unassigned_opportunities(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_existing_firebase_user)],
    limit: int = 200,
):
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required.")
    limit = min(max(int(limit), 1), 2000)
    rows = db.execute(
        text(
            """
            SELECT id, opportunity_id, name, owner_id, status
            FROM opportunities
            WHERE team_id IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).mappings().all()
    return {"opportunities": [dict(r) for r in rows]}


@router.get("/my-opportunities", response_model=MyOpportunitiesResponse)
def get_my_opportunities(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_existing_firebase_user)],
    limit: int = 500,
):
    user_id = int(getattr(user, "id"))
    limit = min(max(int(limit), 1), 2000)
    rows = db.execute(
        text(
            """
            SELECT DISTINCT
                o.id,
                o.opportunity_id,
                o.name,
                o.owner_id,
                o.team_id,
                o.status,
                EXISTS (
                    SELECT 1
                    FROM team_members tm2
                    WHERE tm2.team_id = o.team_id
                      AND tm2.user_id = :user_id
                      AND tm2.is_active = TRUE
                ) AS user_is_team_member,
                EXISTS (
                    SELECT 1
                    FROM team_members tm3
                    WHERE tm3.team_id = o.team_id
                      AND tm3.user_id = :user_id
                      AND tm3.is_active = TRUE
                      AND tm3.is_lead = TRUE
                ) AS user_is_team_lead
            FROM opportunities o
            LEFT JOIN team_members tm
              ON tm.team_id = o.team_id
             AND tm.is_active = TRUE
            WHERE o.owner_id = :user_id
               OR tm.user_id = :user_id
            ORDER BY o.id DESC
            LIMIT :limit
            """
        ),
        {"user_id": user_id, "limit": limit},
    ).mappings().all()

    opportunities: list[MyOpportunityOut] = []
    for row in rows:
        access = can_user_access_opportunity(user, row)
        if not access.can_view:
            continue
        opportunities.append(
            MyOpportunityOut(
                id=int(row["id"]),
                opportunity_id=str(row["opportunity_id"]),
                name=str(row["name"] or ""),
                owner_id=int(row["owner_id"]),
                team_id=int(row["team_id"]) if row["team_id"] is not None else None,
                status=str(row["status"]) if row["status"] is not None else None,
                can_edit=access.can_edit,
                can_assign=access.can_assign,
            )
        )

    return MyOpportunitiesResponse(opportunities=opportunities)


@router.get("/ids", response_model=OpportunityListResponse)
def list_opportunity_ids(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_firebase_user)],
    limit: int = 200,
):
    """Fetch opportunity ids + metadata from the `opportunities` table.

    Requires ``Authorization: Bearer <Firebase ID token>``.
    """
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be > 0")
    limit = min(int(limit), 2000)

    logger.info(
        "list_opportunity_ids: auth user_id={} roles_assigned={!r} effective_roles={} email={!r}",
        getattr(user, "id", None),
        getattr(user, "roles_assigned", None),
        sorted(get_user_roles(user)),
        getattr(user, "email", None),
    )

    user_id = int(getattr(user, "id"))
    if is_admin(user):
        scope_where = "TRUE"
    else:
        # User-level view: own opportunities + opportunities assigned to teams
        # where the user is an active member.
        scope_where = """
            (
                o.owner_id = :user_id
                OR EXISTS (
                    SELECT 1
                    FROM team_members tm
                    WHERE tm.team_id = o.team_id
                      AND tm.user_id = :user_id
                      AND tm.is_active = true
                )
            )
        """

    t_list0 = time.perf_counter()
    total_questions = _get_total_sase_questions_count_cached(db)
    t_cache_ms = int((time.perf_counter() - t_list0) * 1000)

    t_sql0 = time.perf_counter()
    rows = db.execute(
        text(
            """
            WITH recent_o AS (
                SELECT
                    o.opportunity_id,
                    o.name,
                    o.owner_id,
                    o.status,
                    o.created_at
                FROM opportunities o
                WHERE o.opportunity_id IS NOT NULL
                  AND """
            + scope_where
            + """
                ORDER BY o.created_at DESC, o.opportunity_id ASC
                LIMIT :limit
            ),
            a AS (
                SELECT
                    ans.opportunity_id,
                    COUNT(*) FILTER (WHERE ans.status = 'active' AND ans.is_user_override = true) AS human_count,
                    COUNT(*) FILTER (WHERE ans.status = 'active' AND ans.is_user_override = false) AS ai_count
                FROM answers ans
                WHERE ans.opportunity_id = ANY(SELECT ro.opportunity_id FROM recent_o ro)
                GROUP BY ans.opportunity_id
            )
            SELECT
                ro.opportunity_id,
                ro.name,
                ro.owner_id,
                ro.status,
                COALESCE(a.human_count, 0) AS human_count,
                COALESCE(a.ai_count, 0) AS ai_count,
                CAST(:total_questions AS INTEGER) AS total_questions,
                ROUND(
                    (
                        (COALESCE(a.human_count, 0) + COALESCE(a.ai_count, 0))::numeric
                        / NULLIF(CAST(:total_questions AS NUMERIC), 0)
                    ) * 100.0,
                    2
                ) AS percentage,
                ROUND(
                    (
                        COALESCE(a.human_count, 0)::numeric
                        / NULLIF(CAST(:total_questions AS NUMERIC), 0)
                    )
                    * 100.0,
                    2
                ) AS human_percentage,
                ROUND(
                    (
                        COALESCE(a.ai_count, 0)::numeric
                        / NULLIF(CAST(:total_questions AS NUMERIC), 0)
                    )
                    * 100.0,
                    2
                ) AS ai_percentage
            FROM recent_o ro
            LEFT JOIN a
                ON a.opportunity_id = ro.opportunity_id
            ORDER BY ro.created_at DESC, ro.opportunity_id ASC
            """
        ),
        {
            "limit": limit,
            "user_id": user_id,
            "total_questions": total_questions,
        },
    ).fetchall()
    logger.info(
        "list_opportunity_ids timing | total_q_cache_ms={} sql_ms={} rows={} limit={}",
        t_cache_ms,
        int((time.perf_counter() - t_sql0) * 1000),
        len(rows),
        limit,
    )
    return OpportunityListResponse(
        opportunities=[
            OpportunitySummaryOut(
                opportunity_id=str(r[0]),
                name=str(r[1] or ""),
                owner_id=int(r[2]),
                status=str(r[3] or ""),
                human_count=int(r[4] or 0),
                ai_count=int(r[5] or 0),
                total_questions=int(r[6] or 0),
                percentage=float(r[7] or 0.0),
                human_percentage=float(r[8] or 0.0),
                ai_percentage=float(r[9] or 0.0),
            )
            for r in rows
            if r[0] is not None
        ]
    )


@public_router.get("/questions")
async def get_questions():
    """Return all SASE questions (legacy endpoint)."""
    from src.services.database_manager.connection import get_db_connection

    try:
        con = get_db_connection()
        try:
            cur = con.cursor()
            query = """
                SELECT
                    q.q_id,
                    q.question,
                    q.answer_type,
                    q.requirement_type,
                    b.batch_label as subsection,
                    split_part(b.section_path, ' > ', 1) as section,
                    p.option_value
                FROM sase_questions q
                JOIN sase_batches b ON q.batch = b.batch_id
                LEFT JOIN sase_picklist_options p ON p.q_id = q.q_id
                ORDER BY b.batch_order, q.seq_in_section, p.sort_order NULLS LAST;
            """
            cur.execute(query)
            rows = cur.fetchall()

            option_by_qid: dict[str, list[str]] = {}
            question_rows: list[tuple[Any, ...]] = []
            seen_qid: set[str] = set()
            for row in rows:
                qid = row[0]
                opt = row[6]
                if qid not in seen_qid:
                    seen_qid.add(qid)
                    question_rows.append(row)
                    option_by_qid[qid] = []
                if opt is not None:
                    option_by_qid[qid].append(opt)

            questions = [
                {
                    "question_id": row[0],
                    "question_text": row[1],
                    "answer_type": row[2],
                    "requirement_type": row[3],
                    "section": row[5],
                    "subsection": row[4],
                    "option_values": option_by_qid.get(row[0], []),
                }
                for row in question_rows
            ]
            return {"questions": questions}
        finally:
            con.close()
    except Exception as exc:
        logger.exception("Failed to fetch questions: {}", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from None


@public_router.post("/answer-generation")
async def answer_generation(request: Request):
    """RAG workflow: same contract as answer-generation Cloud Function (legacy endpoint)."""
    from src.services.pipelines.agent_pipeline import (
        AnswerGenerationAlreadyRunningError,
        AnswerGenerationPipeline,
    )

    extras: dict = {}
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from None
    opportunity_id = body.get("opportunity_id") or ""
    extras = {"opportunity_id": opportunity_id} if opportunity_id else {}

    try:
        pipeline = AnswerGenerationPipeline(use_cache=True)
        result = await pipeline.run_async(body)
        return result
    except AnswerGenerationAlreadyRunningError as exc:
        logger.bind(**extras).warning("Answer generation rejected (already running): {}", exc)
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        logger.bind(**extras).warning("Answer generation invalid request: {}", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:
        logger.bind(**extras).exception("Answer generation failed: {}", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from None


def _sase_question_lookup_batch(
    cur, q_ids: list[str]
) -> dict[str, tuple[str | None, str | None]]:
    """Map ``q_id`` -> (answer_type, requirement_type) for many ids (join key: ``q_id``)."""
    if not q_ids:
        return {}
    cur.execute(
        """
        SELECT q_id, answer_type, requirement_type
        FROM sase_questions
        WHERE q_id = ANY(%s::text[])
        """,
        (q_ids,),
    )
    return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def _calculate_opportunity_stats(cur, opp_id: str) -> dict[str, float | int]:
    """Calculate AI/Human generation stats for active answers.

    - human_count: active answers where is_user_override = true
    - ai_count: active answers where is_user_override = false
    - percentage: completion rate = (human_count + ai_count) / total sase_questions
    - human_percentage / ai_percentage: breakdown within submitted answers
    """
    cur.execute(
        """
        SELECT
            COUNT(CASE WHEN is_user_override = true THEN 1 END),
            COUNT(CASE WHEN is_user_override = false THEN 1 END)
        FROM answers
        WHERE opportunity_id = %s AND status = 'active'
        """,
        (opp_id,)
    )
    row = cur.fetchone()
    human_count = int(row[0] or 0) if row else 0
    ai_count = int(row[1] or 0) if row else 0
    submitted = human_count + ai_count

    # Total questions in the system (cached; same as /opportunities/ids)
    total_questions = _get_total_sase_questions_count_cached(raw_cursor=cur)

    # Completion percentage: how many of all questions have been answered
    percentage = round((submitted / total_questions * 100.0), 2) if total_questions > 0 else 0.0

    # Breakdown: each count as % of total questions in the system
    human_pct = round((human_count / total_questions * 100.0), 2) if total_questions > 0 else 0.0
    ai_pct = round((ai_count / total_questions * 100.0), 2) if total_questions > 0 else 0.0

    return {
        "human_count": human_count,
        "ai_count": ai_count,
        "total_questions": total_questions,
        "percentage": percentage,
        "human_percentage": human_pct,
        "ai_percentage": ai_pct,
    }


class EnsureSourceBody(BaseModel):
    """Create opportunity + source if missing. Idempotent."""

    opportunity_id: str = Field(
        ...,
        min_length=1,
        description="Unique opportunity id (e.g. 006Ki000004r26LIAQ). Used as GCS folder and Gmail subject search.",
    )
    name: str = Field(..., min_length=1, description="Human-readable deal name.")
    owner_email: str = Field(
        ...,
        min_length=3,
        description="Must match a users.email row with valid OAuth tokens.",
    )


class EnsureSourceResponse(BaseModel):
    opportunity_id: int
    opportunity_id_string: str
    name: str
    owner_id: int
    source_id: int
    source_type: str
    opportunity_created: bool
    source_created: bool


class EnsureSlackOpportunityBody(BaseModel):
    """Create opportunity + slack source if missing. Idempotent."""

    opportunity_id: str = Field(
        ...,
        min_length=1,
        description="Unique opportunity id in canonical form (e.g. oid1234). Drives Slack channel name prefix.",
    )
    name: str = Field(..., min_length=1, description="Human-readable deal name.")
    owner_email: str = Field(
        ...,
        min_length=3,
        description="Must match a users.email row; that user should have slack_access_token.",
    )


class EnsureSlackOpportunityResponse(BaseModel):
    opportunity_id: int
    opportunity_id_string: str
    name: str
    owner_id: int
    slack_source_id: int
    opportunity_created: bool
    slack_source_created: bool


@router.post("/slack", response_model=EnsureSlackOpportunityResponse)
def ensure_slack_opportunity(
    body: EnsureSlackOpportunityBody, db: Annotated[Session, Depends(get_db)]
):
    """Ensure an `opportunities` row and an `opportunity_sources` row (`source_type='slack'`) exist.

    Call this when you add a **new** opportunity (`oid`) or when an opportunity exists but the
    Slack source row was never created. You do **not** need to call this for each new Slack
    channel under the same `oid` — only the channel name prefix must match `oid` (see slack plugin).

    Requires the owner user to exist (typically after Slack OAuth). Does not create users.
    """
    email = body.owner_email.strip()
    try:
        oid = normalize_opportunity_oid(body.opportunity_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    name = body.name.strip()

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail=(
                "No user with that email. Create the user and complete Slack OAuth first "
                f"(users.slack_access_token required). Email: {email}"
            ),
        )

    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == oid).first()
    opportunity_created = False
    if not opp:
        opp = Opportunity(
            opportunity_id=oid,
            name=name,
            owner_id=user.id,
            status=STATUS_DISCOVERED,
            total_documents=0,
            processed_documents=0,
        )
        db.add(opp)
        db.flush()
        opportunity_created = True
        logger.info("Created opportunity oid={} id={}", oid, opp.id)

        # Also register in RAG opportunities table (opportunity_id = oid string)
        try:
            RagDataService().init_opportunity(
                opportunity_id=oid,
                name=name,
                owner_id=str(user.id),
            )
            logger.info("RAG opportunities table seeded for oid={}", oid)
        except Exception:
            logger.exception("Failed to seed RAG opportunities table for oid={}", oid)
    else:
        if opp.owner_id != user.id:
            logger.warning(
                "ensure_slack_opportunity: oid={} already owned by user_id={} (requested owner_id={})",
                oid,
                opp.owner_id,
                user.id,
            )

    slack_src = (
        db
        .query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "slack",
        )
        .first()
    )
    slack_source_created = False
    if not slack_src:
        slack_src = OpportunitySource(opportunity_id=opp.id, source_type="slack")
        db.add(slack_src)
        db.flush()
        slack_source_created = True
        logger.info("Created opportunity_sources slack for opportunity_id={}", opp.id)

    db.commit()
    db.refresh(slack_src)

    return EnsureSlackOpportunityResponse(
        opportunity_id=opp.id,
        opportunity_id_string=opp.opportunity_id,
        name=opp.name,
        owner_id=opp.owner_id,
        slack_source_id=slack_src.id,
        opportunity_created=opportunity_created,
        slack_source_created=slack_source_created,
    )


def _find_first_object_with_key(obj: Any, key: str) -> dict[str, Any] | None:
    """Recursively find the first dict that contains `key`.

    Used to support FE payloads where the actual `q_id` update is nested.
    """
    if isinstance(obj, dict):
        if key in obj:
            # Only treat it as the q update payload if it contains a scalar q_id.
            # FE might send numeric/boolean ids; normalize later via `str(...)`.
            val = obj.get(key)
            if val is not None and not isinstance(val, (dict, list)):
                return obj
        for v in obj.values():
            found = _find_first_object_with_key(v, key)
            if found is not None:
                return found
    if isinstance(obj, list):
        for item in obj:
            found = _find_first_object_with_key(item, key)
            if found is not None:
                return found
    return None


def _find_all_objects_with_key(obj: Any, key: str) -> list[dict[str, Any]]:
    """Recursively collect dicts that contain `key` and look like q-update objects.

    This enables FE to submit multiple question updates in a single request.

    When a dict carries a non-empty ``updates`` list, only entries under that list (plus
    any other nested structures, excluding the ``updates`` key itself) are collected.
    The root dict is not also treated as a q-update. Some clients leave a stale
    root-level ``q_id``/``answer_id`` next to ``updates``; counting the root used to
    apply the wrong question first and could clear or skip the intended row.
    """
    found: list[dict[str, Any]] = []

    def _looks_like_q_update(d: dict[str, Any]) -> bool:
        if key not in d:
            return False
        qid = d.get(key)
        if qid is None or isinstance(qid, (dict, list)):
            return False

        has_conflict_id = d.get("conflict_id") not in (None, "", "null", "NULL")
        has_conflict_answer_id = d.get("conflict_answer_id") not in (
            None,
            "",
            "null",
            "NULL",
        )
        has_answer_id = d.get("answer_id") not in (None, "", "null", "NULL")

        return (has_conflict_id and has_conflict_answer_id) or has_answer_id

    if isinstance(obj, dict):
        updates_list = obj.get("updates")
        if isinstance(updates_list, list) and len(updates_list) > 0:
            for item in updates_list:
                found.extend(_find_all_objects_with_key(item, key))
            for k, v in obj.items():
                if k == "updates":
                    continue
                found.extend(_find_all_objects_with_key(v, key))
            return found
        if _looks_like_q_update(obj):
            found.append(obj)
        for v in obj.values():
            found.extend(_find_all_objects_with_key(v, key))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_find_all_objects_with_key(item, key))

    return found


def _should_use_flat_save_or_resolve(body: Any) -> bool:
    """True when the client clearly sent the legacy flat body (``question_id`` + RESOLVE/INSERT).

    If we do not take this branch, a dict that also contains a stray ``q_id`` (often left
    over from the previous question) plus ``answer_id`` is classified as a nested
    q-update on the **root** object. The handler then uses ``q_id`` instead of
    ``question_id``, updating the wrong ``sase_questions`` row (or running INSERT
    against the wrong question) while the intended question is left unchanged.
    """
    if not isinstance(body, dict):
        return False
    if "question_id" not in body:
        return False
    updates = body.get("updates")
    if isinstance(updates, list) and len(updates) > 0:
        return False
    if body.get("selected_answer_id") is not None:
        return True
    if _normalize_optional_str(body.get("answer_id")) is not None:
        return True
    if body.get("answers") is not None:
        return True
    act = body.get("action")
    if isinstance(act, str) and act.strip():
        return True
    return False


def _normalize_optional_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() == "null":
        return None
    return s


def _coerce_answers_status(status_val: Any, default: str = "active") -> str:
    if isinstance(status_val, bool):
        return "active" if status_val else "inactive"
    if isinstance(status_val, str):
        s = status_val.strip().lower()
        if s in {"active", "inactive"}:
            return s
        if s in {"true", "1", "yes"}:
            return "active"
        if s in {"false", "0", "no"}:
            return "inactive"
    return default


def _submit_final_answer_selection(
    *,
    cur,
    now: datetime,
    opportunity_id: str,
    question_id: str,
    selected_answer_id: str,
    conflict_id: str | None,
    status_str: str,
    is_user_override: bool,
    override_text: str | None = None,
    set_final_answer_id: bool = True,
    effective_question_id: str | None = None,
    skip_validations: bool = False,
) -> str:
    """Apply FE selection to:
    - scoped final answer mapping in `opportunity_question_answers`
      (`opportunity_id`, `question_id`) ← ``selected_answer_id``.
    - `answers.status` / `answers.is_active` / `answers.is_user_override`
    - optional `answers.answer_text` when user overrides AI text (`override_text`)
    - `conflicts.status` (if conflict_id is provided)

    RAG and INSERT paths do not clear ``final_answer_id``; this function and the INSERT
    branch only assign a concrete ``answer_id``.

    Returns the canonical ``q_id`` used for final-answer mapping (from the DB for conflict
    flows, otherwise the request ``question_id``). Callers must use this for responses
    and feedback — not the raw payload ``q_id``, which can disagree with ``conflicts``.
    """
    effective_question_id = effective_question_id or question_id

    # When resolving a conflict, derive the real `question_id` from the conflicts row
    # to avoid FE payload mismatches (conflict_id <-> q_id).
    if conflict_id and not skip_validations:
        cur.execute(
            """
            SELECT question_id
            FROM conflicts
            WHERE conflict_id = %s
              AND opportunity_id = %s
              AND answer_id = %s
            LIMIT 1
            """,
            (conflict_id, opportunity_id, selected_answer_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=400,
                detail="conflict_answer_id is not part of the provided pending conflict group.",
            )
        effective_question_id = row[0]
        if str(question_id).strip() != str(effective_question_id).strip():
            logger.warning(
                "Payload q_id={} does not match conflicts.question_id={} for conflict_id={}; "
                "using DB value for final-answer mapping and answers.",
                question_id,
                effective_question_id,
                conflict_id,
            )

    if not skip_validations:
        cur.execute(
            """
            SELECT 1
            FROM answers
            WHERE opportunity_id = %s AND question_id = %s AND answer_id = %s
            LIMIT 1
            """,
            (opportunity_id, effective_question_id, selected_answer_id),
        )
        if not cur.fetchone():
            raise HTTPException(
                status_code=400,
                detail="selected answer_id does not belong to this question/opportunity.",
            )

    # User-edited answer text (direct submit or conflict winner): same row as selected_answer_id.
    if is_user_override and override_text:
        cur.execute(
            """
            UPDATE answers
            SET answer_text = %s,
                is_user_override = true,
                updated_at = %s
            WHERE opportunity_id = %s
              AND question_id = %s
              AND answer_id = %s
            """,
            (override_text, now, opportunity_id, effective_question_id, selected_answer_id),
        )

    # Final answer selection is persisted per (opportunity_id, question_id).
    if set_final_answer_id:
        cur.execute(
            """
            INSERT INTO opportunity_question_answers (
                opportunity_id,
                question_id,
                final_answer_id,
                updated_at
            )
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (opportunity_id, question_id)
            DO UPDATE SET
                final_answer_id = EXCLUDED.final_answer_id,
                updated_at = NOW()
            """,
            (opportunity_id, effective_question_id, selected_answer_id),
        )

    if conflict_id and not skip_validations:
        cur.execute(
            """
            SELECT 1
            FROM conflicts
            WHERE conflict_id = %s
              AND opportunity_id = %s
              AND question_id = %s
              AND answer_id = %s
            LIMIT 1
            """,
            (conflict_id, opportunity_id, effective_question_id, selected_answer_id),
        )
        if not cur.fetchone():
            raise HTTPException(
                status_code=400,
                detail="conflict_answer_id is not part of the provided pending conflict group.",
            )

    if conflict_id:
        cur.execute(
            """
            UPDATE conflicts
            SET
                status = 'resolved',
                resolved_by = %s,
                resolved_at = %s
            WHERE conflict_id = %s
              AND opportunity_id = %s
              AND question_id = %s
            """,
            (
                selected_answer_id,
                now,
                conflict_id,
                opportunity_id,
                effective_question_id,
            ),
        )
    else:
        # If the FE says there's no conflict, still clean up any pending conflict rows.
        cur.execute(
            """
            UPDATE conflicts
            SET status = 'ignored'
            WHERE opportunity_id = %s
              AND question_id = %s
              AND status = 'pending'
            """,
            (opportunity_id, effective_question_id),
        )

    # Conflict behavior requested by FE:
    # - for the answers participating in the same `conflict_id`,
    #   set selected answer.status='active' and others='inactive'
    # - set answers.is_active=false for both selected + others (resolved set)
    if conflict_id:
        cur.execute(
            """
            UPDATE answers
            SET
                is_active = false,
                status = CASE
                    WHEN answer_id = %s THEN %s
                    ELSE 'inactive'
                END,
                has_conflicts = false,
                needs_review = false,
                is_user_override = CASE
                    WHEN answer_id = %s THEN %s
                    ELSE is_user_override
                END,
                updated_at = %s
            WHERE opportunity_id = %s
              AND question_id = %s
              AND answer_id IN (
                SELECT c.answer_id
                FROM conflicts c
                WHERE c.conflict_id = %s
                  AND c.opportunity_id = %s
                  AND c.question_id = %s
              )
            """,
            (
                selected_answer_id,
                status_str,
                selected_answer_id,
                bool(is_user_override),
                now,
                opportunity_id,
                effective_question_id,
                conflict_id,
                opportunity_id,
                effective_question_id,
            ),
        )
    else:
        # Non-conflict: selected answer becomes active; all other answers for the question go inactive.
        cur.execute(
            """
            UPDATE answers
            SET
                is_active = false,
                status = CASE
                    WHEN answer_id = %s THEN %s
                    ELSE 'inactive'
                END,
                has_conflicts = false,
                needs_review = false,
                is_user_override = CASE
                    WHEN answer_id = %s THEN %s
                    ELSE is_user_override
                END,
                updated_at = %s
            WHERE opportunity_id = %s
              AND question_id = %s
            """,
            (
                selected_answer_id,
                status_str,
                selected_answer_id,
                bool(is_user_override),
                now,
                opportunity_id,
                effective_question_id,
            ),
        )

    return effective_question_id


def _batch_set_final_answer_ids(cur, updates: list[tuple[str, str, str]]) -> None:
    """Batch-upsert scoped final-answer mappings.

    Deprecated legacy target: do not write `sase_questions.final_answer_id`.
    """
    if not updates:
        return
    # Dedupe while preserving the last assignment for (opportunity_id, q_id).
    dedup: dict[tuple[str, str], str] = {}
    for oid, qid, aid in updates:
        dedup[(str(oid), str(qid))] = str(aid)
    items = list(dedup.items())
    placeholders = ",".join(["(%s,%s,%s,NOW())"] * len(items))
    params: list[str] = []
    for (oid, qid), aid in items:
        params.extend([oid, qid, aid])
    cur.execute(
        f"""
        INSERT INTO opportunity_question_answers (
            opportunity_id,
            question_id,
            final_answer_id,
            updated_at
        )
        VALUES {placeholders}
        ON CONFLICT (opportunity_id, question_id)
        DO UPDATE SET
            final_answer_id = EXCLUDED.final_answer_id,
            updated_at = NOW()
        """,
        tuple(params),
    )


# ─── Load Questions (GET) + Answers (POST) ─────────────────────────────────


class QAAnswerInput(BaseModel):
    value: str = Field(..., description="Answer text/value chosen by FE.")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence between 0 and 1."
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class SaveOrResolveAnswersInput(BaseModel):
    question_id: str = Field(..., description="Question ID (q_id).")
    # Required only for INSERT flows; for RESOLVE flows the FE may send just
    # `question_id` + `selected_answer_id`.
    answers: list[QAAnswerInput] = Field(default_factory=list)
    selected_answer_id: str | None = Field(
        default=None,
        description="Answer ID selected by user when action=RESOLVE.",
    )
    action: str = Field(
        default="INSERT",
        description="Either INSERT (default) or RESOLVE.",
    )


class QAAnswerOut(BaseModel):
    answer_id: str
    value: str
    confidence: float
    is_active: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConflictOut(BaseModel):
    conflict_id: str
    answer_ids: list[str]


class QuestionOut(BaseModel):
    question_id: str
    question_text: str
    answer_type: str | None = None
    requirement_type: str | None = None
    option_values: list[str] = Field(
        default_factory=list,
        description="Picklist choices from sase_picklist_options.option_value (ordered by sort_order).",
    )
    final_answer_id: str | None = None
    answers: list[QAAnswerOut] = Field(default_factory=list)
    conflict: ConflictOut | None = None


class LoadQuestionsResponse(BaseModel):
    opportunity_id: str
    human_count: int = Field(default=0, description="Number of active answers overridden by humans.")
    ai_count: int = Field(default=0, description="Number of active answers generated by AI.")
    total_questions: int = Field(default=0, description="Total number of questions in sase_questions.")
    percentage: float = Field(default=0.0, description="Completion percentage: active answers / total questions.")
    human_percentage: float = Field(default=0.0, description="% of submitted answers that are human overrides.")
    ai_percentage: float = Field(default=0.0, description="% of submitted answers that are AI generated.")
    questions: list[QuestionOut]


@router.get("/{opportunity_id}/questions", response_model=LoadQuestionsResponse)
def load_questions(opportunity_id: str):
    """Fetch questions + active answers + conflict context for the FE."""
    con = get_db_connection()
    try:
        cur = con.cursor()

        # 1) Load question metadata + picklist options in one round-trip.
        # deprecated: do not read `sase_questions.final_answer_id`; scoped final answers live
        # in `opportunity_question_answers`.
        cur.execute(
            """
            SELECT
                q.q_id,
                q.question,
                q.answer_type,
                q.requirement_type,
                p.option_value
            FROM sase_questions q
            LEFT JOIN sase_picklist_options p ON p.q_id = q.q_id
            ORDER BY q.q_id, p.sort_order NULLS LAST
            """,
        )
        q_rows = cur.fetchall()
        questions: list[dict[str, Any]] = []
        option_by_qid: dict[str, list[str]] = {}
        seen_qid: set[str] = set()
        for row in q_rows:
            qid = row[0]
            opt = row[4]
            if qid not in seen_qid:
                seen_qid.add(qid)
                questions.append(
                    {
                        "q_id": qid,
                        "question": row[1],
                        "answer_type": row[2],
                        "requirement_type": row[3],
                    }
                )
                option_by_qid[qid] = []
            if opt is not None:
                option_by_qid[qid].append(opt)

        # 2) Load active answers (answers.is_active = true).
        cur.execute(
            """
            SELECT
                question_id,
                answer_id,
                answer_text,
                confidence_score,
                is_active,
                status,
                reasoning,
                primary_source
            FROM answers
            WHERE opportunity_id = %s AND is_active = true
            """,
            (opportunity_id,),
        )
        a_rows = cur.fetchall()
        a_cols = [d[0] for d in cur.description]
        active_answers = [dict(zip(a_cols, r, strict=True)) for r in a_rows]
        active_by_q: dict[str, list[dict[str, Any]]] = {}
        for a in active_answers:
            active_by_q.setdefault(a["question_id"], []).append(a)

        # 3) Load scoped final-answer mappings and join answers via
        #    (opportunity_id, final_answer_id).
        final_by_q: dict[str, dict[str, Any]] = {}
        if questions:
            q_ids = [q["q_id"] for q in questions]
            cur.execute(
                """
                SELECT
                    oqa.question_id,
                    oqa.final_answer_id,
                    a.answer_id,
                    answer_text,
                    confidence_score,
                    is_active,
                    status,
                    reasoning,
                    primary_source
                FROM opportunity_question_answers oqa
                LEFT JOIN answers a
                  ON a.opportunity_id = oqa.opportunity_id
                 AND a.answer_id = oqa.final_answer_id
                WHERE oqa.opportunity_id = %s
                  AND oqa.question_id = ANY(%s::text[])
                """,
                (opportunity_id, q_ids),
            )
            fa_rows = cur.fetchall()
            fa_cols = [d[0] for d in cur.description]
            for r in fa_rows:
                d = dict(zip(fa_cols, r, strict=True))
                final_by_q[d["question_id"]] = d

        # 4) Load pending conflict_id per question (used only when we detect conflicts by is_active).
        conflict_id_by_q: dict[str, str] = {}
        pending_conflict_qids = [
            q["q_id"]
            for q in questions
            if (final_by_q.get(q["q_id"], {}).get("final_answer_id") is None)
            and (len(active_by_q.get(q["q_id"], [])) > 1)
        ]
        if pending_conflict_qids:
            cur.execute(
                """
                SELECT
                    question_id,
                    conflict_id
                FROM conflicts
                WHERE opportunity_id = %s
                  AND status = 'pending'
                  AND question_id = ANY(%s::text[])
                ORDER BY created_at DESC
                """,
                (opportunity_id, pending_conflict_qids),
            )
            for qid, conflict_id in cur.fetchall():
                # First row per question due to ORDER BY created_at DESC; keep it.
                conflict_id_by_q.setdefault(qid, conflict_id)

        out_questions: list[QuestionOut] = []
        for q in questions:
            qid = q["q_id"]
            qtext = q["question"]
            final_answer_id = final_by_q.get(qid, {}).get("final_answer_id")

            active_list = active_by_q.get(qid, [])
            # If resolved (final_answer_id set), show the final answer row.
            if final_answer_id:
                final_row = final_by_q.get(qid)
                answers_out: list[QAAnswerOut] = []
                if final_row:
                    answers_out.append(
                        QAAnswerOut(
                            answer_id=final_row["answer_id"],
                            value=final_row.get("answer_text") or "",
                            confidence=float(final_row.get("confidence_score") or 0.0),
                            is_active=bool(final_row.get("is_active")),
                            metadata={
                                "status": final_row.get("status"),
                                "reasoning": final_row.get("reasoning"),
                                "primary_source": final_row.get("primary_source"),
                            },
                        )
                    )
                out_questions.append(
                    QuestionOut(
                        question_id=qid,
                        question_text=qtext,
                        answer_type=q.get("answer_type"),
                        requirement_type=q.get("requirement_type"),
                        option_values=option_by_qid.get(qid, []),
                        final_answer_id=final_answer_id,
                        answers=answers_out,
                        conflict=None,
                    )
                )
                continue

            # Unresolved: show active answers; conflicts are driven by answers.is_active.
            answers_out = [
                QAAnswerOut(
                    answer_id=a["answer_id"],
                    value=a.get("answer_text") or "",
                    confidence=float(a.get("confidence_score") or 0.0),
                    is_active=bool(a.get("is_active")),
                    metadata={
                        "status": a.get("status"),
                        "reasoning": a.get("reasoning"),
                        "primary_source": a.get("primary_source"),
                    },
                )
                for a in active_list
            ]

            conflict_out: ConflictOut | None = None
            if final_answer_id is None and len(active_list) > 1:
                conflict_id = conflict_id_by_q.get(qid)
                if conflict_id:
                    conflict_out = ConflictOut(
                        conflict_id=conflict_id,
                        answer_ids=[a["answer_id"] for a in active_list],
                    )

            out_questions.append(
                QuestionOut(
                    question_id=qid,
                    question_text=qtext,
                    answer_type=q.get("answer_type"),
                    requirement_type=q.get("requirement_type"),
                    option_values=option_by_qid.get(qid, []),
                    final_answer_id=final_answer_id,
                    answers=answers_out,
                    conflict=conflict_out,
                )
            )

        stats = _calculate_opportunity_stats(cur, opportunity_id)

        return LoadQuestionsResponse(
            opportunity_id=opportunity_id,
            human_count=stats["human_count"],
            ai_count=stats["ai_count"],
            total_questions=stats["total_questions"],
            percentage=stats["percentage"],
            human_percentage=stats["human_percentage"],
            ai_percentage=stats["ai_percentage"],
            questions=out_questions,
        )
    except Exception:
        # Best-effort rollback; if the socket dropped (pg8000 InterfaceError), rollback can fail.
        try:
            con.rollback()
        except Exception:
            pass
        raise
    finally:
        con.close()


@router.post("/{opportunity_id}/answers")
def save_or_resolve_answers(
    opportunity_id: str,
    user: Annotated[User, Depends(get_firebase_user)],
    body: Annotated[
        dict[str, Any],
        Body(
            openapi_examples={
                "nested_select_answer": {
                    "summary": "Nested: pick answer (q_id + answer_id)",
                    "description": (
                        "Replace answer_id with a real UUID from GET /opportunities/{oid}/answers "
                        "or /questions. Any wrapper key works; `updates` is conventional. "
                        "Send Authorization: Bearer <Firebase ID token>."
                    ),
                    "value": {
                        "updates": [
                            {
                                "q_id": "QID-001",
                                "answer_id": "00000000-0000-0000-0000-000000000000",
                            }
                        ]
                    },
                },
                "nested_direct_user_edit": {
                    "summary": "Nested: direct pick + user-edited text",
                    "description": (
                        "Same as direct selection, but when the user edits the answer text, "
                        "send `is_user_override: true` and `override_value` with the final text."
                    ),
                    "value": {
                        "updates": [
                            {
                                "q_id": "QID-001",
                                "answer_id": "00000000-0000-0000-0000-000000000000",
                                "is_user_override": True,
                                "override_value": "Corrected answer text from the user",
                            }
                        ]
                    },
                },
                "nested_resolve_conflict": {
                    "summary": "Nested: resolve conflict",
                    "description": "Use conflict_id from GET .../answers; conflict_answer_id is the chosen answer row.",
                    "value": {
                        "updates": [
                            {
                                "q_id": "QID-001",
                                "conflict_id": "00000000-0000-0000-0000-000000000001",
                                "conflict_answer_id": "00000000-0000-0000-0000-000000000002",
                            }
                        ]
                    },
                },
                "flat_insert": {
                    "summary": "Flat: INSERT new answer text",
                    "value": {
                        "question_id": "QID-001",
                        "action": "INSERT",
                        "answers": [
                            {
                                "value": "Your answer text",
                                "confidence": 0.9,
                                "metadata": {},
                            }
                        ],
                    },
                },
                "flat_resolve": {
                    "summary": "Flat: RESOLVE (select existing answer_id)",
                    "value": {
                        "question_id": "QID-001",
                        "action": "RESOLVE",
                        "selected_answer_id": "00000000-0000-0000-0000-000000000000",
                    },
                },
            }
        ),
    ],
):
    """Insert answers (INSERT) and/or resolve current conflict (RESOLVE).

    **Do not** send Swagger's empty ``{"additionalProp1": {}}`` — pick an example from the
    dropdown in /docs, or paste JSON matching one of the shapes below.

    Additionally supports a FE "single q_id submission" payload:
      - direct answer (no `conflict_id`)
      - conflict winner selection (with `conflict_id` + `conflict_answer_id`)
      - optional user edit on the selected row: `is_user_override: true` and `override_value`
        (required together); updates `answers.answer_text` before finalization.

    Final answer selection is scoped per opportunity in
    ``opportunity_question_answers`` (deprecated: do not use
    ``sase_questions.final_answer_id``).

    **Auth:** ``Authorization: Bearer <Firebase ID token>`` (see dependency ``get_firebase_user``).
    """
    # ── ACL (role-based) ─────────────────────────────────────────────────────
    # Write access rule:
    # - ADMIN can post anywhere
    # - Opportunity owner (opportunities.owner_id == users.id) can post for that opportunity
    # - TEAM_LEAD can post for opportunities in teams they lead (team_members.is_lead)
    def _assert_can_post_answers(cur, user_id: int, user_obj: User) -> None:
        if is_admin(user_obj):
            return

        # One round-trip: opportunity row + whether this user leads the opp's team (if any).
        cur.execute(
            """
            SELECT
                o.owner_id,
                o.team_id,
                EXISTS (
                    SELECT 1
                    FROM team_members tm
                    WHERE tm.team_id = o.team_id
                      AND tm.user_id = %s
                      AND tm.is_lead = true
                ) AS user_leads_team
            FROM opportunities o
            WHERE o.opportunity_id = %s
            LIMIT 1
            """,
            (user_id, str(opportunity_id)),
        )
        opp_row = cur.fetchone()
        if not opp_row:
            raise HTTPException(status_code=404, detail="Opportunity not found")
        opp_owner_id = opp_row[0]
        opp_team_id = opp_row[1]
        user_leads_team = bool(opp_row[2])

        # Owner can always post for their own opportunity.
        if opp_owner_id is not None and int(opp_owner_id) == user_id:
            return

        # TEAM_LEAD: must lead the team that owns the opportunity.
        if not has_role(user_obj, "TEAM_LEAD"):
            raise HTTPException(status_code=403, detail="Access denied")
        if opp_team_id is None or not user_leads_team:
            raise HTTPException(status_code=403, detail="Access denied")

    # New payload: handle ONE OR MANY q-updates in a single request body.
    q_updates = (
        []
        if _should_use_flat_save_or_resolve(body)
        else _find_all_objects_with_key(body, "q_id")
    )
    if q_updates:
        # Validate opportunity id if FE provided it.
        fe_opp_id = body.get("opp_id") or body.get("opportunity_id")
        if fe_opp_id is not None and str(fe_opp_id) != str(opportunity_id):
            raise HTTPException(
                status_code=400,
                detail="opp_id does not match opportunity_id in URL.",
            )

        con = get_db_connection()
        try:
            cur = con.cursor()
            _assert_can_post_answers(cur, user.id, user)
            now = datetime.now(UTC)

            results: list[dict[str, Any]] = []
            touched_qids: list[str] = []
            # Accumulate feedback to persist AFTER the main commit so a
            # feedback failure never rolls back the answer selection.
            pending_feedback: list[dict[str, Any]] = []
            final_answer_updates: list[tuple[str, str, str]] = []

            # Fast path: common FE payload sends many "direct selections" (no conflict_id).
            # We can batch the DB work into a handful of set-based statements.
            has_any_conflict = any(_normalize_optional_str(u.get("conflict_id")) for u in q_updates)
            if not has_any_conflict:
                t_req0 = time.perf_counter()
                batch_rows: list[dict[str, Any]] = []
                for q_update in q_updates:
                    qid = str(q_update["q_id"])
                    selected_answer_id = _normalize_optional_str(q_update.get("answer_id"))
                    if not selected_answer_id:
                        raise HTTPException(
                            status_code=400,
                            detail="answer_id is required when conflict_id is not provided.",
                        )
                    status_str = _coerce_answers_status(q_update.get("status"), default="active")
                    is_user_override = bool(q_update.get("is_user_override", False))
                    override_text = _normalize_optional_str(q_update.get("override_value"))
                    if is_user_override and not override_text:
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                "override_value is required when is_user_override is true "
                                "(empty strings are not allowed)."
                            ),
                        )
                    batch_rows.append(
                        {
                            "question_id": qid,
                            "selected_answer_id": selected_answer_id,
                            "status_str": status_str,
                            "is_user_override": is_user_override,
                            "override_text": override_text,
                            "feedback_id": _normalize_optional_str(q_update.get("feedback_id")),
                            "feedback_type": q_update.get("feedback_type"),
                            "comments": _normalize_optional_str(q_update.get("comments")),
                        }
                    )

                # Validate + apply all updates in ONE DB round-trip (Cloud SQL latency dominates).
                t0 = time.perf_counter()
                placeholders = ",".join(["(%s,%s,%s,%s,%s,%s,%s)"] * len(batch_rows))
                params: list[Any] = []
                for r in batch_rows:
                    params.extend(
                        [
                            r["question_id"],
                            r["selected_answer_id"],
                            r["status_str"],
                            bool(r["is_user_override"]),
                            r.get("override_text"),
                            r.get("feedback_id"),
                            r.get("comments"),
                        ]
                    )
                cur.execute(
                    f"""
                    WITH v AS (
                        SELECT
                            x.question_id::varchar AS question_id,
                            x.selected_answer_id::varchar AS selected_answer_id,
                            x.status_str::varchar AS status_str,
                            x.is_user_override::boolean AS is_user_override,
                            NULLIF(x.override_text::text, '') AS override_text
                        FROM (VALUES {placeholders}) AS x(
                            question_id,
                            selected_answer_id,
                            status_str,
                            is_user_override,
                            override_text,
                            feedback_id,
                            comments
                        )
                    ),
                    valid AS (
                        SELECT v.question_id, v.selected_answer_id
                        FROM v
                        JOIN answers a
                          ON a.opportunity_id = %s
                         AND a.question_id = v.question_id
                         AND a.answer_id = v.selected_answer_id
                    ),
                    upd_override AS (
                        UPDATE answers a
                        SET answer_text = v.override_text,
                            is_user_override = true,
                            updated_at = %s
                        FROM v
                        WHERE v.is_user_override = true
                          AND v.override_text IS NOT NULL
                          AND a.opportunity_id = %s
                          AND a.question_id = v.question_id
                          AND a.answer_id = v.selected_answer_id
                        RETURNING 1
                    ),
                    upd_conflicts AS (
                        UPDATE conflicts c
                        SET status = 'ignored'
                        WHERE c.opportunity_id = %s
                          AND c.question_id IN (SELECT question_id FROM v)
                          AND c.status = 'pending'
                        RETURNING 1
                    ),
                    upd_answers AS (
                        UPDATE answers a
                        SET
                            is_active = false,
                            status = CASE
                                WHEN a.answer_id = v.selected_answer_id THEN v.status_str
                                ELSE 'inactive'
                            END,
                            has_conflicts = false,
                            needs_review = false,
                            answer_text = CASE
                                WHEN a.answer_id = v.selected_answer_id
                                 AND v.is_user_override = true
                                 AND v.override_text IS NOT NULL
                                THEN v.override_text
                                ELSE a.answer_text
                            END,
                            is_user_override = CASE
                                WHEN a.answer_id = v.selected_answer_id THEN v.is_user_override
                                ELSE a.is_user_override
                            END,
                            updated_at = %s
                        FROM v
                        WHERE a.opportunity_id = %s
                          AND a.question_id = v.question_id
                        RETURNING 1
                    )
                    SELECT
                        (SELECT COUNT(*) FROM v) AS requested,
                        (SELECT COUNT(*) FROM valid) AS valid_pairs
                    """,
                    tuple(params + [opportunity_id, now, opportunity_id, opportunity_id, now, opportunity_id]),
                )
                row = cur.fetchone()
                requested = int(row[0] or 0) if row else 0
                valid_pairs = int(row[1] or 0) if row else 0
                if requested != valid_pairs:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "One or more selected answer_id values do not belong to the "
                            "given question/opportunity."
                        ),
                    )
                qids = list(dict.fromkeys([r["question_id"] for r in batch_rows]))
                touched_qids.extend(qids)
                for r in batch_rows:
                    final_answer_updates.append(
                        (opportunity_id, r["question_id"], r["selected_answer_id"])
                    )
                logger.info(
                    "post_answers timing | bulk_apply_ms={} updates={}",
                    int((time.perf_counter() - t0) * 1000),
                    len(batch_rows),
                )

                # 6) Build results + feedback list (no extra DB work).
                for r in batch_rows:
                    if r["feedback_id"] and r["feedback_type"] is not None:
                        pending_feedback.append(
                            {
                                "feedback_id": r["feedback_id"],
                                "answer_id": r["selected_answer_id"],
                                "opportunity_id": opportunity_id,
                                "question_id": r["question_id"],
                                "feedback_type": r["feedback_type"],
                                "comments": r["comments"],
                            }
                        )
                    results.append(
                        {
                            "question_id": r["question_id"],
                            "answer_id": r["selected_answer_id"],
                            "final_answer_id": r["selected_answer_id"],
                            "conflict_id": None,
                            "answer_type": None,
                            "requirement_type": None,
                            "feedback_id": r["feedback_id"],
                        }
                    )
                logger.info(
                    "post_answers timing | fast_path_total_ms={} updates={} feedback_rows={}",
                    int((time.perf_counter() - t_req0) * 1000),
                    len(batch_rows),
                    len(pending_feedback),
                )
            else:
                # Conflict/mixed path: reduce DB round-trips by batching the "validation" SELECTs.
                # We fetch:
                # - conflict_id -> (question_id + participating answer_ids) in one query
                # - answer_id -> question_id (for this opportunity) in one query
                parsed_updates: list[dict[str, Any]] = []
                conflict_ids: list[str] = []
                selected_answer_ids: list[str] = []

                for q_update in q_updates:
                    qid = str(q_update["q_id"])
                    conflict_id = _normalize_optional_str(q_update.get("conflict_id"))
                    if conflict_id:
                        selected_answer_id = _normalize_optional_str(
                            q_update.get("conflict_answer_id")
                        )
                        if not selected_answer_id:
                            raise HTTPException(
                                status_code=400,
                                detail="conflict_answer_id is required when conflict_id is provided.",
                            )
                        conflict_ids.append(conflict_id)
                    else:
                        selected_answer_id = _normalize_optional_str(q_update.get("answer_id"))
                        if not selected_answer_id:
                            raise HTTPException(
                                status_code=400,
                                detail="answer_id is required when conflict_id is not provided.",
                            )

                    status_str = _coerce_answers_status(q_update.get("status"), default="active")
                    is_user_override = bool(q_update.get("is_user_override", False))
                    override_text = _normalize_optional_str(q_update.get("override_value"))
                    if is_user_override and not override_text:
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                "override_value is required when is_user_override is true "
                                "(empty strings are not allowed)."
                            ),
                        )

                    feedback_id = _normalize_optional_str(q_update.get("feedback_id"))
                    feedback_type = q_update.get("feedback_type")
                    comments = _normalize_optional_str(q_update.get("comments"))

                    selected_answer_ids.append(selected_answer_id)
                    parsed_updates.append(
                        {
                            "payload_qid": qid,
                            "conflict_id": conflict_id,
                            "selected_answer_id": selected_answer_id,
                            "status_str": status_str,
                            "is_user_override": is_user_override,
                            "override_text": override_text,
                            "feedback_id": feedback_id,
                            "feedback_type": feedback_type,
                            "comments": comments,
                        }
                    )

                conflict_question_by_id: dict[str, str] = {}
                conflict_answer_ids_by_id: dict[str, set[str]] = {}
                if conflict_ids:
                    cur.execute(
                        """
                        SELECT conflict_id, question_id, answer_id
                        FROM conflicts
                        WHERE opportunity_id = %s
                          AND conflict_id = ANY(%s::text[])
                        """,
                        (opportunity_id, list(dict.fromkeys(conflict_ids))),
                    )
                    for cid, qid_db, aid in cur.fetchall() or []:
                        cid_s = str(cid)
                        conflict_question_by_id[cid_s] = str(qid_db)
                        conflict_answer_ids_by_id.setdefault(cid_s, set()).add(str(aid))

                answer_question_by_id: dict[str, str] = {}
                if selected_answer_ids:
                    cur.execute(
                        """
                        SELECT answer_id, question_id
                        FROM answers
                        WHERE opportunity_id = %s
                          AND answer_id = ANY(%s::text[])
                        """,
                        (opportunity_id, list(dict.fromkeys(selected_answer_ids))),
                    )
                    for aid, qid_db in cur.fetchall() or []:
                        answer_question_by_id[str(aid)] = str(qid_db)

                # Validate and prepare two groups:
                # - direct (no conflict_id) → can reuse the existing set-based fast path
                # - conflict (conflict_id present) → apply set-based UPDATEs keyed by conflict_id
                direct_rows: list[dict[str, Any]] = []
                conflict_rows: list[dict[str, Any]] = []

                for u in parsed_updates:
                    conflict_id = u["conflict_id"]
                    selected_answer_id = u["selected_answer_id"]
                    payload_qid = u["payload_qid"]

                    effective_qid = payload_qid
                    if conflict_id:
                        effective_qid = conflict_question_by_id.get(conflict_id, "")
                        if not effective_qid:
                            raise HTTPException(
                                status_code=400,
                                detail="conflict_id not found for this opportunity.",
                            )
                        if selected_answer_id not in conflict_answer_ids_by_id.get(
                            conflict_id, set()
                        ):
                            raise HTTPException(
                                status_code=400,
                                detail="conflict_answer_id is not part of the provided pending conflict group.",
                            )
                        if str(payload_qid).strip() != str(effective_qid).strip():
                            logger.warning(
                                "Payload q_id={} does not match conflicts.question_id={} for conflict_id={}; "
                                "using DB value for final-answer mapping and answers.",
                                payload_qid,
                                effective_qid,
                                conflict_id,
                            )

                    ans_qid = answer_question_by_id.get(selected_answer_id)
                    if not ans_qid or str(ans_qid).strip() != str(effective_qid).strip():
                        raise HTTPException(
                            status_code=400,
                            detail="selected answer_id does not belong to this question/opportunity.",
                        )

                    row = {
                        "question_id": effective_qid,
                        "payload_qid": payload_qid,
                        "conflict_id": conflict_id,
                        "selected_answer_id": selected_answer_id,
                        "status_str": u["status_str"],
                        "is_user_override": bool(u["is_user_override"]),
                        "override_text": u.get("override_text"),
                        "feedback_id": u.get("feedback_id"),
                        "feedback_type": u.get("feedback_type"),
                        "comments": u.get("comments"),
                    }
                    if conflict_id:
                        conflict_rows.append(row)
                    else:
                        direct_rows.append(row)

                # 1) Apply direct (non-conflict) rows using the existing set-based statement.
                if direct_rows:
                    placeholders = ",".join(["(%s,%s,%s,%s,%s,%s,%s)"] * len(direct_rows))
                    params: list[Any] = []
                    for r in direct_rows:
                        params.extend(
                            [
                                r["question_id"],
                                r["selected_answer_id"],
                                r["status_str"],
                                bool(r["is_user_override"]),
                                r.get("override_text"),
                                r.get("feedback_id"),
                                r.get("comments"),
                            ]
                        )
                    cur.execute(
                        f"""
                        WITH v AS (
                            SELECT
                                x.question_id::varchar AS question_id,
                                x.selected_answer_id::varchar AS selected_answer_id,
                                x.status_str::varchar AS status_str,
                                x.is_user_override::boolean AS is_user_override,
                                NULLIF(x.override_text::text, '') AS override_text
                            FROM (VALUES {placeholders}) AS x(
                                question_id,
                                selected_answer_id,
                                status_str,
                                is_user_override,
                                override_text,
                                feedback_id,
                                comments
                            )
                        ),
                        valid AS (
                            SELECT v.question_id, v.selected_answer_id
                            FROM v
                            JOIN answers a
                              ON a.opportunity_id = %s
                             AND a.question_id = v.question_id
                             AND a.answer_id = v.selected_answer_id
                        ),
                        upd_override AS (
                            UPDATE answers a
                            SET answer_text = v.override_text,
                                is_user_override = true,
                                updated_at = %s
                            FROM v
                            WHERE v.is_user_override = true
                              AND v.override_text IS NOT NULL
                              AND a.opportunity_id = %s
                              AND a.question_id = v.question_id
                              AND a.answer_id = v.selected_answer_id
                            RETURNING 1
                        ),
                        upd_conflicts AS (
                            UPDATE conflicts c
                            SET status = 'ignored'
                            WHERE c.opportunity_id = %s
                              AND c.question_id IN (SELECT question_id FROM v)
                              AND c.status = 'pending'
                            RETURNING 1
                        ),
                        upd_answers AS (
                            UPDATE answers a
                            SET
                                is_active = false,
                                status = CASE
                                    WHEN a.answer_id = v.selected_answer_id THEN v.status_str
                                    ELSE 'inactive'
                                END,
                                has_conflicts = false,
                                needs_review = false,
                                answer_text = CASE
                                    WHEN a.answer_id = v.selected_answer_id
                                     AND v.is_user_override = true
                                     AND v.override_text IS NOT NULL
                                    THEN v.override_text
                                    ELSE a.answer_text
                                END,
                                is_user_override = CASE
                                    WHEN a.answer_id = v.selected_answer_id THEN v.is_user_override
                                    ELSE a.is_user_override
                                END,
                                updated_at = %s
                            FROM v
                            WHERE a.opportunity_id = %s
                              AND a.question_id = v.question_id
                            RETURNING 1
                        )
                        SELECT
                            (SELECT COUNT(*) FROM v) AS requested,
                            (SELECT COUNT(*) FROM valid) AS valid_pairs
                        """,
                        tuple(params + [opportunity_id, now, opportunity_id, opportunity_id, now, opportunity_id]),
                    )
                    row = cur.fetchone()
                    requested = int(row[0] or 0) if row else 0
                    valid_pairs = int(row[1] or 0) if row else 0
                    if requested != valid_pairs:
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                "One or more selected answer_id values do not belong to the "
                                "given question/opportunity."
                            ),
                        )

                # 2) Apply conflict rows with set-based UPDATEs keyed by conflict_id.
                if conflict_rows:
                    placeholders = ",".join(["(%s,%s,%s,%s,%s,%s,%s)"] * len(conflict_rows))
                    params2: list[Any] = []
                    for r in conflict_rows:
                        params2.extend(
                            [
                                r["conflict_id"],
                                r["question_id"],
                                r["selected_answer_id"],
                                r["status_str"],
                                bool(r["is_user_override"]),
                                r.get("override_text"),
                                r.get("comments"),
                            ]
                        )
                    cur.execute(
                        f"""
                        WITH v AS (
                            SELECT
                                x.conflict_id::varchar AS conflict_id,
                                x.question_id::varchar AS question_id,
                                x.selected_answer_id::varchar AS selected_answer_id,
                                x.status_str::varchar AS status_str,
                                x.is_user_override::boolean AS is_user_override,
                                NULLIF(x.override_text::text, '') AS override_text
                            FROM (VALUES {placeholders}) AS x(
                                conflict_id,
                                question_id,
                                selected_answer_id,
                                status_str,
                                is_user_override,
                                override_text,
                                comments
                            )
                        ),
                        upd_override AS (
                            UPDATE answers a
                            SET answer_text = v.override_text,
                                is_user_override = true,
                                updated_at = %s
                            FROM v
                            WHERE v.is_user_override = true
                              AND v.override_text IS NOT NULL
                              AND a.opportunity_id = %s
                              AND a.question_id = v.question_id
                              AND a.answer_id = v.selected_answer_id
                            RETURNING 1
                        ),
                        upd_conflicts AS (
                            UPDATE conflicts c
                            SET
                                status = 'resolved',
                                resolved_by = v.selected_answer_id,
                                resolved_at = %s
                            FROM v
                            WHERE c.opportunity_id = %s
                              AND c.conflict_id = v.conflict_id
                              AND c.question_id = v.question_id
                            RETURNING 1
                        ),
                        upd_answers AS (
                            UPDATE answers a
                            SET
                                is_active = false,
                                status = CASE
                                    WHEN a.answer_id = v.selected_answer_id THEN v.status_str
                                    ELSE 'inactive'
                                END,
                                has_conflicts = false,
                                needs_review = false,
                                is_user_override = CASE
                                    WHEN a.answer_id = v.selected_answer_id THEN v.is_user_override
                                    ELSE a.is_user_override
                                END,
                                answer_text = CASE
                                    WHEN a.answer_id = v.selected_answer_id
                                     AND v.is_user_override = true
                                     AND v.override_text IS NOT NULL
                                    THEN v.override_text
                                    ELSE a.answer_text
                                END,
                                updated_at = %s
                            FROM v, conflicts c
                            WHERE c.conflict_id = v.conflict_id
                              AND c.opportunity_id = %s
                              AND c.question_id = v.question_id
                              AND c.answer_id = a.answer_id
                              AND a.opportunity_id = %s
                              AND a.question_id = v.question_id
                            RETURNING 1
                        )
                        SELECT 1
                        """,
                        tuple(params2 + [now, opportunity_id, now, opportunity_id, now, opportunity_id, opportunity_id]),
                    )

                # 3) Build results + feedback + final_answer_updates (no extra DB reads).
                for r in direct_rows + conflict_rows:
                    qid2 = r["question_id"]
                    touched_qids.append(qid2)
                    final_answer_updates.append((opportunity_id, qid2, r["selected_answer_id"]))
                    if r.get("feedback_id") and r.get("feedback_type") is not None:
                        pending_feedback.append(
                            {
                                "feedback_id": r["feedback_id"],
                                "answer_id": r["selected_answer_id"],
                                "opportunity_id": opportunity_id,
                                "question_id": qid2,
                                "feedback_type": r["feedback_type"],
                                "comments": r.get("comments"),
                            }
                        )
                    results.append(
                        {
                            "question_id": qid2,
                            "answer_id": r["selected_answer_id"],
                            "final_answer_id": r["selected_answer_id"],
                            "conflict_id": r.get("conflict_id"),
                            "answer_type": None,
                            "requirement_type": None,
                            "feedback_id": r.get("feedback_id"),
                        }
                    )

            # Avoid N+1 queries: fetch question metadata for all touched q_ids in one round-trip.
            if touched_qids:
                q_meta = _sase_question_lookup_batch(cur, list(dict.fromkeys(touched_qids)))
                for r in results:
                    qid2 = str(r.get("question_id") or "")
                    ans_type, req_type = q_meta.get(qid2, (None, None))
                    r["answer_type"] = ans_type
                    r["requirement_type"] = req_type

            # Batch-upsert scoped final answers for all touched questions in one statement.
            if final_answer_updates:
                _batch_set_final_answer_ids(cur, final_answer_updates)

            # Persist feedback rows in the SAME transaction, but keep it non-fatal:
            # use a SAVEPOINT so failures roll back only feedback inserts.
            if pending_feedback:
                _svc = RagDataService()
                try:
                    cur.execute("SAVEPOINT sp_feedback")
                    _svc.save_feedback_batch(
                        pending_feedback, cur=cur, con=con, do_commit=False
                    )
                    cur.execute("RELEASE SAVEPOINT sp_feedback")
                except Exception:
                    try:
                        cur.execute("ROLLBACK TO SAVEPOINT sp_feedback")
                        cur.execute("RELEASE SAVEPOINT sp_feedback")
                    except Exception:
                        # If savepoint rollback fails, fall back to outer handler.
                        pass
                    logger.exception(
                        "Non-fatal: failed to save feedback batch | count={}",
                        len(pending_feedback),
                    )

            # Single commit for the whole request.
            con.commit()
        except Exception:
            # Best-effort rollback; if the socket dropped (pg8000 InterfaceError), rollback can fail.
            try:
                con.rollback()
            except Exception:
                pass
            raise
        finally:
            con.close()

        return {"status": "success", "results": results}

    # Backwards compatible: old INSERT/RESOLVE payload.
    flat_body: dict[str, Any] = dict(body) if isinstance(body, dict) else {}
    if flat_body.get("selected_answer_id") is None:
        aid = _normalize_optional_str(flat_body.get("answer_id"))
        if aid:
            flat_body["selected_answer_id"] = aid
    try:
        parsed_body = SaveOrResolveAnswersInput(**flat_body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Request body must match one of the supported shapes.",
                "validation_errors": exc.errors(),
                "expected": {
                    "shape_a_nested_q_id": (
                        "An object (or array of objects) that includes `q_id`, plus "
                        "`answer_id` or (`conflict_id` + `conflict_answer_id`). "
                        'Example: {"updates": [{"q_id": "QID-001", "answer_id": "..."}]}'
                    ),
                    "shape_b_flat": (
                        "SaveOrResolveAnswersInput: `question_id` (required), optional "
                        "`answers` [{value, confidence}], `selected_answer_id`, `action` "
                        '(INSERT|RESOLVE). Swagger\'s default {"additionalProp1": {}} is invalid.'
                    ),
                },
            },
        ) from exc
    con = get_db_connection()
    try:
        cur = con.cursor()
        _assert_can_post_answers(cur, user.id, user)
        now = datetime.now(UTC)

        qid = parsed_body.question_id
        action = (parsed_body.action or "INSERT").strip().upper()
        # Convenience: allow FE to omit `action` for pure "selection" submits.
        # If they only send `selected_answer_id` and no `answers`, treat as RESOLVE.
        if (
            action == "INSERT"
            and parsed_body.selected_answer_id
            and not parsed_body.answers
        ):
            action = "RESOLVE"

        if action == "RESOLVE":
            if not parsed_body.selected_answer_id:
                raise HTTPException(
                    status_code=400,
                    detail="selected_answer_id is required for RESOLVE.",
                )

            # Allow "direct answer" submissions too:
            # - If there is a pending conflict group, resolve it.
            # - If not, set scoped final answer on `opportunity_question_answers`.
            # Either way, update answers lifecycle so the selected answer becomes
            # the canonical one for that question.
            cur.execute(
                """
                SELECT answer_id
                FROM answers
                WHERE opportunity_id = %s AND question_id = %s AND answer_id = %s
                """,
                (opportunity_id, qid, parsed_body.selected_answer_id),
            )
            if not cur.fetchone():
                raise HTTPException(
                    status_code=400,
                    detail="selected_answer_id does not belong to this question/opportunity.",
                )

            # Identify the current pending conflict group for this question.
            cur.execute(
                """
                SELECT conflict_id
                FROM conflicts
                WHERE opportunity_id = %s
                  AND question_id = %s
                  AND status = 'pending'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (opportunity_id, qid),
            )
            row = cur.fetchone()
            conflict_id = row[0] if row else None
            if conflict_id:
                # Ensure the selected answer is part of the pending conflict group.
                cur.execute(
                    """
                    SELECT 1
                    FROM conflicts
                    WHERE conflict_id = %s
                      AND opportunity_id = %s
                      AND question_id = %s
                      AND answer_id = %s
                    LIMIT 1
                    """,
                    (conflict_id, opportunity_id, qid, parsed_body.selected_answer_id),
                )
                if not cur.fetchone():
                    raise HTTPException(
                        status_code=400,
                        detail="selected_answer_id is not part of the pending conflict group for this question.",
                    )

            # 1) Set scoped final_answer_id for this question.
            cur.execute(
                """
                INSERT INTO opportunity_question_answers (
                    opportunity_id,
                    question_id,
                    final_answer_id,
                    updated_at
                )
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (opportunity_id, question_id)
                DO UPDATE SET
                    final_answer_id = EXCLUDED.final_answer_id,
                    updated_at = NOW()
                """,
                (opportunity_id, qid, parsed_body.selected_answer_id),
            )

            # 2) Mark all answers as inactive; confirm only the selected one.
            # This works for both conflict and non-conflict questions.
            cur.execute(
                """
                UPDATE answers
                SET
                    is_active = false,
                    status = CASE
                        WHEN answer_id = %s THEN 'active'
                        ELSE 'inactive'
                    END,
                    updated_at = %s
                WHERE opportunity_id = %s
                  AND question_id = %s
                """,
                (parsed_body.selected_answer_id, now, opportunity_id, qid),
            )

            # 3) If this question had a conflict group, resolve it as well.
            if conflict_id:
                cur.execute(
                    """
                    UPDATE conflicts
                    SET
                        status = 'resolved',
                        resolved_by = %s,
                        resolved_at = %s
                    WHERE conflict_id = %s
                      AND opportunity_id = %s
                      AND question_id = %s
                    """,
                    (
                        parsed_body.selected_answer_id,
                        now,
                        conflict_id,
                        opportunity_id,
                        qid,
                    ),
                )

            con.commit()
            q_meta = _sase_question_lookup_batch(cur, [str(qid)])
            ans_type, req_type = q_meta.get(str(qid), (None, None))
            sid = parsed_body.selected_answer_id
            return {
                "status": "success",
                "question_id": qid,
                "answer_id": sid,
                "final_answer_id": sid,
                "conflict_id": conflict_id,
                "answer_type": ans_type,
                "requirement_type": req_type,
            }

        # Default: INSERT new answers (not just resolve).
        answers = parsed_body.answers or []
        if not answers:
            raise HTTPException(status_code=400, detail="answers must not be empty.")

        # Do not clear scoped final-answer mappings on multi-candidate INSERT. Prior
        # user selection stays until a new winner is chosen via POST submit.

        cur.execute(
            """
            UPDATE conflicts
            SET status = 'ignored'
            WHERE opportunity_id = %s AND question_id = %s AND status = 'pending'
            """,
            (opportunity_id, qid),
        )
        # Deactivate any currently-active conflict alternatives.
        cur.execute(
            """
            UPDATE answers
            SET is_active = false
            WHERE opportunity_id = %s AND question_id = %s AND is_active = true
            """,
            (opportunity_id, qid),
        )

        has_conflicts = len(answers) > 1
        conflict_id: str | None = None
        if has_conflicts:
            conflict_id = str(uuid.uuid4())

        # Embed inserted answer texts (batched) so we can persist answers.answer_embedding.
        answer_texts = [str(a.value or "") for a in answers]
        answer_vectors: list[list[float] | None] = [None] * len(answer_texts)
        try:
            vecs = embed_texts(answer_texts)
            if len(vecs) == len(answer_texts):
                answer_vectors = vecs
            else:
                logger.warning(
                    "embed_texts returned unexpected count; continuing without answer_embedding | expected={} got={}",
                    len(answer_texts),
                    len(vecs),
                )
        except Exception:
            logger.exception(
                "Non-fatal: failed to embed inserted answers; continuing without answer_embedding | opportunity_id={} question_id={}",
                opportunity_id,
                qid,
            )

        inserted_answer_ids: list[str] = []
        for a, vec in zip(answers, answer_vectors, strict=False):
            answer_id = str(uuid.uuid4())
            inserted_answer_ids.append(answer_id)

            # Insert answer row
            embedding_param: Any = vec
            if isinstance(embedding_param, list):
                embedding_param = "[" + ",".join(map(str, embedding_param)) + "]"
            cur.execute(
                """
                INSERT INTO answers (
                    answer_id,
                    opportunity_id,
                    question_id,
                    answer_text,
                    answer_embedding,
                    confidence_score,
                    reasoning,
                    source_count,
                    status,
                    current_version,
                    needs_review,
                    has_conflicts,
                    conflict_count,
                    primary_source,
                    is_active,
                    is_user_override,
                    created_at,
                    updated_at
                )
                VALUES (
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    0, 'pending',
                    1, false,
                    %s, %s,
                    NULL,
                    %s, false,
                    %s, %s
                )
                """,
                (
                    answer_id,
                    opportunity_id,
                    qid,
                    a.value,
                    embedding_param,
                    float(a.confidence),
                    (a.metadata or {}).get("reasoning", None),
                    has_conflicts,
                    (len(answers) if has_conflicts else 0),
                    has_conflicts,
                    now,
                    now,
                ),
            )

            # Insert answer version (keeps history consistent with other flows)
            version_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO answer_versions (
                    version_id, answer_id,
                    opportunity_id, question_id,
                    version, answer_text, confidence_score,
                    change_type, changed_by, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    version_id,
                    answer_id,
                    opportunity_id,
                    qid,
                    1,
                    a.value,
                    float(a.confidence),
                    "initial",
                    "ai",
                    now,
                ),
            )

        # If conflict, create a pending conflict group covering all inserted active answers.
        if has_conflicts and conflict_id:
            n_c = len(inserted_answer_ids)
            ph = ",".join(["(%s,%s,%s,%s,%s,'pending',%s)"] * n_c)
            c_params: list[Any] = []
            for answer_obj, answer_id in zip(answers, inserted_answer_ids, strict=True):
                c_params.extend(
                    [
                        conflict_id,
                        answer_id,
                        opportunity_id,
                        qid,
                        answer_obj.value,
                        now,
                    ]
                )
            cur.execute(
                f"""
                INSERT INTO conflicts (
                    conflict_id, answer_id, opportunity_id, question_id,
                    conflicting_value, status, created_at
                )
                VALUES {ph}
                """,
                c_params,
            )
        else:
            # Single-answer case: set scoped ``final_answer_id`` to the new row.
            single_answer_id = inserted_answer_ids[0]
            cur.execute(
                """
                INSERT INTO opportunity_question_answers (
                    opportunity_id,
                    question_id,
                    final_answer_id,
                    updated_at
                )
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (opportunity_id, question_id)
                DO UPDATE SET
                    final_answer_id = EXCLUDED.final_answer_id,
                    updated_at = NOW()
                """,
                (opportunity_id, qid, single_answer_id),
            )
            cur.execute(
                """
                UPDATE answers
                SET
                    status = 'active',
                is_active = false,
                    updated_at = %s
                WHERE opportunity_id = %s
                  AND question_id = %s
                  AND answer_id = %s
                """,
                (now, opportunity_id, qid, single_answer_id),
            )

        con.commit()
        q_meta_ins = _sase_question_lookup_batch(cur, [str(qid)])
        ans_type, req_type = q_meta_ins.get(str(qid), (None, None))
        out_insert: dict[str, Any] = {
            "status": "success",
            "question_id": qid,
            "final_answer_id": (
                inserted_answer_ids[0] if len(inserted_answer_ids) == 1 else None
            ),
            "conflict_id": conflict_id,
            "answer_type": ans_type,
            "requirement_type": req_type,
            "answer_ids": inserted_answer_ids,
        }
        if len(inserted_answer_ids) == 1:
            out_insert["answer_id"] = inserted_answer_ids[0]
        return out_insert
    finally:
        con.close()


# ─── Read Endpoints ──────────────────────────────────────────────────────────


@router.get("/{oid}/answers")
def get_answers(
    oid: str,
    user: Annotated[User, Depends(get_firebase_user)],
):
    """Return answers in FE-friendly grouped format.

    Requires ``Authorization: Bearer <Firebase ID token>``.

    Each item includes ``answer_type`` and ``requirement_type`` from ``sase_questions``
    when the row exists (``sase_questions.q_id`` = ``answers.question_id``), and
    ``answer_id`` from ``answers.answer_id`` when a single chosen row applies; under
    ``conflicts``, each candidate includes ``answer_id``.

    Response shape matches `samplejson.json`:
    - one entry per `answers.question_id` (only questions that exist in `answers`)
    - `answer_value` picked from the `answers` table only:
      - if exactly one row has status='active', that row is the main answer
      - else if there's only one total answer row for the question, that row is the main answer
      - else `answer_value` is null and all non-inactive candidates are returned under `conflicts`.

    Rows with ``status='inactive'`` are superseded and omitted. Both ``pending`` and ``active``
    are considered (RAG inserts ``pending``; resolution / single-answer flows set ``active``).
    """
    from src.services.database_manager.connection import get_db_connection

    oid_keys = gcs_path_prefix_candidates(oid)
    if not oid_keys:
        logger.warning("get_answers: empty oid path param")
        raise HTTPException(status_code=400, detail="opportunity id is required")

    logger.info(
        "get_answers: request oid_param={!r} resolved_keys={}",
        oid,
        oid_keys,
    )

    con = None
    try:
        con = get_db_connection()
        cur = con.cursor()

        # ACL: verified Firebase user -> users.id, then ensure the opportunity belongs to that user
        user_id = int(user.id)
        if not is_admin(user):
            if has_role(user, "TEAM_LEAD"):
                cur.execute(
                    """
                    SELECT 1
                    FROM opportunities o
                    WHERE o.opportunity_id = ANY(%s)
                      AND (
                        o.owner_id = %s OR
                        EXISTS (
                          SELECT 1
                          FROM team_members tm
                          WHERE tm.team_id = o.team_id
                            AND tm.user_id = %s
                            AND tm.is_lead = true
                        )
                      )
                    LIMIT 1
                    """,
                    (oid_keys, user_id, user_id),
                )
            elif has_role(user, "TEAM_MEMBER"):
                cur.execute(
                    """
                    SELECT 1
                    FROM opportunities o
                    WHERE o.opportunity_id = ANY(%s)
                      AND (
                        o.owner_id = %s OR
                        EXISTS (
                          SELECT 1
                          FROM team_members tm
                          WHERE tm.team_id = o.team_id
                            AND tm.user_id = %s
                        )
                      )
                    LIMIT 1
                    """,
                    (oid_keys, user_id, user_id),
                )
            else:
                cur.execute(
                    """
                    SELECT 1
                    FROM opportunities
                    WHERE opportunity_id = ANY(%s)
                      AND owner_id = %s
                    LIMIT 1
                    """,
                    (oid_keys, user_id),
                )

            if not cur.fetchone():
                raise HTTPException(status_code=403, detail="Access denied")

        # 1) Load all answers for this opportunity (try canonical + legacy DB keys).
        cur.execute(
            """
            SELECT
                opportunity_id,
                answer_id,
                question_id,
                answer_text,
                confidence_score,
                status,
                is_user_override,
                is_active,
                current_version
            FROM answers
            WHERE opportunity_id = ANY(%s)
              AND status IN ('active', 'pending')
            ORDER BY question_id ASC, created_at DESC
            """,
            (oid_keys,),
        )
        a_rows = cur.fetchall()
        matched_oid = a_rows[0][0] if a_rows else oid_keys[0]

        answers_by_q: dict[str, list[dict[str, Any]]] = {}
        for (
            _row_opp_id,
            answer_id,
            question_id,
            answer_text,
            confidence_score,
            status,
            is_user_override,
            is_active,
            current_version,
        ) in a_rows:
            # DB query already filtered to active/pending only.
            answers_by_q.setdefault(question_id, []).append({
                "answer_id": answer_id,
                "answer_value": answer_text,
                "confidence_score": float(confidence_score or 0.0),
                "status": status,
                "is_user_override": bool(is_user_override) if is_user_override is not None else False,
                "is_active": bool(is_active),
                "current_version": int(current_version) if current_version is not None else 1,
            })

        # 2) Load citations only for answers we’re returning (avoids pulling all opportunity citations).
        answer_ids: list[str] = [
            str(r[1]) for r in a_rows if r[1] is not None
        ]
        c_rows: list[tuple[Any, ...]] = []
        if answer_ids:
            cur.execute(
                """
                SELECT
                    answer_id,
                    source_type,
                    source_file,
                    source_name,
                    document_date,
                    chunk_id,
                    quote,
                    context,
                    page_number,
                    timestamp_str,
                    speaker,
                    relevance_score,
                    is_primary
                FROM citations
                WHERE opportunity_id = ANY(%s)
                  AND answer_id = ANY(%s)
                ORDER BY created_at ASC
                """,
                (oid_keys, answer_ids),
            )
            c_rows = cur.fetchall()
        citations_by_answer: dict[str, list[dict[str, Any]]] = {}
        for (
            answer_id,
            source_type,
            source_file,
            source_name,
            document_date,
            chunk_id,
            quote,
            context,
            page_number,
            timestamp_str,
            speaker,
            relevance_score,
            is_primary,
        ) in c_rows:
            citations_by_answer.setdefault(answer_id, []).append({
                "source_type": source_type,
                "source_file": source_file,
                "source_name": source_name,
                "document_date": str(document_date)
                if document_date is not None
                else None,
                "chunk_id": chunk_id,
                "quote": quote,
                "context": context,
                "page_number": page_number,
                "timestamp_str": timestamp_str,
                "speaker": speaker,
                "relevance_score": float(relevance_score or 0.0),
                "is_primary": bool(is_primary) if is_primary is not None else False,
            })

        logger.info(
            "get_answers: loaded answer_rows={} citation_rows={} questions={} matched_opportunity_id={}",
            len(a_rows),
            len(c_rows),
            len(answers_by_q),
            matched_oid,
        )

        qid_list = sorted(answers_by_q.keys())
        sase_meta = _sase_question_lookup_batch(cur, qid_list)

        out: list[dict[str, Any]] = []
        # Batch-load pending conflict ids for questions that have no chosen answer.
        # This avoids N+1 queries in the loop below.
        pending_conflict_id_by_qid: dict[str, str] = {}
        unresolved_qids: list[str] = []
        for qid in qid_list:
            all_q_answers = answers_by_q.get(qid, [])
            active_rows = [a for a in all_q_answers if a.get("status") == "active"]
            chosen: dict[str, Any] | None = None
            if len(active_rows) == 1:
                chosen = active_rows[0]
            elif len(all_q_answers) == 1:
                chosen = all_q_answers[0]
            if not chosen:
                unresolved_qids.append(qid)

        if unresolved_qids:
            cur.execute(
                """
                SELECT DISTINCT ON (question_id)
                    question_id,
                    conflict_id
                FROM conflicts
                WHERE opportunity_id = ANY(%s)
                  AND question_id = ANY(%s::text[])
                  AND status = 'pending'
                ORDER BY question_id, created_at DESC
                """,
                (oid_keys, unresolved_qids),
            )
            for qid, conflict_id in cur.fetchall() or []:
                pending_conflict_id_by_qid[str(qid)] = str(conflict_id)

        for qid in qid_list:
            all_q_answers = answers_by_q.get(qid, [])
            a_at, r_at = sase_meta.get(qid, (None, None))

            active_rows = [a for a in all_q_answers if a.get("status") == "active"]
            chosen: dict[str, Any] | None = None
            if len(active_rows) == 1:
                chosen = active_rows[0]
            elif len(all_q_answers) == 1:
                chosen = all_q_answers[0]

            if chosen:
                out.append({
                    "question_id": qid,
                    "answer_type": a_at,
                    "requirement_type": r_at,
                    "answer_id": chosen.get("answer_id"),
                    "answer_value": chosen.get("answer_value"),
                    "status": chosen.get("status"),
                    "confidence_score": chosen.get("confidence_score", 0.0),
                    "current_version": chosen.get("current_version", 1),
                    "is_user_override": bool(chosen.get("is_user_override", False)),
                    "status": chosen.get("status"),
                    "citations": citations_by_answer.get(chosen["answer_id"], []),
                    "conflict_id": None,
                    "conflicts": [],
                })
            else:
                # Attach current pending conflict_id (if any) for FE to resolve.
                pending_conflict_id = pending_conflict_id_by_qid.get(qid)

                candidates = list(all_q_answers)
                out.append({
                    "question_id": qid,
                    "answer_type": a_at,
                    "requirement_type": r_at,
                    "answer_id": None,
                    "answer_value": None,
                    "status": None,
                    "confidence_score": 0.0,
                    "status": None,
                    "citations": [],
                    "conflict_id": pending_conflict_id,
                    "conflicts": [
                        {
                            "answer_id": a.get("answer_id"),
                            "answer_value": a.get("answer_value"),
                            "status": a.get("status"),
                            "confidence_score": a.get("confidence_score", 0.0),
                            "current_version": a.get("current_version", 1),
                            "is_user_override": bool(a.get("is_user_override", False)),
                            "status": a.get("status"),
                            "citations": citations_by_answer.get(a["answer_id"], []),
                        }
                        for a in candidates
                    ],
                })

        return {
            "opportunity_id": matched_oid,
            "answers": out,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "get_answers failed | oid_param={!r} oid_keys={}",
            oid,
            oid_keys,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to load answers for this opportunity.",
        ) from exc
    finally:
        if con is not None:
            con.close()


@router.post("/gmail", response_model=EnsureSourceResponse)
def ensure_gmail_opportunity(
    body: EnsureSourceBody, db: Annotated[Session, Depends(get_db)]
):
    """Ensure an `opportunities` row and an `opportunity_sources` row (`source_type='gmail'`) exist.

    Call this to enable Gmail sync for an opportunity. The Gmail plugin searches for
    threads with `subject:"{oid}"`, so ensure emails related to this opportunity
    include the OID in the subject line.

    Requires the owner user to have completed Google OAuth (active ``user_connections`` row for provider ``google``).
    """
    email = body.owner_email.strip()
    try:
        oid = normalize_opportunity_oid(body.opportunity_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    name = body.name.strip()

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail=f"No user with email '{email}'. Complete Google OAuth first.",
        )
    google_conn = get_active_connection(db, user.id, "google")
    if not google_conn or not (google_conn.refresh_token or "").strip():
        raise HTTPException(
            status_code=400,
            detail=(
                f"User '{email}' has no active Google OAuth connection. "
                "Complete Google OAuth first."
            ),
        )

    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == oid).first()
    opportunity_created = False
    if not opp:
        opp = Opportunity(
            opportunity_id=oid,
            name=name,
            owner_id=user.id,
            status=STATUS_DISCOVERED,
            total_documents=0,
            processed_documents=0,
        )
        db.add(opp)
        db.flush()
        opportunity_created = True
        logger.info("Created opportunity oid={} id={}", oid, opp.id)

        try:
            RagDataService().init_opportunity(
                opportunity_id=oid,
                name=name,
                owner_id=str(user.id),
            )
            logger.info("RAG opportunities table seeded for oid={} (gmail ensure)", oid)
        except Exception:
            logger.exception("Failed to seed RAG opportunities table for oid={}", oid)

    gmail_src = (
        db
        .query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "gmail",
        )
        .first()
    )
    source_created = False
    if not gmail_src:
        gmail_src = OpportunitySource(opportunity_id=opp.id, source_type="gmail")
        db.add(gmail_src)
        db.flush()
        source_created = True
        logger.info("Created opportunity_sources gmail for opportunity_id={}", opp.id)

    db.commit()
    db.refresh(gmail_src)

    return EnsureSourceResponse(
        opportunity_id=opp.id,
        opportunity_id_string=opp.opportunity_id,
        name=opp.name,
        owner_id=opp.owner_id,
        source_id=gmail_src.id,
        source_type="gmail",
        opportunity_created=opportunity_created,
        source_created=source_created,
    )
