"""PostgreSQL connection management for application tables.

Uses centralized settings (configs/settings.py) instead of dotenv directly.
Supports Cloud SQL connector when CLOUDSQL_INSTANCE_CONNECTION_NAME is set,
else direct TCP to PG_HOST. Connection pooling is used for the psycopg2 (PG_HOST) path.
"""

from __future__ import annotations

import os
import pathlib
import re
import threading
import json
import time
import queue
from contextlib import contextmanager
from typing import Any

from configs.settings import DatabaseSettings, get_settings
from src.utils.logger import get_logger


logger = get_logger(__name__)


def _debug_log(hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    # region agent log
    try:
        payload = {
            "sessionId": "d4faff",
            "runId": "pre-fix",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with open("debug-d4faff.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass
    # endregion


def _normalize_cloudsql_connection_string(value: str) -> str:
    """Normalize Cloud SQL instance connection string to PROJECT:REGION:INSTANCE format.

    Some deployment environments corrupt the value (e.g. PROJECT-PZFs-central1:instance-test
    instead of project-id:us-central1:instance-test). This fixes the common corruption
    where project and region are merged and 'us-central1' loses its leading 'u'.
    """
    value = (value or "").strip()
    if not value:
        return value
    parts = value.split(":")
    if len(parts) == 3:
        # Already correct format; ensure project is lowercase (GCP requirement)
        project, region, instance = parts
        return f"{project.lower()}:{region}:{instance}"
    if len(parts) == 2:
        first, instance = parts
        # Fix corruption like "PROJECT-PZFs-central1" -> "project-id:us-central1"
        # (project+region merged, "us-central1" lost leading "u")
        match = re.match(r"^(.+?)s-([a-z]+1)$", first, re.IGNORECASE)
        if match:
            project = match.group(1).rstrip(":").lower()
            region_suffix = match.group(2).lower()
            return f"{project}:us-{region_suffix}:{instance}"
    return value


class DatabaseManager:
    """Manages PostgreSQL connections for application tables (sase_batches, sase_questions, etc.)."""

    def __init__(self, settings: DatabaseSettings | None = None) -> None:
        self._settings = settings or get_settings().database

    def get_db_connection(self) -> Any:
        """Return a PostgreSQL connection for application tables.

        Uses Cloud SQL connector when cloudsql_instance_connection_name is set,
        else direct TCP to pg_host. For pg_host path, returns a connection from
        the pool (close() returns it to the pool). Returns a connection with
        row-factory-compatible fetch behaviour (rows converted to dicts via rows_to_dicts).
        """
        s = self._settings
        instance_conn_name = _normalize_cloudsql_connection_string(
            s.cloudsql_instance_connection_name or ""
        )
        pg_host = (s.pg_host or "").strip()

        if instance_conn_name:
            pool = _get_cloudsql_pool(s, instance_conn_name)
            raw = _borrow_healthy_cloudsql_connection(pool, s, instance_conn_name)
            conn = _PooledCloudSQLConnection(raw, pool)
        elif pg_host:
            conn = _get_pool().getconn()
        else:
            raise RuntimeError(
                "DB not configured: set CLOUDSQL_INSTANCE_CONNECTION_NAME or PG_HOST "
                "(and PG_USER, PG_PASSWORD, PG_DATABASE) in configs/.env or configs/secrets/.env"
            )

        if conn is None:
            raise RuntimeError("Failed to obtain DB connection")

        # Driver-aware pgvector registration
        conn_module = type(conn).__module__
        try:
            if "pg8000" in conn_module:
                from pgvector.pg8000 import register_vector

                register_vector(conn)
            elif "psycopg2" in conn_module:
                from pgvector.psycopg2 import register_vector

                register_vector(conn)
        except (ImportError, ModuleNotFoundError, AttributeError):
            # Fallback for environments where pgvector helpers are missing, version-mismatched,
            # or inconsistent (e.g. pg8000 DBAPI vs native interface)
            pass

        return conn


_POOL: Any = None
_CLOUDSQL_CONNECTOR: Any = None
_CLOUDSQL_CONNECTOR_LOCK = threading.Lock()
_CLOUDSQL_POOL: "queue.Queue[Any] | None" = None
_CLOUDSQL_POOL_LOCK = threading.Lock()
_CLOUDSQL_POOL_SIZE: int | None = None


def _get_cloudsql_connector() -> Any:
    """Return a shared Cloud SQL connector instance."""
    global _CLOUDSQL_CONNECTOR
    if _CLOUDSQL_CONNECTOR is not None:
        return _CLOUDSQL_CONNECTOR

    with _CLOUDSQL_CONNECTOR_LOCK:
        if _CLOUDSQL_CONNECTOR is not None:
            return _CLOUDSQL_CONNECTOR

        from google.cloud.sql.connector import Connector

        _CLOUDSQL_CONNECTOR = Connector()
        return _CLOUDSQL_CONNECTOR


class _PooledCloudSQLConnection:
    """Proxy that returns the underlying pg8000 connection to a pool on close()."""

    def __init__(self, conn: Any, pool: "queue.Queue[Any]") -> None:
        self._conn = conn
        self._pool = pool

    def close(self) -> None:
        # IMPORTANT: pg8000 opens a transaction even for SELECTs. If callers forget to
        # commit/rollback before returning the connection to the pool, we can end up with
        # long-lived "idle in transaction" sessions holding locks. Make close() leave the
        # connection in a clean state for the next borrower.
        try:
            self._conn.rollback()
        except Exception:
            # Socket dead (e.g. InterfaceError: network error) — do **not** return this
            # connection to the pool or every borrower will hit the same failure.
            try:
                self._conn.close()
            except Exception:
                pass
            return

        try:
            # Return to pool for reuse; if pool is full, close it.
            self._pool.put_nowait(self._conn)
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _is_pg8000_connection_alive(conn: Any) -> bool:
    """Return True if a pg8000 connection is usable.

    Cloud SQL closes idle server-side sockets (default ~10 min). A pooled connection
    whose TCP socket was closed by the server will raise ``InterfaceError: network error``
    on the very next ``execute``. Ping with a trivial query and roll back any implicit
    transaction so the connection is returned to a clean state.
    """
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        try:
            conn.rollback()
        except Exception:
            pass
        return True
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return False


def _borrow_healthy_cloudsql_connection(
    pool: "queue.Queue[Any]",
    s: DatabaseSettings,
    instance_conn_name: str,
) -> Any:
    """Pop a live connection from the pool (pre-ping); create a new one if none are alive.

    Protects against ``pg8000.exceptions.InterfaceError: network error`` caused by
    Cloud SQL killing idle connections. Caps per-request retries to avoid unbounded
    loops if the DB is truly unreachable.
    """
    max_pings = max(pool.maxsize, 1) + 1
    for _ in range(max_pings):
        try:
            candidate = pool.get_nowait()
        except Exception:
            return _cloudsql_connect_new(s, instance_conn_name)
        if _is_pg8000_connection_alive(candidate):
            return candidate
        logger.debug("Discarded dead Cloud SQL connection during pre-ping")
    return _cloudsql_connect_new(s, instance_conn_name)


def _cloudsql_connect_new(s: DatabaseSettings, instance_conn_name: str) -> Any:
    """Create a brand-new Cloud SQL (pg8000) connection."""
    # For local development: fallback to local key if ADC is not found
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        local_key = os.path.join(
            pathlib.Path.cwd(),
            "configs",
            "secrets",
            "gcp-service-account-key.json",
        )
        if pathlib.Path(local_key).exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = local_key

    connector = _get_cloudsql_connector()
    use_iam = (s.cloudsql_use_iam_auth or "true").lower() == "true"
    db_user = (s.pg_user or "").strip()
    db_name = (s.pg_database or "postgres").strip()
    db_pass = (s.pg_password or "").strip() or None

    if use_iam:
        return connector.connect(
            instance_conn_name,
            "pg8000",
            user=db_user,
            db=db_name,
            enable_iam_auth=True,
        )
    return connector.connect(
        instance_conn_name,
        "pg8000",
        user=db_user,
        password=db_pass,
        db=db_name,
    )


def _get_cloudsql_pool(s: DatabaseSettings, instance_conn_name: str) -> "queue.Queue[Any]":
    """Return (and lazily create) a simple pool of Cloud SQL connections."""
    global _CLOUDSQL_POOL, _CLOUDSQL_POOL_SIZE
    desired_size = int(getattr(s, "pool_max_size", 10) or 10)
    if desired_size <= 0:
        desired_size = 10

    if _CLOUDSQL_POOL is not None and _CLOUDSQL_POOL_SIZE == desired_size:
        return _CLOUDSQL_POOL

    with _CLOUDSQL_POOL_LOCK:
        if _CLOUDSQL_POOL is not None and _CLOUDSQL_POOL_SIZE == desired_size:
            return _CLOUDSQL_POOL

        _CLOUDSQL_POOL = queue.Queue(maxsize=desired_size)
        _CLOUDSQL_POOL_SIZE = desired_size

        # Pre-warm a small number of connections (min size).
        min_size = int(getattr(s, "pool_min_size", 1) or 1)
        min_size = max(0, min(min_size, desired_size))
        for _ in range(min_size):
            try:
                _CLOUDSQL_POOL.put_nowait(_cloudsql_connect_new(s, instance_conn_name))
            except Exception:
                break

        return _CLOUDSQL_POOL


def _get_pool() -> Any:
    """Return the psycopg2 connection pool, creating it on first use."""
    global _POOL
    if _POOL is not None:
        return _POOL
    from psycopg2.pool import ThreadedConnectionPool

    s = get_settings().database
    sslmode = (s.pg_sslmode or "require").strip() or "require"
    sslrootcert = (s.pg_sslrootcert or "").strip() or None
    _POOL = ThreadedConnectionPool(
        minconn=s.pool_min_size,
        maxconn=s.pool_max_size,
        host=s.pg_host,
        port=s.pg_port,
        dbname=(s.pg_database or "postgres").strip(),
        user=(s.pg_user or "").strip(),
        password=(s.pg_password or "").strip() or None,
        sslmode=sslmode,
        sslrootcert=sslrootcert,
    )
    return _POOL


def get_database_manager(settings: DatabaseSettings | None = None) -> DatabaseManager:
    """Return a DatabaseManager instance. Uses get_settings().database if settings not provided."""
    return DatabaseManager(settings=settings)


def get_db_connection() -> Any:
    """Convenience: return a DB connection using default settings."""
    return get_database_manager().get_db_connection()


def warm_database_connection_pool() -> None:
    """Create the pool and establish at least one connection at process startup.

    Cloud SQL (Connector + IAM) first connect can take many seconds. Without this,
    the first authenticated HTTP request pays that cost during ``get_firebase_user``'s
    first ``db.execute``; later requests reuse the pooled connection and feel instant.
    """
    s = get_settings().database
    if not (s.cloudsql_instance_connection_name or (s.pg_host or "").strip()):
        return
    t0 = time.perf_counter()
    warmed = 0
    to_warm = max(1, int(getattr(s, "pool_min_size", 1) or 1))
    # For Cloud SQL, warm at least 2 connections so auth+handler can both
    # grab a connection without forcing a cold connector handshake.
    if s.cloudsql_instance_connection_name:
        to_warm = max(to_warm, 2)
    conns: list[Any] = []
    try:
        # Warm multiple connections so the first request doesn't force a new
        # Cloud SQL handshake when one connection is already checked out by the
        # request Session.
        for _ in range(to_warm):
            con = get_db_connection()
            conns.append(con)
            cur = con.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            warmed += 1
    except Exception as exc:
        logger.warning("Database pool warm-up failed (non-fatal): {}", exc)
    finally:
        for c in conns:
            try:
                c.close()
            except Exception:
                pass
    logger.info(
        "database pool warm-up complete | ms={} warmed={}",
        int((time.perf_counter() - t0) * 1000),
        warmed,
    )


@contextmanager
def db_connection():
    """Context manager for DB connections. Returns connection to pool on exit (psycopg2 path)."""
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()
