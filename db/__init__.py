"""Database package for SPEAK2DB."""
from .connection import get_db_connection, MAIN_DB, ARCHIVE_DB, ensure_query_history_schema

__all__ = ["get_db_connection", "MAIN_DB", "ARCHIVE_DB", "ensure_query_history_schema"]
