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


def get_db_connection(db_path: str) -> sqlite3.Connection:
    """Return a SQLite connection with row_factory set."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 3000")
    return conn


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
