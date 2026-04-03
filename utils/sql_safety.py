"""
SQL safety gate and student-specific query rewriting for SPEAK2DB.
"""
import re
import logging
from typing import Optional, Tuple

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

# ---------------------------------------------------------------------------
# validate_sql_query: role-based SQL validation
# ---------------------------------------------------------------------------
_SENSITIVE_TABLES_RE = re.compile(
    r"\b(users|securitylog|activitylogs|sessionlog)\b",
    re.IGNORECASE,
)

_STUDENT_BLOCKED_OPS_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER)\b",
    re.IGNORECASE,
)

_LIBRARIAN_BLOCKED_OPS_RE = re.compile(
    r"\b(DROP|CREATE|ALTER|TRUNCATE|REPLACE|MERGE|GRANT|REVOKE|EXECUTE|EXEC|CALL|PRAGMA)\b",
    re.IGNORECASE,
)


def get_current_student_id(conn, session: dict) -> Optional[int]:
    """Look up the authoritative student PK for the logged-in user.

    Uses ``session['user_id']`` (the roll number) to query the Students table
    and return the integer primary key.  Returns ``None`` when the student
    cannot be found or the session has no ``user_id``.

    Parameters
    ----------
    conn    : An open SQLite connection to the main database.
    session : The Flask session dict (must contain ``'user_id'``).
    """
    roll_number = session.get("user_id")
    if not roll_number:
        logger.warning("get_current_student_id: no user_id in session")
        return None
    try:
        row = conn.execute(
            "SELECT id FROM Students WHERE roll_number = ?", (roll_number,)
        ).fetchone()
        if row:
            return int(row[0])
        logger.warning("get_current_student_id: no student found for roll_number=%r", roll_number)
        return None
    except Exception as exc:
        logger.error("get_current_student_id: DB error: %s", exc)
        return None


def is_my_query(query: str) -> bool:
    """Return ``True`` when *query* contains a first-person possessive keyword.

    Detects ``my``, ``mine``, or ``me`` as whole words so that words like
    "time" or "some" are not falsely matched.
    """
    return bool(re.search(r"\b(my|mine|me)\b", query, re.IGNORECASE))


# Regex to strip hardcoded ``student_id = <number>`` injected by the LLM.
_HARDCODED_STUDENT_ID_RE = re.compile(
    r"\bstudent_id\s*=\s*\d+\b",
    re.IGNORECASE,
)


# Patterns for personal-intent detection (word boundaries to avoid false matches)
_FINES_PATTERN = re.compile(r"\b(fines?|payment)\b", re.IGNORECASE)
_BOOKS_PATTERN = re.compile(r"\b(borrowed|issued|books?)\b", re.IGNORECASE)
_DETAILS_PATTERN = re.compile(r"\b(details?|profile|account|info|records?)\b", re.IGNORECASE)


def enforce_student_context(
    sql: str,
    user_query: str,
    session: dict,
    conn,
) -> str:
    """Rewrite *sql* so that it is always scoped to the currently logged-in student.

    For non-Student roles the original *sql* is returned unchanged.

    Steps performed for Student role
    ---------------------------------
    1. Look up the authoritative ``student_id`` from the database via
       :func:`get_current_student_id`.
    2. Strip any hardcoded ``student_id = <number>`` literals emitted by the
       LLM to prevent data leakage to wrong accounts.
    3. If the natural-language *user_query* expresses personal intent (detected
       by :func:`is_my_query`), replace *sql* with a safe, alias-correct
       template:

       * ``fines``             → ``SELECT f.id AS fine_id, …`` filtered by student
       * ``borrowed`` / ``issued`` → ``SELECT b.book_id, …`` JOIN query with open loans
       * ``details`` / ``profile`` / ``account`` → student profile row

    4. Fall back to :func:`apply_student_filters` for broader pattern matching
       when none of the explicit templates apply.

    Parameters
    ----------
    sql        : SQL produced by the NL-to-SQL engine.
    user_query : Original natural-language query from the user.
    session    : Flask session dict.
    conn       : Open SQLite connection used for the student lookup.
    """
    role = session.get("role", "")
    if role != "Student":
        return sql

    student_id = get_current_student_id(conn, session)
    if student_id is None:
        # Fall back to session value so we never expose data with no filter at all
        student_id = session.get("student_id")
        if not student_id:
            logger.warning("enforce_student_context: cannot determine student_id; query unchanged")
            return sql
    try:
        student_id = int(student_id)
    except (TypeError, ValueError):
        logger.error("enforce_student_context: invalid student_id=%r", student_id)
        return sql

    # ── Step 2: Remove any hardcoded student_id injected by the LLM ─────────
    # student_id has already been validated as int above, so direct string
    # interpolation is safe here (no injection risk from external input).
    sql = _HARDCODED_STUDENT_ID_RE.sub(f"student_id = {student_id}", sql)

    q_lower = user_query.lower()

    if not is_my_query(user_query):
        # Not a personal query – still apply table-level row filtering
        return apply_student_filters(user_query, sql, student_id)

    # ── Step 3: Personal-intent templates ────────────────────────────────────
    if _FINES_PATTERN.search(q_lower):
        return (
            f"SELECT "
            f"f.id AS fine_id, "
            f"f.fine_amount, "
            f"f.fine_type, "
            f"f.status "
            f"FROM Fines f "
            f"WHERE f.student_id = {student_id}"
        )

    if _BOOKS_PATTERN.search(q_lower):
        return (
            f"SELECT "
            f"b.book_id, "
            f"b.title, "
            f"b.author "
            f"FROM Books b "
            f"JOIN Issued i ON b.book_id = i.book_id "
            f"WHERE i.student_id = {student_id} "
            f"AND i.return_date IS NULL"
        )

    if _DETAILS_PATTERN.search(q_lower):
        return (
            f"SELECT "
            f"id AS student_id, "
            f"roll_number, "
            f"name, "
            f"email "
            f"FROM Students "
            f"WHERE id = {student_id}"
        )

    # ── Step 4: Broader pattern matching via existing helper ─────────────────
    return apply_student_filters(user_query, sql, student_id)


def validate_sql_query(query: str, role: str) -> bool:
    """Validate a SQL query against role-based access rules.

    Returns ``True`` if the query is permitted for *role*, ``False`` otherwise.

    Parameters
    ----------
    query : str
        The SQL query string to validate.
    role : str
        The authenticated user's role.  Expected values: ``'Student'``,
        ``'Librarian'``, or ``'Administrator'``.

    Rules
    -----
    **Student**:
      - Only SELECT statements are allowed.
      - Blocks: INSERT, UPDATE, DELETE, DROP, ALTER.
      - Blocks access to: users, securitylog, activitylogs, sessionlog.

    **Librarian**:
      - SELECT, INSERT, UPDATE, DELETE are allowed.
      - Blocks DDL: DROP, CREATE, ALTER, TRUNCATE, etc.
      - Blocks access to: users, securitylog, activitylogs, sessionlog.

    **Administrator**:
      - No restrictions enforced here (returns True for any non-empty query).
    """
    if not query or not query.strip():
        return False

    q = query.strip()
    q_upper = q.upper().lstrip()

    # Block access to sensitive tables for all non-Administrator roles
    if role != "Administrator" and _SENSITIVE_TABLES_RE.search(q):
        logger.warning(
            "validate_sql_query: blocked sensitive table access for role=%s", role
        )
        return False

    if role == "Student":
        # Students may only run SELECT statements
        if not q_upper.startswith("SELECT"):
            logger.warning("validate_sql_query: Student attempted non-SELECT query")
            return False
        if _STUDENT_BLOCKED_OPS_RE.search(q):
            logger.warning("validate_sql_query: Student attempted blocked operation")
            return False

    elif role == "Librarian":
        # Librarians may run SELECT, INSERT, UPDATE, DELETE but not DDL
        allowed_starts = ("SELECT", "INSERT", "UPDATE", "DELETE")
        if not any(q_upper.startswith(s) for s in allowed_starts):
            logger.warning(
                "validate_sql_query: Librarian attempted disallowed statement type"
            )
            return False
        if _LIBRARIAN_BLOCKED_OPS_RE.search(q):
            logger.warning(
                "validate_sql_query: Librarian attempted blocked DDL operation"
            )
            return False

    return True


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
                r"\bstudent_id\s*=\s*" + re.escape(str(sid)) + r"\b",
                sql_query,
                re.IGNORECASE,
            )
        )
        if not already_filtered:
            if has_where:
                return _inject_and_condition(sql_query, f"student_id = {sid}")
            return sql_query + f" WHERE student_id = {sid}"
        return sql_query

    if primary_table == "students":
        # Always restrict the Students table to the logged-in student's own row,
        # regardless of whether a WHERE clause already exists.
        already_filtered = bool(
            re.search(
                r"\bid\s*=\s*" + re.escape(str(sid)) + r"\b",
                sql_query,
                re.IGNORECASE,
            )
        )
        if not already_filtered:
            if has_where:
                return _inject_and_condition(sql_query, f"id = {sid}")
            return sql_query + f" WHERE id = {sid}"
        return sql_query

    if "my" not in q_lower:
        return sql_query

    _fines_base = (
        f"SELECT f.id AS fine_id, f.student_id, f.fine_amount, f.fine_type, f.status, f.issue_date, s.name as student_name FROM Fines f "
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


def enforce_student_filter(user_query: str, sql_query: str, session_data: dict) -> str:
    """Enforce student data isolation by rewriting *sql_query*.

    Only modifies queries for the ``Student`` role.  For other roles the
    original *sql_query* is returned unchanged.

    Handles natural-language patterns such as "my borrowed books", "my fines",
    and "my details" by delegating to :func:`apply_student_filters`, which
    builds the correct JOIN queries and appends ``WHERE student_id = <id>``.

    Parameters
    ----------
    user_query   : The original natural-language query from the user.
    sql_query    : The SQL generated by the NL-to-SQL engine.
    session_data : The Flask session dict (must contain ``'role'`` and
                   ``'student_id'`` keys for students).
    """
    role = session_data.get("role", "")
    if role != "Student":
        return sql_query

    student_id = session_data.get("student_id")
    if not student_id:
        logger.warning(
            "enforce_student_filter: Student role but no student_id in session"
        )
        return sql_query

    return apply_student_filters(user_query, sql_query, student_id)


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
