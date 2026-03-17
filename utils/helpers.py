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


def is_staff(role: str) -> bool:
    """Return whether *role* should be treated as library staff."""
    return role in ('Librarian', 'Faculty', 'Administrator')


def record_query_event(
    *,
    user_id: str,
    role: str,
    user_query: str,
    sql_query: str,
    success: bool,
    response_time: float,
    activity_message: str = None,
    audit_entry: tuple = None,
    activity_logger=None,
    history_logger=None,
    audit_logger=None,
):
    """Persist repeated query history/activity/audit side effects."""
    if history_logger:
        history_logger(user_id, role, user_query, sql_query, success, response_time)
    if activity_message and activity_logger:
        activity_logger(user_id, activity_message)
    if audit_entry and audit_logger:
        action, resource_type, details = audit_entry
        audit_logger(user_id, role, action, resource_type, details, success=success)
