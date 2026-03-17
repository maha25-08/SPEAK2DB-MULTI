"""
General-purpose helper functions for SPEAK2DB.
"""
import logging
from db.connection import get_db_connection, MAIN_DB

logger = logging.getLogger(__name__)


def get_library_stats() -> dict:
    """Fetch common library statistics for librarian/admin dashboard panels."""
    try:
        conn = get_db_connection(MAIN_DB)
        total_books = conn.execute("SELECT COUNT(*) as cnt FROM Books").fetchone()["cnt"]
        total_students = conn.execute(
            "SELECT COUNT(*) as cnt FROM Students"
        ).fetchone()["cnt"]
        active_issues = conn.execute(
            "SELECT COUNT(*) as cnt FROM Issued WHERE return_date IS NULL"
        ).fetchone()["cnt"]
        unpaid_fines = conn.execute(
            "SELECT COUNT(*) as cnt FROM Fines WHERE status = 'Unpaid'"
        ).fetchone()["cnt"]
        conn.close()
        return {
            "total_books": total_books,
            "total_students": total_students,
            "active_issues": active_issues,
            "unpaid_fines": unpaid_fines,
        }
    except Exception as exc:
        logger.error("get_library_stats DB error: %s", exc)
        return {}
