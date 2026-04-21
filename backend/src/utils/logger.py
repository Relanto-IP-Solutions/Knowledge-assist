"""Structured logging for the application using loguru. Uses opportunity_id for log tracking."""

import os
import pathlib
import sys
import threading

from loguru import logger

from configs.settings import get_settings


_logging_initialized = False
_logging_lock = threading.Lock()


def setup_logging(
    log_dir: str | None = None,
    log_level: str | None = None,
    log_file: str | None = None,
    max_bytes: int | None = None,
    backup_count: int | None = None,
):
    """Configure loguru with file and console handlers. Idempotent on repeated calls."""
    global _logging_initialized
    with _logging_lock:
        if _logging_initialized:
            return logger

        settings = get_settings().logging
        log_dir = log_dir or settings.directory
        log_level = log_level or settings.level
        log_file = log_file or settings.name
        max_bytes = max_bytes or settings.max_bytes
        backup_count = (
            backup_count if backup_count is not None else settings.backup_count
        )

        pathlib.Path(log_dir).mkdir(exist_ok=True, parents=True)

        logger.remove()

        log_format = (
            "{time:YYYY-MM-DD HH:mm:ss} - {level} - {extra[name]} - "
            "{extra[opportunity_id]} - {message}"
        )

        logger.add(
            sys.stderr,
            format=log_format,
            level=log_level,
            colorize=True,
        )

        logger.add(
            os.path.join(log_dir, log_file),
            format=log_format,
            level=log_level,
            rotation=max_bytes,
            retention=backup_count,
            colorize=False,
        )

        _logging_initialized = True
        return logger


def get_logger(name: str):
    """Return a loguru logger bound to the given name. Triggers lazy setup on first call.

    Loguru does **not** interpolate ``%s`` / ``%r`` / ``%d`` (that is standard-library ``logging``).
    Use brace placeholders: ``logger.info("Hello {}", name)``, ``{!r}`` for repr, ``{:.1f}`` for floats.
    Optional context: ``logger.bind(key=val).info("...")`` (not ``extra=``).
    """
    setup_logging()
    return logger.bind(name=name, opportunity_id="N/A")
