"""
SQL safety gate and student-specific query rewriting for SPEAK2DB.
"""
import re
import logging
from typing import Tuple

from utils.constants import DEFAULT_QUERY_LIMIT

logger = logging.getLogger(__name__)
_LIMIT_PATTERN = re.compile(r"\bLIMIT\s+(\d+)(?:\s+OFFSET\s+\d+)?\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Blocked DDL / DML keywords
# ---------------------------------------------------------------------------
_BLOCKED_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|REPLACE|MERGE"
    r"|GRANT|REVOKE|EXECUTE|EXEC|CALL|PRAGMA)\b",
    re.IGNORECASE,
)


def is_safe_sql(sql: str) -> Tuple[bool, str]:
    """Return ``(True, '')`` for a safe single SELECT, otherwise ``(False, reason)``.

    Empty SQL is treated as safe so the caller can substitute a default query.
    """
    stripped = sql.strip().rstrip(";") if sql else ""

    if not stripped:
        return True, ""

    if not stripped.upper().startswith("SELECT"):
        return False, "Only SELECT queries are permitted."

    match = _BLOCKED_KEYWORDS.search(stripped)
    if match:
        return False, f"Keyword '{match.group()}' is not allowed."

    if ";" in stripped:
        return False, "Multi-statement SQL is not permitted."

    return True, ""


def ensure_limit(sql: str, limit: int = DEFAULT_QUERY_LIMIT) -> str:
    """Append or cap ``LIMIT <limit>`` on *sql*."""
    if not sql:
        return sql
    limit_match = _LIMIT_PATTERN.search(sql)
    if not limit_match:
        return sql.rstrip().rstrip(";") + f" LIMIT {limit}"
    current_limit = int(limit_match.group(1))
    if current_limit <= limit:
        return sql
    return _LIMIT_PATTERN.sub(lambda match: match.group(0).replace(match.group(1), str(limit), 1), sql, count=1)


def _inject_and_condition(sql_query: str, condition: str) -> str:
    """Inject *condition* immediately after the WHERE keyword."""
    match = re.search(r"\bWHERE\b", sql_query, re.IGNORECASE)
    if match:
        pos = match.end()
        return sql_query[:pos] + f" {condition} AND" + sql_query[pos:]
    return sql_query + f" WHERE {condition}"


def _primary_table_name(sql_query: str) -> str:
    """Return the top-level table following FROM, if present."""
    match = re.search(r"\bFROM\s+([A-Za-z_][A-Za-z0-9_]*)\b", sql_query, re.IGNORECASE)
    return match.group(1).lower() if match else ""


def apply_student_filters(user_query: str, sql_query: str, student_id: int) -> str:
    """Rewrite *sql_query* to restrict results to the given *student_id*.

    Ensures students can only see their own data in personal tables
    (Fines, Issued, Reservations) even when the generated SQL omits filtering.
    """
    # Validate student_id early to avoid downstream issues.
    try:
        sid = int(student_id)
    except (TypeError, ValueError):
        logger.error("apply_student_filters: invalid student_id=%r", student_id)
        return sql_query

    q_lower = user_query.lower()
    sq_lower = sql_query.lower()
    has_where = "WHERE" in sql_query.upper()
    primary_table = _primary_table_name(sql_query)

    # ── Always restrict personal tables ─────────────────────────────────────
    if primary_table in {"fines", "issued", "reservations"}:
        already_filtered = bool(
            re.search(
                r"\bstudent_id\s*=\s*" + str(sid) + r"\b",
                sql_query,
                re.IGNORECASE,
            )
        )
        if not already_filtered:
            if has_where:
                return _inject_and_condition(sql_query, f"student_id = {sid}")
            return sql_query + f" WHERE student_id = {sid}"
        return sql_query

    if primary_table == "students" and not has_where:
        return sql_query + f" WHERE id = {sid}"

    if "my" not in q_lower:
        return sql_query

    _fines_base = (
        f"SELECT f.*, s.name as student_name FROM Fines f "
        f"JOIN Students s ON f.student_id = s.id "
        f"WHERE f.student_id = {sid}"
    )
    _books_base = (
        f"SELECT i.*, b.title, b.author FROM Issued i "
        f"JOIN Books b ON i.book_id = b.id "
        f"WHERE i.student_id = {sid}"
    )
    _profile_base = (
        f"SELECT s.*, d.name as department_name FROM Students s "
        f"JOIN Departments d ON s.branch = d.id "
        f"WHERE s.id = {sid}"
    )

    # ── Fine / payment patterns ──────────────────────────────────────────────
    if any(
        k in q_lower
        for k in (
            "my fines",
            "my fine",
            "my fine records",
            "my payment history",
            "my payment records",
        )
    ):
        return _fines_base + " ORDER BY f.issue_date DESC"

    if any(
        k in q_lower
        for k in ("my current fines", "my unpaid fines", "my outstanding fines")
    ):
        return _fines_base + " AND f.status = 'Unpaid' ORDER BY f.issue_date DESC"

    if "my outstanding balance" in q_lower or "my library account balance" in q_lower:
        return (
            f"SELECT s.name, SUM(f.fine_amount) as total_balance "
            f"FROM Students s LEFT JOIN Fines f ON s.id = f.student_id "
            f"WHERE s.id = {sid} AND f.status = 'Unpaid' GROUP BY s.id, s.name"
        )
    if "my total fines" in q_lower:
        return (
            f"SELECT s.name, SUM(f.fine_amount) as total_balance "
            f"FROM Students s LEFT JOIN Fines f ON s.id = f.student_id "
            f"WHERE s.id = {sid} AND f.status = 'Unpaid' GROUP BY s.id, s.name"
        )

    # ── Book / borrowing patterns ────────────────────────────────────────────
    if any(k in q_lower for k in ("my current books", "books due")):
        return _books_base + " AND i.return_date IS NULL ORDER BY i.due_date ASC"

    if "my overdue" in q_lower:
        return (
            _books_base
            + " AND i.return_date IS NULL AND i.due_date < date('now')"
        )

    if any(
        k in q_lower
        for k in (
            "my books",
            "my issued books",
            "my borrowed books",
            "my borrowing history",
            "my reading history",
            "my total books",
        )
    ):
        return _books_base + " ORDER BY i.issue_date DESC"

    # ── Reservation patterns ─────────────────────────────────────────────────
    if any(k in q_lower for k in ("my reservations", "my reserved books")):
        return (
            f"SELECT r.*, b.title, b.author FROM Reservations r "
            f"JOIN Books b ON r.book_id = b.id "
            f"WHERE r.student_id = {sid} ORDER BY r.reservation_date DESC"
        )

    # ── Profile / account patterns ───────────────────────────────────────────
    if any(
        k in q_lower
        for k in (
            "my profile",
            "my student info",
            "my account details",
            "my student record",
            "my personal information",
            "my personal details",
            "my enrollment",
        )
    ):
        return _profile_base

    if any(
        k in q_lower
        for k in (
            "my account",
            "my library account",
            "my library status",
            "my library record",
            "my library history",
            "my personal data",
        )
    ):
        return _profile_base

    # ── Academic patterns ────────────────────────────────────────────────────
    if any(
        k in q_lower
        for k in (
            "my gpa",
            "my attendance",
            "my academic",
            "my semester",
            "my course",
            "my grades",
            "my current status",
            "my current semester",
            "my current year",
        )
    ):
        return (
            f"SELECT gpa, attendance, role, created_date "
            f"FROM Students WHERE id = {sid}"
        )

    # ── Generic patterns ─────────────────────────────────────────────────────
    if "do i have" in q_lower or "what are my" in q_lower or "am i" in q_lower:
        if "fine" in q_lower:
            return _fines_base + " AND f.status = 'Unpaid' ORDER BY f.issue_date DESC"
        if "book" in q_lower:
            return _books_base + " AND i.return_date IS NULL ORDER BY i.due_date ASC"
        if "reservat" in q_lower:
            return (
                f"SELECT r.*, b.title, b.author FROM Reservations r "
                f"JOIN Books b ON r.book_id = b.id "
                f"WHERE r.student_id = {sid} ORDER BY r.reservation_date DESC"
            )

    if "how much do i owe" in q_lower:
        return (
            f"SELECT s.name, SUM(f.fine_amount) as total_balance "
            f"FROM Students s LEFT JOIN Fines f ON s.id = f.student_id "
            f"WHERE s.id = {sid} AND f.status = 'Unpaid' GROUP BY s.id, s.name"
        )

    if "when are my" in q_lower and "due" in q_lower:
        return _books_base + " AND i.return_date IS NULL ORDER BY i.due_date ASC"

    return sql_query


def fallback_columns(sql_query: str) -> list:
    """Return a sensible fallback column list when a query returns no rows."""
    sq = sql_query.lower()
    if "books" in sq:
        return ["id", "title", "author", "category", "total_copies", "available_copies"]
    if "students" in sq:
        return ["id", "roll_number", "name", "branch", "year", "email", "gpa"]
    if "faculty" in sq:
        return ["id", "name", "department", "designation", "email"]
    if "fines" in sq:
        return ["id", "student_id", "fine_amount", "fine_type", "status", "issue_date"]
    if "issued" in sq:
        return ["id", "student_id", "book_id", "issue_date", "due_date", "return_date"]
    return ["id", "name"]
