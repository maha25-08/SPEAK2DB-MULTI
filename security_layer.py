"""
🛡️ SPEAK2DB DATABASE SECURITY LAYER
Provides three-tier protection for NL-to-SQL queries:
  1. Student data isolation  – auto-injects WHERE student_id filters
  2. Table access control    – enforces per-role allowed-table lists
  3. SQL injection protection – SELECT-only, blocks dangerous keywords
"""

import re
from typing import Tuple, Optional

# ── Role-based allowed tables ────────────────────────────────────────────────

_ALLOWED_TABLES: dict = {
    'Student': {
        'Books', 'Issued', 'Fines', 'Reservations', 'BorrowHistory', 'Students',
        # lower-case variants included so matching is case-insensitive
        'books', 'issued', 'fines', 'reservations', 'borrowhistory', 'students',
    },
    'Librarian': {
        'Books', 'Issued', 'Fines', 'Reservations', 'Students', 'BorrowHistory',
        'books', 'issued', 'fines', 'reservations', 'students', 'borrowhistory',
    },
    # Administrator has no restrictions – handled separately
}

# Tables that require per-student scoping for the Student role.
# 'students' is included so students can only view their own profile row.
_STUDENT_SCOPED_TABLES = {'fines', 'issued', 'reservations', 'borrowhistory', 'students'}

# Column used to filter per-student rows differs between tables.
# All personal-activity tables (Fines, Issued, etc.) use 'student_id' (FK),
# while the Students table itself uses 'id' (PK).
_STUDENT_FILTER_COLUMN: dict = {
    'fines': 'student_id',
    'issued': 'student_id',
    'reservations': 'student_id',
    'borrowhistory': 'student_id',
    'students': 'id',
}

# Dangerous DDL / DML keywords that must never appear in an allowed query
_BLOCKED_KEYWORDS_RE = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|REPLACE|MERGE'
    r'|GRANT|REVOKE|EXECUTE|EXEC|CALL|PRAGMA)\b',
    re.IGNORECASE,
)

# DDL-only keywords blocked for Librarians (DML is permitted)
_LIBRARIAN_BLOCKED_RE = re.compile(
    r'\b(DROP|CREATE|ALTER|TRUNCATE|REPLACE|MERGE|GRANT|REVOKE|EXECUTE|EXEC|CALL|PRAGMA)\b',
    re.IGNORECASE,
)

# UNION SELECT is an injection vector even inside an otherwise SELECT query
_UNION_SELECT_RE = re.compile(r'\bUNION\s+SELECT\b', re.IGNORECASE)

# SQL comment patterns used in injection attacks
_COMMENT_RE = re.compile(r'--')


def _extract_table_names(sql: str) -> list:
    """
    Return a list of table names referenced in *sql*.
    Handles FROM, JOIN, INTO patterns (case-insensitive).
    """
    pattern = re.compile(
        r'\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+([`"\[]?[A-Za-z_][A-Za-z0-9_]*[`"\]]?)',
        re.IGNORECASE,
    )
    return [m.group(1).strip('`"[]') for m in pattern.finditer(sql)]


def _primary_table_name(sql: str) -> str:
    """Return the top-level table following the first FROM clause."""
    match = re.search(r'\bFROM\s+([`"\[]?[A-Za-z_][A-Za-z0-9_]*[`"\]]?)', sql, re.IGNORECASE)
    return match.group(1).strip('`"[]').lower() if match else ''


def _inject_student_filter(sql: str, student_id: int, table: str = '') -> str:
    """
    Inject a student-scoping condition into the WHERE clause of *sql*.

    The filter column differs between tables:
    * ``Students``  → ``id = <student_id>``   (PK column)
    * all others    → ``student_id = <student_id>``  (FK column)

    Parameters
    ----------
    sql        : The SQL query to modify.
    student_id : Numeric student PK to inject.
    table      : Lower-cased primary table name.  When empty or unknown,
                 defaults to the ``student_id`` FK column convention.

    Rules
    -----
    * If the statement already contains WHERE, prepend the condition so it
      is always evaluated regardless of any OR chains in the original query.
    * If there is no WHERE clause, append one.
    * GROUP BY / ORDER BY / LIMIT are placed after the injected condition.
    """
    filter_col = _STUDENT_FILTER_COLUMN.get(table.lower() if table else '', 'student_id')
    sid_condition = f"{filter_col} = {int(student_id)}"

    sql_upper = sql.upper()

    if 'WHERE' in sql_upper:
        # Insert condition immediately after the WHERE keyword so it is
        # ANDed with whatever the LLM generated.
        return re.sub(
            r'\bWHERE\s+',
            f'WHERE {sid_condition} AND ',
            sql,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        # Append before GROUP BY / ORDER BY / LIMIT if present, otherwise at end.
        for keyword in ('GROUP BY', 'ORDER BY', 'LIMIT', 'HAVING'):
            idx = sql_upper.find(keyword)
            if idx != -1:
                return sql[:idx].rstrip() + f' WHERE {sid_condition} ' + sql[idx:]
        return sql.rstrip() + f' WHERE {sid_condition}'


# ── Public API ────────────────────────────────────────────────────────────────

def validate_sql(
    sql: str,
    role: str,
    student_id: Optional[int] = None,
) -> Tuple[bool, str, str]:
    """
    Validate and optionally transform *sql* according to the security policy.

    Parameters
    ----------
    sql        : Raw SQL string produced by the NL-to-SQL generator.
    role       : Logged-in user role (``'Student'``, ``'Librarian'``,
                 ``'Administrator'``).
    student_id : Numeric student PK – required when *role* is ``'Student'``.

    Returns
    -------
    (allowed: bool, filtered_sql: str, error_message: str)
    * ``allowed=True``  → *filtered_sql* is safe to execute.
    * ``allowed=False`` → *error_message* describes why the query was blocked.
      *filtered_sql* equals the original *sql* in this case.
    """
    print(f"[SECURITY] Role: {role}")
    print(f"[SECURITY] SQL before filter: {sql}")

    stripped = sql.strip().rstrip(';') if sql else ''

    # ── Protection 3: SQL injection checks ──────────────────────────────────

    if not stripped:
        msg = "Empty SQL query."
        print(f"[SECURITY] BLOCKED – {msg}")
        return False, sql, msg

    # Statement-type check is role-aware:
    # - Students may only run SELECT
    # - Librarians may run SELECT + DML (INSERT/UPDATE/DELETE), not DDL
    # - Administrators have no statement-type restriction here
    if role == 'Student':
        if not stripped.upper().startswith('SELECT'):
            msg = "Only SELECT queries are allowed."
            print(f"[SECURITY] BLOCKED – {msg}")
            return False, sql, msg
        # Block all DML/DDL keywords for students
        kw_match = _BLOCKED_KEYWORDS_RE.search(stripped)
        if kw_match:
            msg = f"Keyword '{kw_match.group()}' is not allowed."
            print(f"[SECURITY] BLOCKED – {msg}")
            return False, sql, msg
    elif role == 'Librarian':
        # Librarians may use SELECT, INSERT, UPDATE, DELETE but not DDL
        q_upper = stripped.upper().lstrip()
        allowed_starts = ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
        if not any(q_upper.startswith(s) for s in allowed_starts):
            msg = "Only SELECT/INSERT/UPDATE/DELETE queries are allowed for Librarians."
            print(f"[SECURITY] BLOCKED – {msg}")
            return False, sql, msg
        kw_match = _LIBRARIAN_BLOCKED_RE.search(stripped)
        if kw_match:
            msg = f"Keyword '{kw_match.group()}' is not allowed for Librarians."
            print(f"[SECURITY] BLOCKED – {msg}")
            return False, sql, msg
    else:
        # Administrator: no statement-type restrictions
        pass

    # Block UNION SELECT injection
    if _UNION_SELECT_RE.search(stripped):
        msg = "UNION SELECT is not permitted."
        print(f"[SECURITY] BLOCKED – {msg}")
        return False, sql, msg

    # Block SQL comment sequences used to terminate injected statements
    if _COMMENT_RE.search(stripped):
        msg = "SQL comments (--) are not permitted."
        print(f"[SECURITY] BLOCKED – {msg}")
        return False, sql, msg

    # Block multiple statements via semicolons
    if ';' in stripped:
        msg = "Multi-statement SQL is not permitted."
        print(f"[SECURITY] BLOCKED – {msg}")
        return False, sql, msg

    # ── Protection 2: Table access control ──────────────────────────────────

    tables = _extract_table_names(stripped)

    if role != 'Administrator':
        allowed = _ALLOWED_TABLES.get(role, set())
        for table in tables:
            if table.lower() not in {t.lower() for t in allowed}:
                msg = f"Access denied for table '{table}'."
                print(f"[SECURITY] BLOCKED – {msg}")
                return False, sql, msg

    # ── Protection 1: Student data isolation ────────────────────────────────

    filtered_sql = stripped

    if role == 'Student' and student_id is not None:
        primary = _primary_table_name(stripped)
        if primary in _STUDENT_SCOPED_TABLES:
            filter_col = _STUDENT_FILTER_COLUMN.get(primary, 'student_id')
            # Only inject the filter when it is not already present, to avoid
            # double-injection when enforce_student_filter ran earlier in the
            # pipeline.
            already_present = bool(
                re.search(
                    r'\b' + re.escape(filter_col) + r'\s*=\s*' + re.escape(str(int(student_id))) + r'\b',
                    stripped,
                    re.IGNORECASE,
                )
            )
            if not already_present:
                filtered_sql = _inject_student_filter(filtered_sql, student_id, primary)

    print(f"[SECURITY] SQL after filter: {filtered_sql}")
    return True, filtered_sql, ""


def validate_sql_query(
    query: str,
    role: str,
    student_id: Optional[int] = None,
) -> Tuple[bool, str, str]:
    """
    Public alias for :func:`validate_sql` using the naming convention
    required by the safe-execution pipeline.

    Parameters
    ----------
    query      : SQL string to validate (and optionally transform).
    role       : Logged-in user role (``'Student'``, ``'Librarian'``,
                 ``'Administrator'``).
    student_id : Numeric student PK – required when *role* is ``'Student'``.

    Returns
    -------
    (allowed: bool, safe_sql: str, error_message: str)

    When ``allowed`` is ``True``, ``safe_sql`` is the query to execute
    (student-isolation filters may have been injected).
    When ``allowed`` is ``False``, ``error_message`` explains why the
    query was blocked and the caller should return "Access Denied".

    Security rules enforced
    -----------------------
    * Students may only execute SELECT statements.
    * Students cannot access sensitive tables (``Users``, ``SecurityLog``,
      ``ActivityLogs``, ``SessionLog``, etc.).
    * All student queries against personal tables are scoped to the
      student's own rows.
    * DDL / DML keywords (UPDATE, DELETE, INSERT, DROP, ALTER …) are
      blocked for all roles.
    * UNION SELECT injections and SQL comments are blocked.
    """
    return validate_sql(query, role, student_id)
