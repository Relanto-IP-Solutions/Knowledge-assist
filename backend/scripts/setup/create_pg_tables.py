"""DEPRECATED: do not use this script for schema creation.

Schema ownership moved to modular SQL files under db/schema/modules.
Use instead:
    uv run python scripts/db/apply_modular_schema.py

This file is intentionally kept temporarily to avoid accidental breakage in
external references, but execution is blocked to prevent schema drift.
"""

from __future__ import annotations

import sys


def main() -> None:
    print(
        "ERROR: scripts/setup/create_pg_tables.py is deprecated and disabled.\n"
        "Use: uv run python scripts/db/apply_modular_schema.py",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()

"""
Create the Knowledge-Assist opportunity data-model tables in Cloud SQL (PostgreSQL).

Usage
-----
    # Via Cloud SQL connector (recommended — uses IAM auth or password):
    uv run python -m scripts.create_pg_tables

    # Skip existing tables, just show current state:
    uv run python -m scripts.create_pg_tables --verify-only

    # Drop and recreate everything (destructive — prompts for confirmation):
    uv run python -m scripts.create_pg_tables --drop-existing

Connection modes
----------------
The script picks the connection method automatically:

1. **Cloud SQL Python Connector** (preferred)
   Set CLOUDSQL_INSTANCE_CONNECTION_NAME=project:region:instance.
   Set CLOUDSQL_USE_IAM_AUTH=true for Workload Identity / IAM auth.
   Set CLOUDSQL_USE_IAM_AUTH=false and PG_PASSWORD=<pw> for password auth.

2. **Direct TCP / Cloud SQL Auth Proxy**
   Leave CLOUDSQL_INSTANCE_CONNECTION_NAME empty and set PG_HOST.

Required env vars (copy configs/.env.example to configs/.env and fill in):
    CLOUDSQL_INSTANCE_CONNECTION_NAME   project:region:instance (or leave empty)
    CLOUDSQL_USE_IAM_AUTH               true | false
    PG_HOST                             host/IP (only when NOT using connector)
    PG_PORT                             5432
    PG_DATABASE                         pzf_dor
    PG_USER                             e.g. pzf-service-account@project.iam
    PG_PASSWORD                         password (empty if using IAM auth)
    GOOGLE_APPLICATION_CREDENTIALS      path to service-account JSON key
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.services.database_manager.answers_legacy_unique import (
    drop_legacy_unique_one_row_per_question_on_answers,
)


# ---------------------------------------------------------------------------
# Bootstrap: load all .env files into os.environ before anything else.
# pydantic-settings only maps known fields; load_dotenv populates os.environ
# so that ad-hoc vars like CLOUDSQL_INSTANCE_CONNECTION_NAME are readable.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_ENV_FILES = [
    _PROJECT_ROOT / "configs" / ".env",
    _PROJECT_ROOT / "configs" / "secrets" / ".env",
]
for _ef in _ENV_FILES:
    if _ef.exists():
        load_dotenv(_ef, override=False)  # override=False: real env vars win

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL — type mapping from Spanner → PostgreSQL
#
#   STRING(n)        → VARCHAR(n)
#   STRING(MAX)      → TEXT
#   INT64            → BIGINT
#   FLOAT64          → DOUBLE PRECISION
#   BOOL             → BOOLEAN
#   DATE             → DATE
#   TIMESTAMP (COMMIT_TIMESTAMP default) → TIMESTAMPTZ DEFAULT NOW()
#   TIMESTAMP (no default)               → TIMESTAMPTZ
#   JSON             → JSONB
#
# Interleaved tables become regular tables with FK constraints.
# ---------------------------------------------------------------------------

DDL_STATEMENTS: list[tuple[str, str]] = [
    # ------------------------------------------------------------------
    # 0. extensions
    # ------------------------------------------------------------------
    (
        "_extensions",
        """
CREATE EXTENSION IF NOT EXISTS vector;
""",
    ),
    # ------------------------------------------------------------------
    # 1. opportunities
    # ------------------------------------------------------------------
    (
        "opportunities",
        """
CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_id          VARCHAR(64)        NOT NULL,
    opportunity_name        VARCHAR(512),
    account_name            VARCHAR(512),
    owner_id                VARCHAR(64),
    owner_name              VARCHAR(256),
    status                  VARCHAR(32)        NOT NULL DEFAULT 'Discovery',
    processing_status       VARCHAR(32)                 DEFAULT 'idle',
    total_documents         BIGINT                      DEFAULT 0,
    processed_documents     BIGINT                      DEFAULT 0,
    total_chunks            BIGINT                      DEFAULT 0,
    total_questions         BIGINT                      DEFAULT 0,
    answered_questions      BIGINT                      DEFAULT 0,
    high_confidence         BIGINT                      DEFAULT 0,
    medium_confidence       BIGINT                      DEFAULT 0,
    low_confidence          BIGINT                      DEFAULT 0,
    unanswered              BIGINT                      DEFAULT 0,
    with_conflicts          BIGINT                      DEFAULT 0,
    needs_review            BIGINT                      DEFAULT 0,
    user_overridden         BIGINT                      DEFAULT 0,
    completeness_pct        DOUBLE PRECISION            DEFAULT 0.0,
    last_doc_uploaded_at    TIMESTAMPTZ,
    last_doc_processed_at   TIMESTAMPTZ,
    last_extraction_at      TIMESTAMPTZ,
    last_answer_updated_at  TIMESTAMPTZ,
    last_user_activity_at   TIMESTAMPTZ,
    created_at              TIMESTAMPTZ        NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ        NOT NULL DEFAULT NOW(),
    extraction_version      BIGINT                      DEFAULT 0,
    metadata                JSONB,

    CONSTRAINT pk_opportunities PRIMARY KEY (opportunity_id),
    CONSTRAINT chk_opportunities_status
        CHECK (status IN ('Discovery', 'In-Progress', 'Completed')),
    CONSTRAINT chk_opportunities_processing_status
        CHECK (processing_status IN ('idle', 'processing', 'completed', 'error'))
)
""",
    ),
    # ------------------------------------------------------------------
    # 2. questions
    # ------------------------------------------------------------------
    (
        "questions",
        """
CREATE TABLE IF NOT EXISTS questions (
    question_id             VARCHAR(64)        NOT NULL,
    section                 VARCHAR(256)       NOT NULL,
    sub_section_1           VARCHAR(256),
    sub_section_2           VARCHAR(256),
    sub_section_3           VARCHAR(256),
    sub_section_4           VARCHAR(256),
    question_text           TEXT               NOT NULL,
    is_required             BOOLEAN            NOT NULL DEFAULT FALSE,
    data_type               VARCHAR(64)        NOT NULL,
    picklist_options        JSONB,
    customer_artifacts      VARCHAR(512),
    applicable_existing     BOOLEAN                     DEFAULT TRUE,
    applicable_new          BOOLEAN                     DEFAULT TRUE,
    who_can_help            VARCHAR(256),
    depends_on_question     VARCHAR(64),
    depends_on_condition    VARCHAR(256),
    default_value           TEXT,
    default_condition       VARCHAR(512),
    display_order           BIGINT,
    help_text               TEXT,
    is_active               BOOLEAN            NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ        NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ        NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_questions PRIMARY KEY (question_id),
    CONSTRAINT chk_questions_data_type
        CHECK (data_type IN (
            'text_area', 'text_area_long', 'number', 'date',
            'boolean', 'picklist', 'multi_select'
        ))
)
""",
    ),
    # ------------------------------------------------------------------
    # 3. answers  (child of opportunities)
    # ------------------------------------------------------------------
    (
        "answers",
        """
CREATE TABLE IF NOT EXISTS answers (
    answer_id               VARCHAR(256)       NOT NULL,
    opportunity_id          VARCHAR(64)        NOT NULL,
    question_id             VARCHAR(64)        NOT NULL,
    answer_text             TEXT,
    answer_number           DOUBLE PRECISION,
    answer_date             DATE,
    answer_boolean          BOOLEAN,
    answer_picklist         VARCHAR(512),
    answer_multi            JSONB,
    answer_display          TEXT,
    confidence_score        DOUBLE PRECISION            DEFAULT 0.0,
    status                  VARCHAR(32)        NOT NULL DEFAULT 'inactive',
    needs_review            BOOLEAN            NOT NULL DEFAULT FALSE,
    has_conflicts           BOOLEAN            NOT NULL DEFAULT FALSE,
    conflict_count          BIGINT                      DEFAULT 0,
    source_count            BIGINT                      DEFAULT 0,
    primary_source          VARCHAR(512),
    reasoning               TEXT,
    is_active               BOOLEAN            NOT NULL DEFAULT FALSE,
    current_version         BIGINT             NOT NULL DEFAULT 1,
    extraction_version      BIGINT,
    is_user_override        BOOLEAN            NOT NULL DEFAULT FALSE,
    overridden_by           VARCHAR(64),
    overridden_at           TIMESTAMPTZ,
    override_reason         TEXT,
    created_at              TIMESTAMPTZ        NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ        NOT NULL DEFAULT NOW(),
    confidence              DOUBLE PRECISION            DEFAULT 0.0,
    answer_embedding        vector(768),

    CONSTRAINT pk_answers PRIMARY KEY (opportunity_id, answer_id),
    CONSTRAINT fk_answers_opportunity
        FOREIGN KEY (opportunity_id) REFERENCES opportunities (opportunity_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_answers_question
        FOREIGN KEY (question_id) REFERENCES questions (question_id),
    CONSTRAINT chk_answers_status
        CHECK (status IN ('pending', 'active', 'inactive')),
    CONSTRAINT chk_answers_confidence
        CHECK (confidence_score IS NULL OR (confidence_score >= 0.0 AND confidence_score <= 1.0))
)
""",
    ),
    # ------------------------------------------------------------------
    # 4. answer_versions  (child of answers)
    # ------------------------------------------------------------------
    (
        "answer_versions",
        """
CREATE TABLE IF NOT EXISTS answer_versions (
    version_id              VARCHAR(320)       NOT NULL,
    answer_id               VARCHAR(256)       NOT NULL,
    opportunity_id          VARCHAR(64)        NOT NULL,
    question_id             VARCHAR(64)        NOT NULL,
    version                 BIGINT             NOT NULL,
    answer_text             TEXT,
    answer_number           DOUBLE PRECISION,
    answer_date             DATE,
    answer_boolean          BOOLEAN,
    answer_picklist         VARCHAR(512),
    answer_multi            JSONB,
    answer_display          TEXT,
    confidence_score        DOUBLE PRECISION,
    reasoning               TEXT,
    change_type             VARCHAR(32)        NOT NULL,
    change_reason           TEXT,
    changed_by              VARCHAR(64)        NOT NULL,
    previous_value          TEXT,
    created_at              TIMESTAMPTZ        NOT NULL DEFAULT NOW(),
    confidence              DOUBLE PRECISION,
    created_by              VARCHAR(64),
    created_by_type         VARCHAR(16)                 DEFAULT 'ai',

    CONSTRAINT pk_answer_versions PRIMARY KEY (opportunity_id, answer_id, version),
    CONSTRAINT fk_answer_versions_answer
        FOREIGN KEY (opportunity_id, answer_id)
        REFERENCES answers (opportunity_id, answer_id)
        ON DELETE CASCADE,
    CONSTRAINT chk_answer_versions_change_type
        CHECK (change_type IN (
            'initial', 'extraction', 'user_override', 'conflict_resolution'
        )),
    CONSTRAINT chk_answer_versions_created_by_type
        CHECK (created_by_type IN ('ai', 'user'))
)
""",
    ),
    # ------------------------------------------------------------------
    # 5. citations  (child of answers)
    # ------------------------------------------------------------------
    (
        "citations",
        """
CREATE TABLE IF NOT EXISTS citations (
    citation_id             VARCHAR(64)        NOT NULL,
    answer_id               VARCHAR(256)       NOT NULL,
    conflict_id             VARCHAR(64),
    opportunity_id          VARCHAR(64)        NOT NULL,
    question_id             VARCHAR(64)        NOT NULL,
    source_type             VARCHAR(32)        NOT NULL,
    source_file             VARCHAR(1024),
    source_name             VARCHAR(512),
    document_date           DATE,
    chunk_id                VARCHAR(128),
    quote                   TEXT,
    context                 TEXT,
    page_number             BIGINT,
    timestamp_str           VARCHAR(64),
    speaker                 VARCHAR(256),
    relevance_score         DOUBLE PRECISION            DEFAULT 0.0,
    is_primary              BOOLEAN                     DEFAULT FALSE,
    created_at              TIMESTAMPTZ        NOT NULL DEFAULT NOW(),
    version_id              VARCHAR(320),

    CONSTRAINT pk_citations PRIMARY KEY (opportunity_id, answer_id, citation_id),
    CONSTRAINT fk_citations_answer
        FOREIGN KEY (opportunity_id, answer_id)
        REFERENCES answers (opportunity_id, answer_id)
        ON DELETE CASCADE,
    CONSTRAINT chk_citations_source_type
        CHECK (source_type IN ('slack', 'zoom', 'pdf', 'docx', 'pptx', 'email'))
)
""",
    ),
    # ------------------------------------------------------------------
    # 6. conflicts  (child of answers)
    # ------------------------------------------------------------------
    (
        "conflicts",
        """
CREATE TABLE IF NOT EXISTS conflicts (
    conflict_id             VARCHAR(64)        NOT NULL,
    answer_id               VARCHAR(256)       NOT NULL,
    opportunity_id          VARCHAR(64)        NOT NULL,
    question_id             VARCHAR(64)        NOT NULL,
    conflicting_value       TEXT               NOT NULL,
    value_display           TEXT,
    confidence_score        DOUBLE PRECISION,
    source_type             VARCHAR(32),
    source_file             VARCHAR(1024),
    source_name             VARCHAR(512),
    reasoning               TEXT,
    status                  VARCHAR(16)        NOT NULL DEFAULT 'pending',
    resolved_by             VARCHAR(64),
    resolved_at             TIMESTAMPTZ,
    resolution_reason       TEXT,
    created_at              TIMESTAMPTZ        NOT NULL DEFAULT NOW(),
    confidence              DOUBLE PRECISION,

    CONSTRAINT pk_conflicts PRIMARY KEY (opportunity_id, answer_id, conflict_id),
    CONSTRAINT fk_conflicts_answer
        FOREIGN KEY (opportunity_id, answer_id)
        REFERENCES answers (opportunity_id, answer_id)
        ON DELETE CASCADE,
    CONSTRAINT chk_conflicts_status
        CHECK (status IN ('pending', 'resolved', 'ignored'))
)
""",
    ),
    # ------------------------------------------------------------------
    # 7. feedback  (child of answers)
    # ------------------------------------------------------------------
    (
        "feedback",
        """
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id             VARCHAR(64)        NOT NULL,
    answer_id               VARCHAR(256)       NOT NULL,
    opportunity_id          VARCHAR(64)        NOT NULL,
    question_id             VARCHAR(64)        NOT NULL,
    answer_version          BIGINT             NOT NULL,
    feedback_type           VARCHAR(32)        NOT NULL,
    is_correct              BOOLEAN,
    accuracy_rating         BIGINT,
    relevance_rating        BIGINT,
    citation_quality        BIGINT,
    original_value          TEXT,
    corrected_value         TEXT,
    correction_reason       TEXT,
    issues                  JSONB,
    comments                TEXT,
    suggested_source        TEXT,
    submitted_by            VARCHAR(64)        NOT NULL,
    submitted_by_name       VARCHAR(256),
    submitted_by_role       VARCHAR(128),
    status                  VARCHAR(32)        NOT NULL DEFAULT 'pending',
    reviewed_by             VARCHAR(64),
    reviewed_at             TIMESTAMPTZ,
    review_notes            TEXT,
    created_at              TIMESTAMPTZ        NOT NULL DEFAULT NOW(),

    CONSTRAINT pk_feedback PRIMARY KEY (opportunity_id, answer_id, feedback_id),
    CONSTRAINT fk_feedback_answer
        FOREIGN KEY (opportunity_id, answer_id)
        REFERENCES answers (opportunity_id, answer_id)
        ON DELETE CASCADE,
    CONSTRAINT chk_feedback_type
        CHECK (feedback_type IN ('rating', 'correction', 'comment')),
    CONSTRAINT chk_feedback_status
        CHECK (status IN ('pending', 'reviewed', 'actioned', 'dismissed'))
)
""",
    ),
]

# Indexes created after all tables exist (so FK targets are already there)
INDEX_STATEMENTS: list[tuple[str, str]] = [
    (
        "idx_opportunities_status",
        "CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities (status)",
    ),
    (
        "idx_opportunities_created_at_id",
        "CREATE INDEX IF NOT EXISTS idx_opportunities_created_at_id "
        "ON opportunities (created_at DESC, opportunity_id ASC)",
    ),
    (
        "idx_opportunities_updated",
        "CREATE INDEX IF NOT EXISTS idx_opportunities_updated "
        "ON opportunities (updated_at DESC)",
    ),
    (
        "idx_questions_active",
        "CREATE INDEX IF NOT EXISTS idx_questions_active ON questions (is_active)",
    ),
    (
        "idx_questions_section",
        "CREATE INDEX IF NOT EXISTS idx_questions_section ON questions (section)",
    ),
    (
        "idx_answers_opportunity",
        "CREATE INDEX IF NOT EXISTS idx_answers_opportunity "
        "ON answers (opportunity_id)",
    ),
    (
        "idx_answers_opp_active_override",
        "CREATE INDEX IF NOT EXISTS idx_answers_opp_active_override "
        "ON answers (opportunity_id, is_user_override) "
        "WHERE status = 'active'",
    ),
    (
        "idx_answers_question",
        "CREATE INDEX IF NOT EXISTS idx_answers_question ON answers (question_id)",
    ),
    (
        "idx_versions_answer",
        "CREATE INDEX IF NOT EXISTS idx_versions_answer "
        "ON answer_versions (opportunity_id, answer_id)",
    ),
    (
        "idx_versions_created",
        "CREATE INDEX IF NOT EXISTS idx_versions_created "
        "ON answer_versions (opportunity_id, answer_id, created_at DESC)",
    ),
    (
        "idx_citations_conflict",
        "CREATE INDEX IF NOT EXISTS idx_citations_conflict "
        "ON citations (conflict_id) WHERE conflict_id IS NOT NULL",
    ),
    (
        "idx_citations_primary",
        "CREATE INDEX IF NOT EXISTS idx_citations_primary "
        "ON citations (opportunity_id, answer_id, is_primary) "
        "WHERE is_primary IS NOT NULL",
    ),
    (
        "idx_conflicts_status",
        "CREATE INDEX IF NOT EXISTS idx_conflicts_status "
        "ON conflicts (opportunity_id, status)",
    ),
    (
        "idx_feedback_status",
        "CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback (status)",
    ),
    (
        "idx_feedback_user",
        "CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback (submitted_by)",
    ),
]

DROP_ORDER = [
    "feedback",
    "conflicts",
    "citations",
    "answer_versions",
    "answers",
    "questions",
    "opportunities",
]


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def _env(key: str, default: str = "") -> str:
    """Read an env var that was loaded from the project .env files."""
    return os.environ.get(key, default).strip()


# ---------------------------------------------------------------------------
# Table management
# ---------------------------------------------------------------------------


def _cursor(conn):
    """Return a plain cursor — pg8000 cursor does not support the context manager protocol."""
    return conn.cursor()


def drop_all_tables(conn) -> None:
    """Drop all tables in child-first order (CASCADE)."""
    cur = _cursor(conn)
    try:
        for table in DROP_ORDER:
            logger.warning("Dropping table: %s", table)
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    finally:
        cur.close()
    conn.commit()
    logger.info("All tables dropped.")


def create_all_tables(conn) -> None:
    """Execute all CREATE TABLE IF NOT EXISTS statements."""
    cur = _cursor(conn)
    try:
        for table_name, ddl in DDL_STATEMENTS:
            logger.info("Creating table: %s", table_name)
            cur.execute(ddl)
    finally:
        cur.close()
    conn.commit()
    logger.info("All tables created.")


def create_all_indexes(conn) -> None:
    """Execute all CREATE INDEX IF NOT EXISTS statements."""
    cur = _cursor(conn)
    try:
        for idx_name, ddl in INDEX_STATEMENTS:
            logger.info("Creating index: %s", idx_name)
            cur.execute(ddl)
    finally:
        cur.close()
    conn.commit()
    logger.info("All indexes created.")


def strip_answers_legacy_unique_constraints(conn) -> None:
    """Remove UNIQUE(opportunity_id, question_id) drift on ``public.answers`` (not in our DDL)."""
    cur = _cursor(conn)
    try:
        drop_legacy_unique_one_row_per_question_on_answers(cur)
        conn.commit()
        logger.info(
            "Checked public.answers for legacy UNIQUE(opportunity_id, question_id); "
            "dropped if present (see answers_legacy_unique)."
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def verify_tables(conn) -> None:
    """Print a summary of tables and their row counts."""
    table_names = [t for t, _ in DDL_STATEMENTS]
    cur = _cursor(conn)
    try:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        )
        existing = {row[0] for row in cur.fetchall()}
    finally:
        cur.close()

    print("\n" + "=" * 60)
    print(f"{'Table':<25} {'Exists':>8}  {'Rows':>10}")
    print("-" * 60)
    for table in table_names:
        exists = table in existing
        rows = "-"
        if exists:
            cur2 = _cursor(conn)
            try:
                cur2.execute(f"SELECT COUNT(*) FROM {table}")
                rows = str(cur2.fetchone()[0])
            finally:
                cur2.close()
        status = "YES" if exists else "MISSING"
        print(f"  {table:<23} {status:>8}  {rows:>10}")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create Knowledge-Assist opportunity tables in Cloud SQL (PostgreSQL)."
    )
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="Drop all tables before creating them (destructive).",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only check which tables exist and their row counts.",
    )
    args = parser.parse_args()

    instance_conn_name = _env("CLOUDSQL_INSTANCE_CONNECTION_NAME")
    pg_host = _env("PG_HOST")

    if not instance_conn_name and not pg_host:
        logger.error(
            "No connection target configured.  "
            "Set CLOUDSQL_INSTANCE_CONNECTION_NAME (Cloud SQL connector) "
            "or PG_HOST (direct TCP) in configs/.env"
        )
        sys.exit(1)

    # ------------------------------------------------------------------
    # We need to open the connection slightly differently depending on the
    # backend (pg8000 from connector doesn't have a cursor() on the same
    # interface as psycopg2, so we normalise via psycopg2 for TCP and
    # use pg8000 connection directly for the connector path).
    # Both implement DB-API 2.0 so the same cursor() calls work.
    # ------------------------------------------------------------------
    if instance_conn_name:
        from google.cloud.sql.connector import Connector

        use_iam = _env("CLOUDSQL_USE_IAM_AUTH", "true").lower() == "true"
        db_user = _env("PG_USER")
        db_name = _env("PG_DATABASE", "pzf_dor")
        db_pass = _env("PG_PASSWORD") or None

        connector = Connector()
        try:
            if use_iam:
                conn = connector.connect(
                    instance_conn_name,
                    "pg8000",
                    user=db_user,
                    db=db_name,
                    enable_iam_auth=True,
                )
            else:
                conn = connector.connect(
                    instance_conn_name,
                    "pg8000",
                    user=db_user,
                    password=db_pass,
                    db=db_name,
                )
            logger.info(
                "Connected via Cloud SQL connector: %s (db=%s, user=%s, iam=%s)",
                instance_conn_name,
                db_name,
                db_user,
                use_iam,
            )
        except Exception as exc:
            logger.exception("Connection failed: %s", exc)
            connector.close()
            sys.exit(1)
    else:
        import psycopg2

        host = _env("PG_HOST", "127.0.0.1")
        port = int(_env("PG_PORT", "5432"))
        database = _env("PG_DATABASE", "pzf_dor")
        user = _env("PG_USER")
        password = _env("PG_PASSWORD") or None
        try:
            conn = psycopg2.connect(
                host=host,
                port=port,
                dbname=database,
                user=user,
                password=password,
                # Cloud SQL Auth Proxy handles TLS; plain TCP locally.
                sslmode="disable",
            )
            logger.info(
                "Connected via TCP: %s:%d/%s (user=%s)", host, port, database, user
            )
        except Exception as exc:
            logger.exception("Connection failed: %s", exc)
            sys.exit(1)

    conn.autocommit = False

    try:
        if args.verify_only:
            verify_tables(conn)
            return

        if args.drop_existing:
            answer = (
                input(
                    "\n  WARNING: This will DROP all Knowledge-Assist tables and their data.\n"
                    "  Type 'yes' to confirm: "
                )
                .strip()
                .lower()
            )
            if answer != "yes":
                logger.info("Aborted.")
                return
            drop_all_tables(conn)

        create_all_tables(conn)
        create_all_indexes(conn)
        strip_answers_legacy_unique_constraints(conn)
        verify_tables(conn)
        logger.info("Done. All tables and indexes are ready.")

    except Exception as exc:
        logger.exception("Error during table creation: %s", exc)
        conn.rollback()
        raise
    finally:
        conn.close()
        if instance_conn_name:
            connector.close()  # type: ignore[possibly-undefined]


if __name__ == "__main__":
    main()
