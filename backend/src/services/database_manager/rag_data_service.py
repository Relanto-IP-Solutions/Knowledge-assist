import math
import uuid
from datetime import UTC, datetime
from typing import Any

import ast
from src.services.database_manager.answers_legacy_unique import (
    drop_legacy_unique_one_row_per_question_on_answers,
)
from src.services.database_manager.connection import get_db_connection
from src.services.database_manager.opportunity_state import STATUS_DISCOVERED
from src.services.rag_engine.retrieval.embedding import embed_texts
from src.utils.logger import get_logger
from src.utils.opportunity_id import require_stored_opportunity_id


logger = get_logger(__name__)

ANSWER_CONFLICT_EMBEDDING_THRESHOLD = 0.90  # cosine similarity; below => conflict

def _drop_unique_opportunity_question_on_answers_if_present(cur: Any) -> None:
    """Drop legacy UNIQUE(opportunity_id, question_id) on ``public.answers`` if present."""
    drop_legacy_unique_one_row_per_question_on_answers(cur)


def _pg_is_unique_violation(exc: BaseException) -> bool:
    """Detect Postgres 23505 from pg8000 DatabaseError."""
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], dict):
        return args[0].get("C") == "23505"
    msg = str(exc).lower()
    return "23505" in msg and "unique" in msg


def _normalize_answer_text_for_compare(raw: object) -> str:
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""

    # Multi-select / picklist answers may be stored as a stringified Python list.
    # Canonicalize to avoid artificial conflicts from ordering/casing differences.
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = ast.literal_eval(s)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            toks = [str(x).strip().casefold() for x in parsed if str(x).strip()]
            toks.sort()
            return ",".join(toks)

    return s.casefold()


def _normalize_feedback_type_for_db(raw: Any) -> int:
    """Coerce FE values to integer feedback type codes (1..5).

    The DB stores feedback_type as an integer code in the range 1-5.
    - If the FE sends 1..5 (int or numeric string), we store it as-is.
    - Otherwise, default to 3 to avoid failing the request.
    """
    if raw is None:
        return 3

    if isinstance(raw, int):
        return raw if 1 <= raw <= 5 else 3

    s = str(raw).strip()
    if s.isdigit():
        n = int(s)
        return n if 1 <= n <= 5 else 3

    return 3


def _pgvector_param(val: Any) -> Any:
    """Convert list[float] to pgvector literal if adapter isn't active."""
    if isinstance(val, list):
        return "[" + ",".join(map(str, val)) + "]"
    return val


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=False):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        na += fx * fx
        nb += fy * fy
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _coerce_pgvector_to_list(raw: Any) -> list[float] | None:
    """Best-effort conversion of pgvector values into list[float].

    Depending on the DB driver/registration, pgvector columns may come back as:
    - list[float] (ideal)
    - string literal like "[0.1,0.2,...]"
    - None
    """
    if raw is None:
        return None
    if isinstance(raw, list):
        try:
            return [float(x) for x in raw]
        except Exception:
            return None
    if isinstance(raw, str):
        s = raw.strip()
        if not (s.startswith("[") and s.endswith("]")):
            return None
        inner = s[1:-1].strip()
        if not inner:
            return None
        try:
            return [float(x.strip()) for x in inner.split(",") if x.strip()]
        except Exception:
            return None
    return None


def _normalize_citation_source_type(raw: object) -> str:
    """Map retrieval/LLM source labels to ``citations.source_type`` values allowed by the DB.

    RAG chunks often use ``zoom_transcript``; ``citations.chk_citations_source_type`` expects
    short forms such as ``zoom``, ``slack``, ``drive`` (see opportunity_sources conventions).
    """
    # Keep this in sync with `create_pg_tables.py`:
    #   CHECK (source_type IN ('slack', 'zoom', 'pdf', 'docx', 'pptx', 'email'))
    allowed = {"slack", "zoom", "pdf", "docx", "pptx", "email"}
    if raw is None:
        return "unknown"
    s = str(raw).strip().lower()
    if not s:
        return "unknown"
    aliases: dict[str, str] = {
        "zoom_transcript": "zoom",
        "zoom_transcripts": "zoom",
        "slack_message": "slack",
        "slack_messages": "slack",
        # pgvector/ingestion paths
        "gdrive_doc": "docx",
        # legacy/alternate labels
        "google_drive": "docx",
        "gdrive": "docx",
        "drive": "docx",
        # file-type labels (best-effort defaults)
        "pdf": "pdf",
        "document": "docx",
        "documents": "docx",
        "doc": "docx",
        "docx": "docx",
        "pptx": "pptx",
        # email
        "gmail_message": "email",
        "gmail_messages": "email",
        "email": "email",
    }
    mapped = aliases.get(s, s)
    # If the mapping still doesn't fall into the DB-allowed set,
    # pick a safe default rather than failing the entire answers transaction.
    return mapped if mapped in allowed else "docx"


def _resolve_chunk_ids_for_citations(
    cur: Any,
    citations: list[dict[str, Any]],
    *,
    opportunity_id: str,
    question_id: str,
) -> None:
    """Drop chunk_id values that are not in chunk_registry.

    ``validate_citation_chunk_id`` rejects INSERTs when chunk_id is set but missing
    from chunk_registry (e.g. stale retrieval keys or path drift). Clearing avoids
    failing the whole answers/citations transaction.
    """
    if not citations:
        return
    ids: list[str] = []
    for c in citations:
        cid = c.get("chunk_id")
        if cid is not None and str(cid).strip():
            ids.append(str(cid).strip())
    if not ids:
        return
    ids = list(dict.fromkeys(ids))
    placeholders = ",".join(["%s"] * len(ids))
    cur.execute(
        f"SELECT chunk_id FROM chunk_registry WHERE chunk_id IN ({placeholders})",
        ids,
    )
    valid = {row[0] for row in cur.fetchall()}
    for c in citations:
        cid = c.get("chunk_id")
        if cid is None or not str(cid).strip():
            continue
        s = str(cid).strip()
        if s not in valid:
            logger.warning(
                "Citation chunk_id not in chunk_registry; clearing for insert | opportunity_id={} question_id={} chunk_id={}",
                opportunity_id,
                question_id,
                s[:200],
            )
            c["chunk_id"] = None


class RagDataService:
    """Service to handle RAG post-retrieval data insertions logic per the defined rules."""

    @staticmethod
    def _execute_step(
        cur, query: str, params: tuple, step: str, ctx: dict[str, Any]
    ) -> None:
        """Execute one SQL statement and log clear context on failure."""
        try:
            cur.execute(query, params)
        except Exception:
            logger.exception("DB step failed: {} | ctx={}", step, ctx)
            raise

    def init_opportunity(self, opportunity_id: str, name: str, owner_id: str) -> None:
        """
        1. opportunities: When opportunity is created -> INSERT
        """
        oid = require_stored_opportunity_id(opportunity_id)
        now = datetime.now(UTC)
        con = get_db_connection()
        try:
            cur = con.cursor()
            query = """
                INSERT INTO opportunities (
                    opportunity_id, name, owner_id, status,
                    total_documents, processed_documents,
                    last_extraction_at, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (opportunity_id) DO NOTHING
            """
            cur.execute(
                query,
                (oid, name, owner_id, STATUS_DISCOVERED, 0, 0, now, now, now),
            )
            con.commit()
            logger.info("Initialized opportunity: {}", oid)
        except Exception:
            con.rollback()
            logger.exception("Failed to initialize opportunity {}", oid)
            raise
        finally:
            con.close()

    def update_opportunity_status(
        self,
        opportunity_id: str,
        status: str = "IN_PROGRESS",
        doc_count: int = 0,
        processed_count: int = 0,
    ) -> None:
        """
        Update opportunity status and metrics during/after processing.
        """
        now = datetime.now(UTC)
        con = get_db_connection()
        try:
            cur = con.cursor()
            query = """
                UPDATE opportunities
                SET status = %s,
                    total_documents = %s,
                    processed_documents = %s,
                    last_extraction_at = %s,
                    updated_at = %s
                WHERE opportunity_id = %s
            """
            cur.execute(
                query, (status, doc_count, processed_count, now, now, opportunity_id)
            )
            con.commit()
            logger.info("Updated opportunity %s status to %s", opportunity_id, status)
        except Exception:
            con.rollback()
            logger.exception("Failed to update opportunity %s status", opportunity_id)
            raise
        finally:
            con.close()

    def update_opportunity_metrics(
        self, opportunity_id: str, doc_count: int, processed_count: int
    ) -> None:
        """
        1. opportunities: During processing -> UPDATE status & metrics
        """
        now = datetime.now(UTC)
        con = get_db_connection()
        try:
            cur = con.cursor()
            query = """
                UPDATE opportunities
                SET status = 'IN_PROGRESS',
                    total_documents = %s,
                    processed_documents = %s,
                    last_extraction_at = %s,
                    updated_at = %s
                WHERE opportunity_id = %s
            """
            cur.execute(query, (doc_count, processed_count, now, now, opportunity_id))
            con.commit()
            logger.info("Updated metrics for opportunity: %s", opportunity_id)
        except Exception:
            con.rollback()
            logger.exception("Failed to update opportunity metrics")
            raise
        finally:
            con.close()

    def allocate_next_opportunity_run_version(self, opportunity_id: str) -> int:
        """Return the next shared version number for one answer-generation batch.

        ``answer_versions.version`` was previously derived per question, so
        ``answers.current_version`` could differ within the same pipeline run (e.g. 94 vs 96).
        Call once before persisting all questions for a run and pass the result as
        ``run_version`` to :meth:`save_rag_answers` so every question in that run shares
        the same version.

        Uses ``GREATEST`` of max ``answer_versions.version`` and max ``answers.current_version``
        for the opportunity so gaps or legacy rows do not move the counter backward.
        """
        require_stored_opportunity_id(opportunity_id)
        con = get_db_connection()
        try:
            cur = con.cursor()
            self._execute_step(
                cur,
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"opp_answer_run_version:{opportunity_id}",),
                "acquire_opp_run_version_lock",
                {"opportunity_id": opportunity_id},
            )
            self._execute_step(
                cur,
                """
                SELECT GREATEST(
                    COALESCE(
                        (SELECT MAX(version) FROM answer_versions WHERE opportunity_id = %s),
                        0
                    ),
                    COALESCE(
                        (SELECT MAX(current_version) FROM answers WHERE opportunity_id = %s),
                        0
                    )
                )
                """,
                (opportunity_id, opportunity_id),
                "select_max_version_across_opportunity",
                {"opportunity_id": opportunity_id},
            )
            row = cur.fetchone()
            max_v = int((row[0] if row else 0) or 0)
            next_v = max_v + 1
            con.commit()
            logger.info(
                "Allocated opportunity-wide run version | opportunity_id={} run_version={} (max_seen={})",
                opportunity_id,
                next_v,
                max_v,
            )
            return next_v
        except Exception:
            con.rollback()
            logger.exception(
                "allocate_next_opportunity_run_version failed | opportunity_id={}",
                opportunity_id,
            )
            raise
        finally:
            con.close()

    def ensure_answers_allows_multiple_rows_per_question(self) -> None:
        """Drop ``UNIQUE (opportunity_id, question_id)`` on ``answers`` if the DB has it.

        Required for answer-generation when inserting a new ``answer_id`` per run (see
        ``insert_new_answer_row``). Production uses ``uq_answers_opp_question`` in some envs.
        The app DB user needs ``ALTER TABLE`` on ``answers``.
        """
        con = get_db_connection()
        try:
            cur = con.cursor()
            _drop_unique_opportunity_question_on_answers_if_present(cur)
            con.commit()
            logger.info(
                "Ensured answers can store multiple rows per question_id (dropped uq_answers_opp_question if present)"
            )
        except Exception:
            con.rollback()
            logger.exception("ensure_answers_allows_multiple_rows_per_question failed")
            raise
        finally:
            con.close()

    def save_rag_answers(
        self,
        opportunity_id: str,
        question_id: str,
        question_text: str,
        answers_list: list[dict[str, Any]],
        version_id: str,
        has_conflicts: bool | None = None,
        conflict_count: int | None = None,
        run_version: int | None = None,
        insert_new_answer_row: bool = False,
    ) -> None:
        """
        Core Transaction for RAG pipeline outputs:
        - 2. answers: INSERT (all), or UPDATE in place when the DB enforces one row per
          (opportunity_id, question_id) and exactly one candidate is returned
        - 3. answer_versions: INSERT (new ``version`` on each run)
        - 4. citations: INSERT
        - 5. conflicts: INSERT (if multiple answers; skipped for single-row reuse)

        If ``run_version`` is set (e.g. from :meth:`allocate_next_opportunity_run_version`),
        it is used as ``answers.current_version`` / ``answer_versions.version`` for this
        question instead of per-question ``MAX(version)+1``.

        If ``insert_new_answer_row`` is True (answer-generation pipeline), always INSERT a
        new ``answers`` row with a fresh ``answer_id`` instead of UPDATE-in-place on the
        sole existing row. Prior rows stay in the table (may be set inactive by conflict
        rules). Primary key remains ``(opportunity_id, answer_id)``; each run uses a new
        ``answer_id`` (UUID) so multiple rows per ``question_id`` are allowed when the DB
        has no extra unique on ``(opportunity_id, question_id)``.
        """
        require_stored_opportunity_id(opportunity_id)
        if not answers_list:
            logger.warning(
                "No answers provided for opportunity %s, question %s",
                opportunity_id,
                question_id,
            )
            return

        now = datetime.now(UTC)
        con = get_db_connection()
        try:
            cur = con.cursor()
            run_token = f"pipeline_run:{version_id}"

            # Serialize writes per (opportunity_id, question_id) to avoid double-ingestion
            # from near-simultaneous duplicate invocations.
            self._execute_step(
                cur,
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"{opportunity_id}:{question_id}",),
                "acquire_question_ingest_lock",
                {"opportunity_id": opportunity_id, "question_id": question_id},
            )

            logger.info(
                "save_rag_answers started | opportunity_id={} question_id={} answers={}",
                opportunity_id,
                question_id,
                len(answers_list),
            )

            candidate_records = []
            for answer_idx, ans in enumerate(answers_list, start=1):
                candidate_records.append({
                    "answer_id": str(uuid.uuid4()),
                    "answer_text": ans.get("answer_text", ""),
                    "confidence_score": ans.get("confidence_score", 0.0),
                    "reasoning": ans.get("reasoning", ""),
                    "citations": ans.get("citations", []),
                    "answer_idx": answer_idx,
                })

            # Unique (opportunity_id, question_id) allows only one answers row per question.
            # Multi-candidate conflict flows would INSERT N>1 rows and fail with 23505 on the
            # second insert — the whole question rolls back and nothing is stored for it.
            if len(candidate_records) > 1:
                logger.warning(
                    "Multiple answer candidates for one question; persisting primary only "
                    "(unique opportunity_id+question_id on answers). | opportunity_id=%s question_id=%s n=%d",
                    opportunity_id,
                    question_id,
                    len(candidate_records),
                )
                candidate_records = [candidate_records[0]]

            # Some deployments add UNIQUE (opportunity_id, question_id) on ``answers`` so only
            # one row per question exists. In that case we must UPDATE the existing row and
            # append a new ``answer_versions`` row instead of INSERTing a second answers row.
            self._execute_step(
                cur,
                """
                SELECT COUNT(*)::bigint
                FROM answers
                WHERE opportunity_id = %s AND question_id = %s
                """,
                (opportunity_id, question_id),
                "count_existing_answers_for_question",
                {"opportunity_id": opportunity_id, "question_id": question_id},
            )
            ec_row = cur.fetchone()
            existing_answer_count = int(ec_row[0] if ec_row else 0)
            insert_new_effective = bool(insert_new_answer_row)
            if insert_new_effective:
                try:
                    # DROP errors abort the whole transaction unless rolled back to a savepoint.
                    cur.execute("SAVEPOINT savepoint_drop_uq_answers")
                    _drop_unique_opportunity_question_on_answers_if_present(cur)
                    cur.execute("RELEASE SAVEPOINT savepoint_drop_uq_answers")
                except Exception as exc:
                    try:
                        cur.execute("ROLLBACK TO SAVEPOINT savepoint_drop_uq_answers")
                    except Exception:
                        pass
                    logger.warning(
                        "Could not DROP uq_answers_opp_question in this transaction; "
                        "will UPDATE existing row if exactly one | opportunity_id={} question_id={} err={!r}",
                        opportunity_id,
                        question_id,
                        exc,
                    )
                    insert_new_effective = False
            reuse_single_row = (
                existing_answer_count == 1
                and len(candidate_records) == 1
                and not insert_new_effective
            )
            if reuse_single_row:
                self._execute_step(
                    cur,
                    """
                    SELECT answer_id
                    FROM answers
                    WHERE opportunity_id = %s AND question_id = %s
                    LIMIT 1
                    """,
                    (opportunity_id, question_id),
                    "select_sole_answer_id_for_reuse",
                    {"opportunity_id": opportunity_id, "question_id": question_id},
                )
                sole = cur.fetchone()
                if sole and sole[0]:
                    candidate_records[0]["answer_id"] = sole[0]

            if run_version is not None:
                next_version = int(run_version)
            elif reuse_single_row:
                self._execute_step(
                    cur,
                    """
                    SELECT COALESCE(MAX(version), 0)
                    FROM answer_versions
                    WHERE opportunity_id = %s AND question_id = %s AND answer_id = %s
                    """,
                    (
                        opportunity_id,
                        question_id,
                        candidate_records[0]["answer_id"],
                    ),
                    "select_latest_answer_version_for_reused_row",
                    {
                        "opportunity_id": opportunity_id,
                        "question_id": question_id,
                        "answer_id": candidate_records[0]["answer_id"],
                    },
                )
                latest_version_row = cur.fetchone()
                current_version = (latest_version_row[0] if latest_version_row else 0) or 0
                next_version = current_version + 1
            else:
                # Align with allocate_next_opportunity_run_version: use the higher of
                # max(answer_versions.version) and max(answers.current_version) for this
                # question so we never insert version 1 when answers rows already show v98+.
                self._execute_step(
                    cur,
                    """
                    SELECT GREATEST(
                        COALESCE((
                            SELECT MAX(version) FROM answer_versions
                            WHERE opportunity_id = %s AND question_id = %s
                        ), 0),
                        COALESCE((
                            SELECT MAX(current_version) FROM answers
                            WHERE opportunity_id = %s AND question_id = %s
                        ), 0)
                    )
                    """,
                    (opportunity_id, question_id, opportunity_id, question_id),
                    "select_latest_version_merged_for_question",
                    {"opportunity_id": opportunity_id, "question_id": question_id},
                )
                latest_version_row = cur.fetchone()
                current_version = (latest_version_row[0] if latest_version_row else 0) or 0
                next_version = current_version + 1

            inserted_answer_records = []
            total_citations_inserted = 0

            # Do not clear scoped final-answer mappings here. User selections are tracked in
            # opportunity_question_answers per (opportunity_id, question_id).

            # New generation run: clear pending conflict rows for this question.
            # We'll compute new conflict state after comparing old active vs new candidates.
            self._execute_step(
                cur,
                """
                UPDATE conflicts
                SET status = 'ignored',
                    resolution_reason = %s,
                    resolved_at = %s
                WHERE opportunity_id = %s
                  AND question_id = %s
                  AND status = 'pending'
                """,
                (
                    "Superseded by newer answer generation",
                    now,
                    opportunity_id,
                    question_id,
                ),
                "ignore_existing_pending_conflicts",
                {"opportunity_id": opportunity_id, "question_id": question_id},
            )

            # Compare new generation against the prior *active* answer only (embedding / text).
            # Pending rows from earlier runs are not used as the semantic baseline, but are
            # superseded after insert when ``insert_new_answer_row`` (see below).
            self._execute_step(
                cur,
                """
                SELECT answer_id, answer_text, answer_embedding
                FROM answers
                WHERE opportunity_id = %s
                  AND question_id = %s
                  AND status = 'active'
                ORDER BY
                    updated_at DESC,
                    created_at DESC
                LIMIT 1
                """,
                (opportunity_id, question_id),
                "select_latest_active_or_is_active_answer",
                {"opportunity_id": opportunity_id, "question_id": question_id},
            )
            old_active_row = cur.fetchone()
            old_active_answer_id = old_active_row[0] if old_active_row else None
            old_active_text = old_active_row[1] if old_active_row else None
            old_active_embedding = (
                _coerce_pgvector_to_list(old_active_row[2]) if old_active_row else None
            )
            old_active_norm = _normalize_answer_text_for_compare(old_active_text)

            # Embed candidate answer text (batched) so we can persist in answers.answer_embedding.
            try:
                # Vertex embedding API rejects empty strings; embed only non-empty answers
                # and leave empty answers with null embedding.
                texts = [str(r.get("answer_text") or "") for r in candidate_records]
                non_empty: list[str] = []
                non_empty_idxs: list[int] = []
                for idx, t in enumerate(texts):
                    if t and t.strip():
                        non_empty.append(t)
                        non_empty_idxs.append(idx)

                vectors: list[list[float]] = []
                if non_empty:
                    vectors = embed_texts(non_empty)
                    if len(vectors) != len(non_empty_idxs):
                        raise RuntimeError(
                            f"embed_texts returned {len(vectors)} vectors for {len(non_empty_idxs)} non-empty texts"
                        )

                for rec in candidate_records:
                    rec["answer_embedding"] = None
                for idx, vec in zip(non_empty_idxs, vectors, strict=True):
                    candidate_records[idx]["answer_embedding"] = vec
            except Exception:
                logger.exception(
                    "Non-fatal: failed to embed answers; continuing without answer_embedding | opportunity_id={} question_id={}",
                    opportunity_id,
                    question_id,
                )
                for rec in candidate_records:
                    rec["answer_embedding"] = None

            for record in candidate_records:
                primary_source = (
                    (
                        record["citations"][0].get("source_name")
                        or record["citations"][0].get("source_file")
                    )
                    if record["citations"]
                    else None
                )

                if reuse_single_row:
                    logger.info(
                        "Updating answer row (reuse, new version) | opportunity_id=%s question_id=%s answer_id=%s version=%d",
                        opportunity_id,
                        question_id,
                        record["answer_id"],
                        next_version,
                    )
                    if not str(record.get("answer_text") or "").strip():
                        # "No generation" in single-row mode: we cannot insert a new answers row,
                        # so keep the existing answer value intact and just demote it to pending.
                        self._execute_step(
                            cur,
                            """
                            UPDATE answers
                            SET
                                status = 'pending',
                                current_version = %s,
                                needs_review = false,
                                has_conflicts = false,
                                conflict_count = 0,
                                is_active = false,
                                is_user_override = false,
                                updated_at = %s
                            WHERE opportunity_id = %s
                              AND question_id = %s
                              AND answer_id = %s
                            """,
                            (
                                next_version,
                                now,
                                opportunity_id,
                                question_id,
                                record["answer_id"],
                            ),
                            "demote_answer_reuse_single_row_on_empty_generation",
                            {
                                "opportunity_id": opportunity_id,
                                "question_id": question_id,
                                "answer_id": record["answer_id"],
                                "version": next_version,
                            },
                        )
                    else:
                        self._execute_step(
                            cur,
                            """
                            UPDATE answers
                            SET
                                answer_text = %s,
                                confidence_score = %s,
                                reasoning = %s,
                                source_count = %s,
                                status = 'pending',
                                current_version = %s,
                                needs_review = false,
                                has_conflicts = false,
                                conflict_count = 0,
                                primary_source = %s,
                                is_active = false,
                                is_user_override = false,
                                updated_at = %s,
                                answer_embedding = %s
                            WHERE opportunity_id = %s
                              AND question_id = %s
                              AND answer_id = %s
                            """,
                            (
                                record["answer_text"],
                                record["confidence_score"],
                                record["reasoning"],
                                len(record["citations"]),
                                next_version,
                                primary_source,
                                now,
                                _pgvector_param(record.get("answer_embedding")),
                                opportunity_id,
                                question_id,
                                record["answer_id"],
                            ),
                            "update_answer_reuse_single_row",
                            {
                                "opportunity_id": opportunity_id,
                                "question_id": question_id,
                                "answer_id": record["answer_id"],
                                "version": next_version,
                            },
                        )
                else:
                    logger.info(
                        "Inserting answer row | opportunity_id=%s question_id=%s answer_id=%s version=%d conflicts=%s",
                        opportunity_id,
                        question_id,
                        record["answer_id"],
                        next_version,
                        has_conflicts,
                    )

                    try:
                        # INSERT failure (e.g. 23505) aborts the transaction; use a savepoint so
                        # fallback SELECT/UPDATE can run without 25P02.
                        cur.execute("SAVEPOINT savepoint_insert_answer")
                        self._execute_step(
                            cur,
                            """
                            INSERT INTO answers (
                                answer_id, opportunity_id, question_id, answer_text,
                                confidence_score, reasoning, source_count, status,
                                current_version, needs_review, has_conflicts, conflict_count,
                                primary_source, is_active, is_user_override, created_at, updated_at,
                                answer_embedding
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s, false, false, 0, %s, false, false, %s, %s, %s)
                            """,
                            (
                                record["answer_id"],
                                opportunity_id,
                                question_id,
                                record["answer_text"],
                                record["confidence_score"],
                                record["reasoning"],
                                len(record["citations"]),
                                next_version,
                                primary_source,
                                now,
                                now,
                                _pgvector_param(record.get("answer_embedding")),
                            ),
                            "insert_answer",
                            {
                                "opportunity_id": opportunity_id,
                                "question_id": question_id,
                                "answer_id": record["answer_id"],
                                "version": next_version,
                            },
                        )
                        cur.execute("RELEASE SAVEPOINT savepoint_insert_answer")
                    except Exception as insert_exc:
                        try:
                            cur.execute("ROLLBACK TO SAVEPOINT savepoint_insert_answer")
                        except Exception:
                            pass
                        if not (
                            _pg_is_unique_violation(insert_exc)
                            and existing_answer_count == 1
                            and len(candidate_records) == 1
                        ):
                            raise insert_exc
                        logger.warning(
                            "INSERT answers hit 23505 (uq_answers_opp_question); falling back to UPDATE in place | opportunity_id={} question_id={}",
                            opportunity_id,
                            question_id,
                        )
                        self._execute_step(
                            cur,
                            """
                            SELECT answer_id
                            FROM answers
                            WHERE opportunity_id = %s AND question_id = %s
                            LIMIT 1
                            """,
                            (opportunity_id, question_id),
                            "select_sole_answer_id_after_23505",
                            {"opportunity_id": opportunity_id, "question_id": question_id},
                        )
                        sole = cur.fetchone()
                        if not sole or not sole[0]:
                            raise insert_exc
                        record["answer_id"] = sole[0]
                        self._execute_step(
                            cur,
                            """
                            UPDATE answers
                            SET
                                answer_text = %s,
                                confidence_score = %s,
                                reasoning = %s,
                                source_count = %s,
                                status = 'pending',
                                current_version = %s,
                                needs_review = false,
                                has_conflicts = false,
                                conflict_count = 0,
                                primary_source = %s,
                                is_active = false,
                                is_user_override = false,
                                updated_at = %s,
                                answer_embedding = %s
                            WHERE opportunity_id = %s
                              AND question_id = %s
                              AND answer_id = %s
                            """,
                            (
                                record["answer_text"],
                                record["confidence_score"],
                                record["reasoning"],
                                len(record["citations"]),
                                next_version,
                                primary_source,
                                now,
                                _pgvector_param(record.get("answer_embedding")),
                                opportunity_id,
                                question_id,
                                record["answer_id"],
                            ),
                            "update_answer_after_insert_23505",
                            {
                                "opportunity_id": opportunity_id,
                                "question_id": question_id,
                                "answer_id": record["answer_id"],
                                "version": next_version,
                            },
                        )
                inserted_answer_records.append(record)

                logger.info(
                    "Processing answer version | opportunity_id={} question_id={} answer_idx={}/{} answer_id={} citations={}",
                    opportunity_id,
                    question_id,
                    record["answer_idx"],
                    len(candidate_records),
                    record["answer_id"],
                    len(record["citations"]),
                )

                answer_version_id = str(uuid.uuid4())
                self._execute_step(
                    cur,
                    """
                    INSERT INTO answer_versions (
                        version_id, answer_id, opportunity_id, question_id,
                        version, answer_text, confidence_score, change_type, change_reason, changed_by, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        answer_version_id,
                        record["answer_id"],
                        opportunity_id,
                        question_id,
                        next_version,
                        record["answer_text"],
                        record["confidence_score"],
                        "initial",
                        run_token,
                        "ai",
                        now,
                    ),
                    "insert_answer_version",
                    {
                        "opportunity_id": opportunity_id,
                        "question_id": question_id,
                        "answer_id": record["answer_id"],
                        "version_id": answer_version_id,
                        "version": next_version,
                    },
                )

                # 4. Insert into citations (full schema)
                _resolve_chunk_ids_for_citations(
                    cur,
                    record["citations"],
                    opportunity_id=opportunity_id,
                    question_id=question_id,
                )
                for citation_idx, cit in enumerate(record["citations"], start=1):
                    citation_id = str(uuid.uuid4())
                    self._execute_step(
                        cur,
                        """
                        INSERT INTO citations (
                            citation_id,
                            answer_id,
                            conflict_id,
                            opportunity_id,
                            question_id,
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
                            created_at,
                            version_id
                        )
                        VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s
                        )
                        """,
                        (
                            citation_id,
                            record["answer_id"],
                            cit.get("conflict_id"),
                            opportunity_id,
                            question_id,
                            _normalize_citation_source_type(cit.get("source_type")),
                            cit.get("source_file"),
                            cit.get("source_name"),
                            cit.get("document_date"),
                            cit.get("chunk_id"),
                            cit.get("quote"),
                            cit.get("context"),
                            cit.get("page_number"),
                            cit.get("timestamp") or cit.get("timestamp_str"),
                            cit.get("speaker"),
                            cit.get("relevance_score"),
                            bool(cit.get("is_primary"))
                            if cit.get("is_primary") is not None
                            else False,
                            now,
                            answer_version_id,
                        ),
                        "insert_citation",
                        {
                            "opportunity_id": opportunity_id,
                            "question_id": question_id,
                            "answer_id": record["answer_id"],
                            "citation_id": citation_id,
                            "citation_idx": citation_idx,
                        },
                    )
                    total_citations_inserted += 1

            conflicts_inserted = 0
            inserted_answer_ids = [r["answer_id"] for r in inserted_answer_records]

            # When reuse_single_row: answers row was UPDATEd in the loop; skip multi-row
            # conflict detection (would archive or duplicate the same row).

            if not reuse_single_row:
                inserted_norm_values = {
                    _normalize_answer_text_for_compare(r["answer_text"])
                    for r in inserted_answer_records
                }

                # Special-case: when one side is empty, do not create a conflict group.
                #
                # Desired behavior:
                # - old has value + new empty  => old -> pending, new -> inactive
                # - old empty + new has value  => old -> inactive, new -> pending
                # - old empty + new empty      => old -> inactive, new -> pending (let user decide)
                #
                # Note: "pending" rows here are *not* conflict candidates (is_active=false).
                old_has_value = bool(str(old_active_text or "").strip())
                new_has_value = any(
                    bool(str(r.get("answer_text") or "").strip())
                    for r in inserted_answer_records
                )
                any_new_row = bool(inserted_answer_records)
                new_all_empty = any_new_row and (not new_has_value)
                new_all_non_empty = any_new_row and new_has_value
                # Only apply this special-case when there is an old active row AND we inserted
                # a new generation row (even if empty).
                should_short_circuit_no_conflict = bool(old_active_answer_id) and any_new_row and (
                    (old_has_value and new_all_empty)
                    or ((not old_has_value) and new_all_non_empty)
                    or ((not old_has_value) and new_all_empty)
                )
                keep_old_active_pending_due_to_empty_generation = False

                should_create_conflict = False
                conflict_answer_ids: list[str] = []

                if should_short_circuit_no_conflict:
                    # Update old row status based on which side has value.
                    old_new_status = "pending" if old_has_value and new_all_empty else "inactive"
                    keep_old_active_pending_due_to_empty_generation = (old_new_status == "pending")
                    self._execute_step(
                        cur,
                        """
                        UPDATE answers
                        SET status = %s,
                            is_active = false,
                            has_conflicts = false,
                            needs_review = false,
                            conflict_count = 0,
                            updated_at = %s
                        WHERE opportunity_id = %s
                          AND question_id = %s
                          AND answer_id = %s
                        """,
                        (
                            old_new_status,
                            now,
                            opportunity_id,
                            question_id,
                            old_active_answer_id,
                        ),
                        "update_old_active_on_empty_value_short_circuit",
                        {
                            "opportunity_id": opportunity_id,
                            "question_id": question_id,
                            "answer_id": old_active_answer_id,
                            "old_has_value": old_has_value,
                            "new_has_value": new_has_value,
                            "old_new_status": old_new_status,
                        },
                    )

                    # Update new rows status based on whether there is any new value.
                    # If new is empty and old had value => new inactive
                    # If new has value OR both empty     => new pending
                    new_new_status = "inactive" if (old_has_value and new_all_empty) else "pending"
                    self._execute_step(
                        cur,
                        """
                        UPDATE answers
                        SET status = %s,
                            is_active = false,
                            has_conflicts = false,
                            needs_review = false,
                            conflict_count = 0,
                            updated_at = %s
                        WHERE opportunity_id = %s
                          AND question_id = %s
                          AND answer_id = ANY(%s::text[])
                        """,
                        (
                            new_new_status,
                            now,
                            opportunity_id,
                            question_id,
                            inserted_answer_ids,
                        ),
                        "update_new_rows_on_empty_value_short_circuit",
                        {
                            "opportunity_id": opportunity_id,
                            "question_id": question_id,
                            "inserted_count": len(inserted_answer_ids),
                            "old_has_value": old_has_value,
                            "new_has_value": new_has_value,
                            "new_new_status": new_new_status,
                        },
                    )
                else:
                    # Picklist questions keep the legacy "text differs => conflict" behavior.
                    # For non-picklist questions, prefer embedding similarity vs previous active answer.
                    #
                    # IMPORTANT: do NOT infer picklist-ness solely from sase_picklist_options presence;
                    # that table can contain stale rows. Prefer sase_questions.answer_type.
                    self._execute_step(
                        cur,
                        "SELECT answer_type FROM sase_questions WHERE q_id = %s LIMIT 1",
                        (question_id,),
                        "load_sase_question_answer_type",
                        {"question_id": question_id},
                    )
                    row_at = cur.fetchone()
                    answer_type = (
                        str(row_at[0]).strip().lower()
                        if row_at and row_at[0] is not None
                        else ""
                    )

                    self._execute_step(
                        cur,
                        "SELECT 1 FROM sase_picklist_options WHERE q_id = %s LIMIT 1",
                        (question_id,),
                        "check_picklist_options",
                        {"question_id": question_id},
                    )
                    has_picklist_options = bool(cur.fetchone())
                    is_picklist_question = (
                        answer_type in {"picklist", "multi_select"}
                    ) or has_picklist_options
                    logger.bind(
                        opportunity_id=opportunity_id,
                        question_id=question_id,
                    ).info(
                        "Conflict mode selection | answer_type={} has_picklist_options={} is_picklist_question={}",
                        answer_type or None,
                        has_picklist_options,
                        is_picklist_question,
                    )

                    if old_active_answer_id:
                        # Case A: detect conflict against previous active.
                        is_conflict = False

                        has_old_vec = isinstance(old_active_embedding, list) and bool(old_active_embedding)
                        has_new_vec = any(
                            isinstance(r.get("answer_embedding"), list) and r.get("answer_embedding")
                            for r in inserted_answer_records
                        )
                        can_use_embeddings = (not is_picklist_question) and has_old_vec and has_new_vec
                        logger.bind(
                            opportunity_id=opportunity_id,
                            question_id=question_id,
                        ).debug(
                            "Conflict inputs | old_active_answer_id={} has_old_vec={} has_new_vec={} can_use_embeddings={}",
                            old_active_answer_id,
                            has_old_vec,
                            has_new_vec,
                            can_use_embeddings,
                        )

                        if can_use_embeddings:
                            sims: list[float] = []
                            for rec in inserted_answer_records:
                                vec = rec.get("answer_embedding")
                                if not isinstance(vec, list) or not vec:
                                    continue
                                sims.append(_cosine_similarity(old_active_embedding, vec))
                            min_sim = min(sims) if sims else 0.0
                            is_conflict = min_sim < ANSWER_CONFLICT_EMBEDDING_THRESHOLD
                            logger.bind(
                                opportunity_id=opportunity_id,
                                question_id=question_id,
                                is_picklist=is_picklist_question,
                                min_similarity=round(min_sim, 4),
                                threshold=ANSWER_CONFLICT_EMBEDDING_THRESHOLD,
                            ).info("Conflict check (embedding)")
                            logger.bind(
                                opportunity_id=opportunity_id,
                                question_id=question_id,
                            ).debug(
                                "Embedding conflict decision | min_similarity={} threshold={} is_conflict={}",
                                round(min_sim, 6),
                                ANSWER_CONFLICT_EMBEDDING_THRESHOLD,
                                is_conflict,
                            )
                        else:
                            # Debug why we didn't use embeddings.
                            if is_picklist_question:
                                reason = "picklist_question"
                            elif not has_old_vec:
                                reason = "missing_old_embedding"
                            elif not has_new_vec:
                                reason = "missing_new_embedding"
                            else:
                                reason = "unknown"
                            is_conflict = any(v != old_active_norm for v in inserted_norm_values)
                            logger.bind(
                                opportunity_id=opportunity_id,
                                question_id=question_id,
                                is_picklist=is_picklist_question,
                                answer_type=(answer_type or None),
                                has_picklist_options=has_picklist_options,
                                fallback_reason=reason,
                            ).info("Conflict check (text)")
                            logger.bind(
                                opportunity_id=opportunity_id,
                                question_id=question_id,
                            ).debug(
                                "Text conflict decision | reason={} old_active_norm={} inserted_norm_values_count={} is_conflict={}",
                                reason,
                                old_active_norm,
                                len(inserted_norm_values),
                                is_conflict,
                            )

                        if is_conflict:
                            should_create_conflict = True
                            conflict_answer_ids = [old_active_answer_id, *inserted_answer_ids]

                            # Demote old active -> pending, keep it in active candidate pool.
                            self._execute_step(
                                cur,
                                """
                                UPDATE answers
                                SET status = 'pending',
                                    is_active = true,
                                    has_conflicts = true,
                                    needs_review = true,
                                    conflict_count = %s,
                                    updated_at = %s
                                WHERE opportunity_id = %s
                                  AND question_id = %s
                                  AND answer_id = %s
                                """,
                                (
                                    len(conflict_answer_ids),
                                    now,
                                    opportunity_id,
                                    question_id,
                                    old_active_answer_id,
                                ),
                                "mark_old_active_as_pending_on_conflict",
                                {
                                    "opportunity_id": opportunity_id,
                                    "question_id": question_id,
                                    "answer_id": old_active_answer_id,
                                },
                            )
                        else:
                            # Case B: values unchanged => archive prior active row.
                            self._execute_step(
                                cur,
                                """
                                UPDATE answers
                                SET status = 'inactive',
                                    is_active = false,
                                    has_conflicts = false,
                                    needs_review = false,
                                    conflict_count = 0,
                                    updated_at = %s
                                WHERE opportunity_id = %s
                                  AND question_id = %s
                                  AND answer_id = %s
                                """,
                                (now, opportunity_id, question_id, old_active_answer_id),
                                "archive_old_active_on_same_value_rerun",
                                {
                                    "opportunity_id": opportunity_id,
                                    "question_id": question_id,
                                    "answer_id": old_active_answer_id,
                                },
                            )
                    else:
                        # First run / no prior active row: conflict only when new candidates disagree.
                        if len(inserted_norm_values) > 1 and len(inserted_answer_ids) > 1:
                            should_create_conflict = True
                            conflict_answer_ids = list(inserted_answer_ids)

                    if should_create_conflict:
                        self._execute_step(
                            cur,
                            """
                            UPDATE answers
                            SET status = 'pending',
                                is_active = true,
                                has_conflicts = true,
                                needs_review = true,
                                conflict_count = %s,
                                updated_at = %s
                            WHERE opportunity_id = %s
                              AND question_id = %s
                              AND answer_id = ANY(%s::text[])
                            """,
                            (
                                len(conflict_answer_ids),
                                now,
                                opportunity_id,
                                question_id,
                                conflict_answer_ids,
                            ),
                            "mark_conflict_participants_pending_active",
                            {
                                "opportunity_id": opportunity_id,
                                "question_id": question_id,
                                "participant_count": len(conflict_answer_ids),
                            },
                        )

                        conflict_id = str(uuid.uuid4())
                        for answer_id in conflict_answer_ids:
                            self._execute_step(
                                cur,
                                """
                                SELECT answer_text
                                FROM answers
                                WHERE opportunity_id = %s
                                  AND question_id = %s
                                  AND answer_id = %s
                                LIMIT 1
                                """,
                                (opportunity_id, question_id, answer_id),
                                "select_conflicting_value",
                                {
                                    "opportunity_id": opportunity_id,
                                    "question_id": question_id,
                                    "answer_id": answer_id,
                                },
                            )
                            row = cur.fetchone()
                            conflicting_value = row[0] if row and row[0] is not None else ""

                            self._execute_step(
                                cur,
                                """
                                INSERT INTO conflicts (
                                    conflict_id, answer_id, opportunity_id, question_id,
                                    conflicting_value, status, created_at
                                )
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (opportunity_id, answer_id, conflict_id) DO NOTHING
                                """,
                                (
                                    conflict_id,
                                    answer_id,
                                    opportunity_id,
                                    question_id,
                                    conflicting_value,
                                    "pending",
                                    now,
                                ),
                                "insert_conflict",
                                {
                                    "opportunity_id": opportunity_id,
                                    "question_id": question_id,
                                    "answer_id": answer_id,
                                    "conflict_id": conflict_id,
                                },
                            )
                            conflicts_inserted += 1
                    else:
                        # No conflict: new rows remain pending but are not "active candidates".
                        self._execute_step(
                            cur,
                            """
                            UPDATE answers
                            SET status = 'pending',
                                is_active = false,
                                has_conflicts = false,
                                needs_review = false,
                                conflict_count = 0,
                                updated_at = %s
                            WHERE opportunity_id = %s
                              AND question_id = %s
                              AND answer_id = ANY(%s::text[])
                            """,
                            (now, opportunity_id, question_id, inserted_answer_ids),
                            "mark_new_rows_pending_no_conflict",
                            {
                                "opportunity_id": opportunity_id,
                                "question_id": question_id,
                                "inserted_count": len(inserted_answer_ids),
                            },
                        )

                # New generation row(s) use ``next_version``; older rows for this question
                # (e.g. v98 when this run is v99) must not look "current". Inactivate any
                # prior-version rows except this run's inserts and conflict participants.
                if insert_new_answer_row:
                    exclude_ids: set[str] = set(inserted_answer_ids)
                    if should_create_conflict and conflict_answer_ids:
                        exclude_ids.update(str(x) for x in conflict_answer_ids if x)
                    if keep_old_active_pending_due_to_empty_generation and old_active_answer_id:
                        exclude_ids.add(str(old_active_answer_id))
                    exclude_list = sorted(exclude_ids)
                    self._execute_step(
                        cur,
                        """
                        UPDATE answers
                        SET
                            status = 'inactive',
                            is_active = false,
                            needs_review = false,
                            has_conflicts = false,
                            conflict_count = 0,
                            updated_at = %s
                        WHERE opportunity_id = %s
                          AND question_id = %s
                          AND current_version < %s
                          AND NOT (answer_id = ANY(%s::text[]))
                        """,
                        (now, opportunity_id, question_id, next_version, exclude_list),
                        "supersede_prior_answer_versions_for_new_generation",
                        {
                            "opportunity_id": opportunity_id,
                            "question_id": question_id,
                            "new_version": next_version,
                            "excluded_answer_ids": exclude_list,
                        },
                    )
                    logger.info(
                        "Superseded prior-version answers for new generation | opportunity_id={} question_id={} new_version={} excluded_answer_id_count={}",
                        opportunity_id,
                        question_id,
                        next_version,
                        len(exclude_list),
                    )

            con.commit()
            logger.info(
                "save_rag_answers committed | opportunity_id={} question_id={} answers_inserted={} citations_inserted={} conflicts_inserted={}",
                opportunity_id,
                question_id,
                len(inserted_answer_records),
                total_citations_inserted,
                conflicts_inserted,
            )

        except Exception:
            con.rollback()
            logger.exception(
                "save_rag_answers rolled back | opportunity_id={} question_id={} answers_requested={}",
                opportunity_id,
                question_id,
                len(answers_list),
            )
            raise
        finally:
            con.close()

    def resolve_conflict(
        self, question_id: str, conflict_id: str, selected_answer_id: str
    ) -> None:
        """
        User Resolution Step:
        - 6. scoped final mapping: UPSERT final_answer_id
        - 7. conflicts: UPDATE status = resolved
        """
        now = datetime.now(UTC)
        con = get_db_connection()
        try:
            cur = con.cursor()

            # Derive the real (opportunity_id, question_id) from the conflicts row
            # using the selected answer. This avoids FE payload mismatches.
            cur.execute(
                """
                SELECT opportunity_id, question_id
                FROM conflicts
                WHERE conflict_id = %s
                  AND answer_id = %s
                LIMIT 1
                """,
                (conflict_id, selected_answer_id),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError(
                    f"resolve_conflict: no conflicts row found for conflict_id={conflict_id} selected_answer_id={selected_answer_id}"
                )
            opportunity_id, effective_question_id = row[0], row[1]

            # 6. Update scoped final answer mapping (deprecated: do not use
            #    sase_questions.final_answer_id).
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

            # 7. Update conflicts group
            cur.execute(
                """
                UPDATE conflicts
                SET status = 'resolved',
                    resolved_by = %s,
                    resolved_at = %s
                WHERE conflict_id = %s
            """,
                (selected_answer_id, now, conflict_id),
            )

            # 8. Update answers lifecycle:
            #    - set is_active=false for both selected + non-selected answers
            #    - mark the selected one as the confirmed winner (status='active'),
            #      others as inactive (status='inactive')
            cur.execute(
                """
                UPDATE answers
                SET
                    is_active = false,
                    status = CASE
                        WHEN answer_id = %s THEN 'active'
                        ELSE 'inactive'
                    END,
                    has_conflicts = false,
                    needs_review = false,
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
                    now,
                    opportunity_id,
                    effective_question_id,
                    conflict_id,
                    opportunity_id,
                    effective_question_id,
                ),
            )

            con.commit()
            logger.info(
                "Conflict %s resolved for question %s with answer %s",
                conflict_id,
                effective_question_id,
                selected_answer_id,
            )

        except Exception:
            con.rollback()
            logger.exception("Failed to resolve conflict")
            raise
        finally:
            con.close()

    def add_new_answer_after_resolution(
        self, opportunity_id: str, question_id: str, new_answer: dict[str, Any]
    ) -> None:
        """
        8. Special Case: New Answer After Resolution
        - Step 1: Insert new answer -> answers, versions, citations
        - Step 2: Create NEW conflict group for ALL active answers
        (Scoped final-answer mapping is left unchanged — user selections are not cleared.)
        """
        now = datetime.now(UTC)
        con = get_db_connection()
        try:
            cur = con.cursor()

            # Step 1: Insert new answer
            answer_id = str(uuid.uuid4())
            answer_text = new_answer.get("answer_text", "")
            confidence_score = new_answer.get("confidence_score", 0.0)
            reasoning = new_answer.get("reasoning", "")
            citations = new_answer.get("citations", [])

            answer_embedding = None
            try:
                vecs = embed_texts([str(answer_text or "")])
                answer_embedding = vecs[0] if vecs else None
            except Exception:
                logger.exception(
                    "Non-fatal: failed to embed late answer; continuing without answer_embedding | opportunity_id={} question_id={}",
                    opportunity_id,
                    question_id,
                )

            cur.execute(
                """
                INSERT INTO answers (
                    answer_id, opportunity_id, question_id, answer_text,
                    confidence_score, reasoning, source_count, status,
                    current_version, needs_review, has_conflicts, is_active, is_user_override,
                    created_at, updated_at,
                    answer_embedding
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', 1, false, false, true, false, %s, %s, %s)
            """,
                (
                    answer_id,
                    opportunity_id,
                    question_id,
                    answer_text,
                    confidence_score,
                    reasoning,
                    len(citations),
                    now,
                    now,
                    _pgvector_param(answer_embedding),
                ),
            )

            version_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO answer_versions (
                    version_id, answer_id, opportunity_id, question_id,
                    version, answer_text, confidence_score, change_type, changed_by, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    version_id,
                    answer_id,
                    opportunity_id,
                    question_id,
                    1,
                    answer_text,
                    confidence_score,
                    "INITIAL",
                    "ai",
                    now,
                ),
            )

            for cit in citations:
                citation_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO citations (
                        citation_id,
                        answer_id,
                        conflict_id,
                        opportunity_id,
                        question_id,
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
                        created_at,
                        version_id
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                """,
                    (
                        citation_id,
                        answer_id,
                        cit.get("conflict_id"),
                        opportunity_id,
                        question_id,
                        _normalize_citation_source_type(cit.get("source_type")),
                        cit.get("source_file"),
                        cit.get("source_name"),
                        cit.get("document_date"),
                        cit.get("chunk_id"),
                        cit.get("quote"),
                        cit.get("context"),
                        cit.get("page_number"),
                        cit.get("timestamp") or cit.get("timestamp_str"),
                        cit.get("speaker"),
                        cit.get("relevance_score"),
                        bool(cit.get("is_primary"))
                        if cit.get("is_primary") is not None
                        else False,
                        now,
                        version_id,
                    ),
                )

            # Step 2: Create NEW conflict group
            cur.execute(
                """
                SELECT answer_id FROM answers
                WHERE opportunity_id = %s AND question_id = %s AND is_active = true
            """,
                (opportunity_id, question_id),
            )
            active_answer_rows = cur.fetchall()

            if len(active_answer_rows) > 1:
                conflict_id = str(uuid.uuid4())
                for row in active_answer_rows:
                    active_ans_id = row[0]
                    cur.execute(
                        "SELECT answer_text FROM answers WHERE answer_id = %s AND opportunity_id = %s",
                        (active_ans_id, opportunity_id),
                    )
                    ans_text_row = cur.fetchone()
                    conflicting_value = ans_text_row[0] if ans_text_row else ""

                    cur.execute(
                        """
                        INSERT INTO conflicts (
                            conflict_id, answer_id, opportunity_id, question_id,
                            conflicting_value, status, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (opportunity_id, answer_id, conflict_id) DO NOTHING
                    """,
                        (
                            conflict_id,
                            active_ans_id,
                            opportunity_id,
                            question_id,
                            conflicting_value,
                            "pending",
                            now,
                        ),
                    )

            con.commit()
            logger.info(
                "Ingested late answer %s for %s. Conflict group reset.",
                answer_id,
                question_id,
            )

        except Exception:
            con.rollback()
            logger.exception("Failed to add late answer and reset conflicts")
            raise
        finally:
            con.close()

    def save_feedback(
        self,
        *,
        feedback_id: str,
        answer_id: str,
        opportunity_id: str,
        question_id: str,
        feedback_type: Any,
        comments: str | None = None,
        submitted_by: str = "user",
    ) -> None:
        """Persist a single feedback row to the ``feedback`` table.

        Only the fields sent by the FE are stored; all other columns default
        to their DB-defined defaults (NULL / 'pending' / NOW()).

        ``feedback_type`` is normalized to satisfy ``chk_feedback_type`` (rating /
        correction / comment). Legacy numeric codes (e.g. ``\"4\"``) map to ``rating``.
        """
        # Derive the current answer_version from answer_versions table.
        con = get_db_connection()
        try:
            cur = con.cursor()

            # Look up the latest version number for this answer so we can
            # record which version the feedback refers to.
            cur.execute(
                """
                SELECT COALESCE(MAX(version), 1)
                FROM answer_versions
                WHERE opportunity_id = %s AND answer_id = %s
                """,
                (opportunity_id, answer_id),
            )
            row = cur.fetchone()
            answer_version = row[0] if row else 1

            fb_type = _normalize_feedback_type_for_db(feedback_type)

            self._execute_step(
                cur,
                """
                INSERT INTO feedback (
                    feedback_id,
                    answer_id,
                    opportunity_id,
                    question_id,
                    answer_version,
                    feedback_type,
                    comments
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (opportunity_id, answer_id, feedback_id) DO NOTHING
                """,
                (
                    feedback_id,
                    answer_id,
                    opportunity_id,
                    question_id,
                    answer_version,
                    fb_type,
                    comments,
                ),
                "insert_feedback",
                {
                    "feedback_id": feedback_id,
                    "answer_id": answer_id,
                    "opportunity_id": opportunity_id,
                    "question_id": question_id,
                },
            )
            con.commit()
            logger.info(
                "Feedback saved | feedback_id={} answer_id={} opportunity_id={} question_id={}",
                feedback_id,
                answer_id,
                opportunity_id,
                question_id,
            )
        except Exception:
            con.rollback()
            logger.exception(
                "Failed to save feedback | feedback_id={} answer_id={}",
                feedback_id,
                answer_id,
            )
            raise
        finally:
            con.close()

    def save_feedback_batch(
        self,
        feedback_rows: list[dict[str, Any]],
        *,
        cur: Any | None = None,
        con: Any | None = None,
        do_commit: bool = True,
    ) -> None:
        """Persist many feedback rows efficiently.

        Optimized for the `/opportunities/{id}/answers` endpoint:
        - Can reuse an existing connection/cursor to avoid reconnect cost.
        - Avoids per-row version lookups by joining `answers.current_version`.

        Expects each row dict to contain:
        - feedback_id, answer_id, opportunity_id, question_id, feedback_type, comments (optional)
        """
        if not feedback_rows:
            return

        owns_conn = con is None or cur is None
        if owns_conn:
            con = get_db_connection()
            cur = con.cursor()

        try:
            # One INSERT .. SELECT with a join to answers to derive answer_version quickly.
            values_placeholders = ",".join(["(%s,%s,%s,%s,%s,%s)"] * len(feedback_rows))
            params: list[Any] = []
            for r in feedback_rows:
                params.extend(
                    [
                        str(r.get("feedback_id")),
                        str(r.get("answer_id")),
                        str(r.get("opportunity_id")),
                        str(r.get("question_id")),
                        _normalize_feedback_type_for_db(r.get("feedback_type")),
                        (str(r.get("comments")).strip() if r.get("comments") is not None else None),
                    ]
                )

            cur.execute(
                f"""
                INSERT INTO feedback (
                    feedback_id,
                    answer_id,
                    opportunity_id,
                    question_id,
                    answer_version,
                    feedback_type,
                    comments
                )
                SELECT
                    v.feedback_id,
                    v.answer_id,
                    v.opportunity_id,
                    v.question_id,
                    COALESCE(a.current_version, 1) AS answer_version,
                    v.feedback_type::integer,
                    v.comments
                FROM (VALUES {values_placeholders}) AS v(
                    feedback_id,
                    answer_id,
                    opportunity_id,
                    question_id,
                    feedback_type,
                    comments
                )
                JOIN answers a
                  ON a.opportunity_id = v.opportunity_id
                 AND a.answer_id = v.answer_id
                ON CONFLICT (opportunity_id, answer_id, feedback_id) DO NOTHING
                """,
                tuple(params),
            )
            if do_commit:
                con.commit()
            logger.info("Feedback batch saved | count={}", len(feedback_rows))
        except Exception:
            if con is not None:
                con.rollback()
            logger.exception("Failed to save feedback batch | count={}", len(feedback_rows))
            raise
        finally:
            if owns_conn and con is not None:
                con.close()
