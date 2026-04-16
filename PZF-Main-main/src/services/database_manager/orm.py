"""SQLAlchemy ORM setup and connection management."""

import time

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from configs.settings import get_settings
from src.services.database_manager.connection import get_database_manager
from src.utils.logger import get_logger


Base = declarative_base()

_ENGINE = None
logger = get_logger(__name__)


def get_engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE

    # One physical pool (Cloud SQL queue or psycopg2 ThreadedConnectionPool) in
    # connection.py. SQLAlchemy must not open a second parallel connector + QueuePool
    # or every ORM request pays a fresh Cloud SQL handshake (~seconds) while raw
    # get_db_connection() reuses pre-warmed connections.
    s = get_settings().database

    def creator():
        return get_database_manager().get_db_connection()

    if s.cloudsql_instance_connection_name:
        use_iam = (s.cloudsql_use_iam_auth or "true").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if not use_iam and not (s.pg_password or "").strip():
            raise ValueError(
                "Cloud SQL: CLOUDSQL_USE_IAM_AUTH is disabled but PG_PASSWORD is empty. "
                "Set PG_PASSWORD in configs/secrets/.env, or enable IAM with "
                "CLOUDSQL_USE_IAM_AUTH=true and a Cloud SQL IAM database user."
            )
        if use_iam and not (s.pg_user or "").strip():
            raise ValueError(
                "Cloud SQL IAM auth requires PG_USER (e.g. IAM-enabled database username)."
            )
        _ENGINE = create_engine(
            "postgresql+pg8000://",
            creator=creator,
            poolclass=NullPool,
        )
    else:
        if not (s.pg_host or "").strip():
            raise RuntimeError(
                "DB not configured: set CLOUDSQL_INSTANCE_CONNECTION_NAME or PG_HOST."
            )
        _ENGINE = create_engine(
            "postgresql+psycopg2://",
            creator=creator,
            poolclass=NullPool,
        )

    return _ENGINE


def SessionLocal():
    """Returns a new Session instance from the global engine."""
    engine = get_engine()
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return factory()


def get_db():
    """FastAPI dependency: yields a new session and ensures it is closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def warm_sqlalchemy() -> None:
    """Warm SQLAlchemy dialect initialization on startup.

    Even with a pre-warmed physical connection, SQLAlchemy/pg8000 performs first-use
    initialization (version, settings probes) the first time a Session checks out a
    connection. Doing a tiny SELECT here keeps the first API call fast.
    """
    t0 = time.perf_counter()
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception as exc:
        logger.warning("SQLAlchemy warm-up failed (non-fatal): {}", exc)
        return
    logger.info("sqlalchemy warm-up complete | ms={}", int((time.perf_counter() - t0) * 1000))
