"""Database manager for PostgreSQL / Cloud SQL connections."""

from src.services.database_manager.connection import (
    DatabaseManager,
    db_connection,
    get_database_manager,
    get_db_connection,
)
from src.services.database_manager.operations import rows_to_dicts
from src.services.database_manager.registry import (
    RegistryClient,
    delete_document_from_registry,
    get_chunk_registry,
    get_document_registry,
    list_document_ids_for_opportunity,
    write_ingestion_registry,
)


__all__ = [
    "DatabaseManager",
    "RegistryClient",
    "db_connection",
    "delete_document_from_registry",
    "get_chunk_registry",
    "get_database_manager",
    "get_db_connection",
    "get_document_registry",
    "list_document_ids_for_opportunity",
    "rows_to_dicts",
    "write_ingestion_registry",
]
