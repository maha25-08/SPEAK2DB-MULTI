"""
Database connection and schema management for SPEAK2DB.
"""
import logging
import os
import sqlite3

logger = logging.getLogger(__name__)

# Database paths
MAIN_DB = os.getenv("MAIN_DB", "library_main.db")
ARCHIVE_DB = os.getenv("ARCHIVE_DB", "library_archive.db")
MANAGEMENT_DB = os.getenv("MANAGEMENT_DB", "library_management.db")
SQLITE_BUSY_TIMEOUT_MS = int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "3000"))


def get_db_connection(db_path: str) -> sqlite3.Connection:
    """Return a SQLite connection with row_factory set."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    return conn


def get_main_db() -> sqlite3.Connection:
    """Return a connection to the main application database (library_main.db)."""
    return get_db_connection(MAIN_DB)


def get_management_db() -> sqlite3.Connection:
    """Return a connection to the library management database (library_management.db)."""
    return get_db_connection(MANAGEMENT_DB)


def get_archive_db() -> sqlite3.Connection:
    """Return a connection to the archive/history database (library_archive.db)."""
    return get_db_connection(ARCHIVE_DB)


def ensure_query_history_schema() -> None:
    """Add the ``role`` column to QueryHistory if it was created without it."""
    try:
        conn = sqlite3.connect(MAIN_DB)
        existing = {row[1] for row in conn.execute("PRAGMA table_info(QueryHistory)").fetchall()}
        if "role" not in existing:
            conn.execute("ALTER TABLE QueryHistory ADD COLUMN role TEXT")
            conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("QueryHistory schema migration skipped: %s", exc)
