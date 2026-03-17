"""
🗃️ SPEAK2DB - NL-to-SQL Query Assistant
Integrated with domain vocabulary, clarification chatbot, RBAC,
SQL safety gate, and security headers.
"""

import logging
import os
import jinja2
import time
import json
from ollama_sql import generate_sql
import pandas as pd
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Tuple
from werkzeug.security import generate_password_hash, check_password_hash

# ── New pipeline modules ────────────────────────────────────────────────────
from domain_vocabulary import build_vocabulary, preprocess_query, get_vocabulary_sample
from clarification import is_ambiguous_query, get_clarification, apply_clarification_choice
from query_correction import correct_query
from query_context import save_context, is_followup, rewrite_followup, get_last_query

# ── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Database package ─────────────────────────────────────────────────────────
from db.connection import get_db_connection, MAIN_DB, ARCHIVE_DB, ensure_query_history_schema

# ── Security headers (Option 2 – safe, non-breaking) ────────────────────────
try:
    from security_layers import apply_security_headers
    _SECURITY_HEADERS_AVAILABLE = True
except ImportError:
    _SECURITY_HEADERS_AVAILABLE = False

# Database paths
MAIN_DB = "library_main.db"
ARCHIVE_DB = "library_archive.db"
SUPPORTED_ROLES = ('Student', 'Faculty', 'Librarian', 'Administrator')
REGISTRATION_ROLES = ('Student', 'Faculty', 'Librarian')
DEFAULT_QUERY_PERMISSION = 'query:execute_select'
MANAGED_TABLES = [
    'Books', 'Students', 'Faculty', 'Issued', 'Fines', 'Reservations',
    'Users', 'Departments', 'Publishers', 'QueryHistory',
    'ActivityLogs', 'SecurityLog', 'SecurityAlerts', 'SessionLog',
]
DEFAULT_ROLE_TABLE_ACCESS = {
    'Student': {'Books', 'Issued', 'Fines', 'Reservations', 'Students'},
    'Faculty': {'Books', 'Faculty', 'Departments', 'QueryHistory'},
    'Librarian': {
        'Books', 'Issued', 'Fines', 'Reservations', 'Students',
        'Users', 'Publishers', 'Departments', 'QueryHistory', 'SpecialPermissions',
    },
    'Administrator': set(MANAGED_TABLES) | {'SpecialPermissions'},
}

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = Flask(__name__)
# Secret key: read from environment for production; fall back to a random key
# for development (note: random key means sessions are lost on restart).
_secret_key_env = os.environ.get("SECRET_KEY")
if _secret_key_env:
    app.secret_key = _secret_key_env
else:
    app.secret_key = os.urandom(24)
    logger.warning(
        "SECRET_KEY environment variable is not set. "
        "A random key has been generated — all sessions will be lost on restart. "
        "Set SECRET_KEY in production."
    )

# ── Register Blueprints ──────────────────────────────────────────────────────
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(query_bp)
app.register_blueprint(api_bp)
app.register_blueprint(views_bp)

# ── Run DB schema migrations at startup ─────────────────────────────────────
ensure_query_history_schema()


def _normalize_role(role: str) -> str:
    """Normalize database/user-supplied role names to app-facing values."""
    role = (role or '').strip()
    if role == 'Admin':
        return 'Administrator'
    return role


def _password_is_hashed(password_value: str) -> bool:
    """Return True when the stored password already uses Werkzeug hashing."""
    return str(password_value or '').startswith(('pbkdf2:', 'scrypt:', 'bcrypt:', 'argon2:', 'sha256:'))


def _ensure_admin_schema():
    """Apply small compatible schema updates needed by auth/admin features."""
    conn = sqlite3.connect(MAIN_DB)
    try:
        existing_user_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(Users)").fetchall()
        }
        if 'linked_id' not in existing_user_columns:
            conn.execute("ALTER TABLE Users ADD COLUMN linked_id INTEGER")
        if 'full_name' not in existing_user_columns:
            conn.execute("ALTER TABLE Users ADD COLUMN full_name TEXT")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS ActivityLogs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                action TEXT,
                timestamp TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS FailedLoginAttempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                attempt_time TEXT DEFAULT CURRENT_TIMESTAMP,
                failure_reason TEXT,
                blocked BOOLEAN DEFAULT FALSE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS SecuritySettings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting_name TEXT NOT NULL,
                setting_value TEXT NOT NULL,
                description TEXT,
                updated_by TEXT,
                updated_date TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        role_columns = {row[1] for row in conn.execute("PRAGMA table_info(Roles)").fetchall()}
        role_name_col = 'name' if 'name' in role_columns else 'role_name'
        role_level_col = 'level' if 'level' in role_columns else 'role_level'
        role_desc_col = 'description' if 'description' in role_columns else 'role_description'
        faculty_role = conn.execute(
            f"SELECT id FROM Roles WHERE {role_name_col} = ?",
            ('Faculty',),
        ).fetchone()
        if not faculty_role:
            conn.execute(
                f"INSERT INTO Roles ({role_name_col}, {role_level_col}, {role_desc_col}) VALUES (?, ?, ?)",
                ('Faculty', 2, 'Faculty analytics and academic access'),
            )

        permission_columns = {row[1] for row in conn.execute("PRAGMA table_info(Permissions)").fetchall()}
        permission_name_col = 'name' if 'name' in permission_columns else 'permission_name'
        permission_category_col = 'category' if 'category' in permission_columns else 'permission_category'
        permission_desc_col = 'description' if 'description' in permission_columns else 'permission_description'

        required_permissions = [
            (DEFAULT_QUERY_PERMISSION, 'query_control', 'Allow SELECT query execution'),
        ] + [
            (f'table_access:{table}', 'table_access', f'Access to {table} table')
            for table in MANAGED_TABLES + ['SpecialPermissions']
        ]
        for perm_name, category, description in required_permissions:
            if not conn.execute(
                f"SELECT 1 FROM Permissions WHERE {permission_name_col} = ?",
                (perm_name,),
            ).fetchone():
                conn.execute(
                    f"INSERT INTO Permissions ({permission_name_col}, {permission_category_col}, {permission_desc_col}) VALUES (?, ?, ?)",
                    (perm_name, category, description),
                )

        roles = conn.execute(
            f"SELECT id, {role_name_col} FROM Roles"
        ).fetchall()
        role_ids = {row[1]: row[0] for row in roles}
        permission_rows = conn.execute(
            f"SELECT id, {permission_name_col} FROM Permissions"
        ).fetchall()
        permission_ids = {row[1]: row[0] for row in permission_rows}

        default_role_permissions = {
            role: {DEFAULT_QUERY_PERMISSION} | {
                f'table_access:{table}' for table in DEFAULT_ROLE_TABLE_ACCESS.get(role, set())
            }
            for role in SUPPORTED_ROLES
        }
        for role_name, permission_names in default_role_permissions.items():
            role_id = role_ids.get(role_name)
            if not role_id:
                continue
            for permission_name in permission_names:
                permission_id = permission_ids.get(permission_name)
                if not permission_id:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM RolePermissions WHERE role_id = ? AND permission_id = ?",
                    (role_id, permission_id),
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO RolePermissions (role_id, permission_id) VALUES (?, ?)",
                        (role_id, permission_id),
                    )

        users = conn.execute(
            "SELECT id, username, password, role, email, linked_id, full_name FROM Users"
        ).fetchall()
        for user in users:
            stored_password = user[2]
            normalized_role = _normalize_role(user[3])
            update_fields = []
            update_values = []

            if normalized_role != user[3]:
                update_fields.append("role = ?")
                update_values.append(normalized_role)

            if stored_password and not _password_is_hashed(stored_password):
                update_fields.append("password = ?")
                update_values.append(generate_password_hash(stored_password))

            linked_id = user[5]
            if linked_id is None:
                if normalized_role == 'Student':
                    student_row = conn.execute(
                        "SELECT id, name FROM Students WHERE roll_number = ? OR email = ? LIMIT 1",
                        (user[1], user[4]),
                    ).fetchone()
                    if student_row:
                        update_fields.append("linked_id = ?")
                        update_values.append(student_row[0])
                        if not user[6]:
                            update_fields.append("full_name = ?")
                            update_values.append(student_row[1])
                elif normalized_role == 'Faculty':
                    faculty_row = conn.execute(
                        "SELECT id, name FROM Faculty WHERE email = ? OR name = ? LIMIT 1",
                        (user[4], user[1]),
                    ).fetchone()
                    if faculty_row:
                        update_fields.append("linked_id = ?")
                        update_values.append(faculty_row[0])
                        if not user[6]:
                            update_fields.append("full_name = ?")
                            update_values.append(faculty_row[1])

            if update_fields:
                update_values.append(user[0])
                conn.execute(
                    f"UPDATE Users SET {', '.join(update_fields)} WHERE id = ?",
                    tuple(update_values),
                )

        default_settings = {
            'max_query_result_limit': ('100', 'Maximum rows returned per query'),
            'voice_input_enabled': ('true', 'Enable voice input features'),
            'ai_query_enabled': ('true', 'Enable AI query processing'),
            'ollama_sql_enabled': ('true', 'Enable Ollama SQL generation'),
        }
        for setting_name, (setting_value, description) in default_settings.items():
            exists = conn.execute(
                "SELECT id FROM SecuritySettings WHERE setting_name = ? ORDER BY id DESC LIMIT 1",
                (setting_name,),
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO SecuritySettings (setting_name, setting_value, description, updated_by, updated_date) VALUES (?, ?, ?, ?, ?)",
                    (setting_name, setting_value, description, 'system', datetime.now(timezone.utc).isoformat()),
                )

        conn.commit()
    finally:
        conn.close()


_ensure_admin_schema()


def _get_setting(setting_name: str, default_value: str) -> str:
    """Fetch a security/admin setting with a default fallback."""
    try:
        conn = get_db_connection(MAIN_DB)
        row = conn.execute(
            "SELECT setting_value FROM SecuritySettings WHERE setting_name = ? ORDER BY id DESC LIMIT 1",
            (setting_name,),
        ).fetchone()
        conn.close()
        return row['setting_value'] if row else default_value
    except Exception:
        return default_value


def _setting_enabled(setting_name: str, default: bool = True) -> bool:
    """Return a boolean view of a SecuritySettings flag."""
    default_text = 'true' if default else 'false'
    return str(_get_setting(setting_name, default_text)).strip().lower() in ('1', 'true', 'yes', 'on')


def _set_setting(setting_name: str, setting_value: str, description: str, updated_by: str):
    """Insert or update a named admin setting."""
    conn = get_db_connection(MAIN_DB)
    try:
        existing = conn.execute(
            "SELECT id FROM SecuritySettings WHERE setting_name = ? ORDER BY id DESC LIMIT 1",
            (setting_name,),
        ).fetchone()
        now = datetime.now(timezone.utc).isoformat()
        if existing:
            conn.execute(
                "UPDATE SecuritySettings SET setting_value = ?, description = ?, updated_by = ?, updated_date = ? WHERE id = ?",
                (setting_value, description, updated_by, now, existing['id']),
            )
        else:
            conn.execute(
                "INSERT INTO SecuritySettings (setting_name, setting_value, description, updated_by, updated_date) VALUES (?, ?, ?, ?, ?)",
                (setting_name, setting_value, description, updated_by, now),
            )
        conn.commit()
    finally:
        conn.close()


def _record_failed_login(username: str, reason: str):
    """Persist failed login attempts for security monitoring."""
    try:
        conn = get_db_connection(MAIN_DB)
        conn.execute(
            "INSERT INTO FailedLoginAttempts (username, ip_address, user_agent, attempt_time, failure_reason, blocked) VALUES (?, ?, ?, ?, ?, ?)",
            (
                username,
                request.remote_addr,
                request.headers.get('User-Agent'),
                datetime.now(timezone.utc).isoformat(),
                reason,
                False,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[failed_login] logging error: {exc}")


def _log_security_event(event_type: str, details: str, severity: str = 'medium', user_id: str = None):
    """Write security-relevant events to SecurityLog when available."""
    try:
        conn = get_db_connection(MAIN_DB)
        conn.execute(
            """
            INSERT INTO SecurityLog (
                event_type, details, ip_address, user_agent, user_id, session_id, timestamp, severity
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                details,
                request.remote_addr,
                request.headers.get('User-Agent'),
                user_id,
                request.cookies.get(app.config.get('SESSION_COOKIE_NAME', 'session')),
                datetime.now(timezone.utc).isoformat(),
                severity,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[security_log] logging error: {exc}")


def _log_activity(user_id: str, action: str):
    """Store a concise audit trail in ActivityLogs."""
    try:
        conn = get_db_connection(MAIN_DB)
        conn.execute(
            "INSERT INTO ActivityLogs (user_id, action, timestamp) VALUES (?, ?, ?)",
            (user_id, action, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[activity_log] logging error: {exc}")


def _record_query_history(user_id: str, query_text: str, sql_query: str, response_time: float, success: bool, role: str):
    """Persist query history entries for analytics and monitoring."""
    try:
        conn = get_db_connection(MAIN_DB)
        conn.execute(
            "INSERT INTO QueryHistory (user_id, query, sql_query, response_time, timestamp, success, role) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                query_text,
                sql_query,
                response_time,
                datetime.now(timezone.utc).isoformat(),
                1 if success else 0,
                role,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[query_history] logging error: {exc}")


def _record_session_login(user_id: str, role: str):
    """Record a successful login session."""
    try:
        conn = get_db_connection(MAIN_DB)
        conn.execute(
            """
            INSERT INTO SessionLog (user_id, user_role, session_id, login_time, ip_address, user_agent, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                role,
                request.cookies.get(app.config.get('SESSION_COOKIE_NAME', 'session'), 'unknown'),
                datetime.now(timezone.utc).isoformat(),
                request.remote_addr or 'unknown',
                request.headers.get('User-Agent', 'unknown'),
                'Active',
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[session_log] logging error: {exc}")


def _record_session_logout(user_id: str):
    """Mark any active sessions for the user as ended."""
    try:
        conn = get_db_connection(MAIN_DB)
        conn.execute(
            """
            UPDATE SessionLog
            SET logout_time = ?, status = 'Ended'
            WHERE user_id = ? AND status = 'Active'
            """,
            (datetime.now(timezone.utc).isoformat(), user_id),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[session_logout] logging error: {exc}")


def _get_role_metadata(conn):
    """Return role rows in a schema-tolerant format."""
    role_columns = {row[1] for row in conn.execute("PRAGMA table_info(Roles)").fetchall()}
    role_name_col = 'name' if 'name' in role_columns else 'role_name'
    role_level_col = 'level' if 'level' in role_columns else 'role_level'
    role_desc_col = 'description' if 'description' in role_columns else 'role_description'
    rows = conn.execute(
        f"SELECT id, {role_name_col} AS role_name, {role_level_col} AS role_level, {role_desc_col} AS role_description FROM Roles ORDER BY {role_level_col}, {role_name_col}"
    ).fetchall()
    return rows, role_name_col


def _get_permission_metadata(conn):
    """Return permission rows in a schema-tolerant format."""
    permission_columns = {row[1] for row in conn.execute("PRAGMA table_info(Permissions)").fetchall()}
    permission_name_col = 'name' if 'name' in permission_columns else 'permission_name'
    permission_category_col = 'category' if 'category' in permission_columns else 'permission_category'
    permission_desc_col = 'description' if 'description' in permission_columns else 'permission_description'
    rows = conn.execute(
        f"SELECT id, {permission_name_col} AS permission_name, {permission_category_col} AS permission_category, {permission_desc_col} AS permission_description FROM Permissions ORDER BY {permission_category_col}, {permission_name_col}"
    ).fetchall()
    return rows


def _sync_user_role_assignment(conn, username: str, role: str, assigned_by: str):
    """Keep the UserRoles table aligned with the Users table."""
    roles, _ = _get_role_metadata(conn)
    role_map = {row['role_name']: row['id'] for row in roles}
    role_id = role_map.get(role)
    if not role_id:
        return
    existing = conn.execute(
        "SELECT id FROM UserRoles WHERE user_id = ? AND status = 'Active' ORDER BY id DESC LIMIT 1",
        (username,),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE UserRoles SET role_id = ?, assigned_by = ?, assigned_date = ? WHERE id = ?",
            (role_id, assigned_by, datetime.now(timezone.utc).isoformat(), existing['id']),
        )
    else:
        conn.execute(
            """
            INSERT INTO UserRoles (user_id, user_type, role_id, assigned_date, assigned_by, status)
            VALUES (?, ?, ?, ?, ?, 'Active')
            """,
            (username, 'user', role_id, datetime.now(timezone.utc).isoformat(), assigned_by),
        )


def _resolve_linked_profile(conn, role: str, linked_id: int, username: str, email: str, full_name: str):
    """Return best-effort name/email details from linked profile tables."""
    resolved_name = full_name or username
    resolved_email = email
    if role == 'Student' and linked_id:
        row = conn.execute(
            "SELECT name, email FROM Students WHERE id = ?",
            (linked_id,),
        ).fetchone()
        if row:
            resolved_name = row['name'] or resolved_name
            resolved_email = row['email'] or resolved_email
    elif role == 'Faculty' and linked_id:
        row = conn.execute(
            "SELECT name, email FROM Faculty WHERE id = ?",
            (linked_id,),
        ).fetchone()
        if row:
            resolved_name = row['name'] or resolved_name
            resolved_email = row['email'] or resolved_email
    return resolved_name, resolved_email


def _save_linked_record(conn, role: str, form_data, username: str, email: str, existing_linked_id: int = None) -> int:
    """Insert or update Student/Faculty profile data and return linked_id."""
    role = _normalize_role(role)
    if role == 'Student':
        payload = (
            (form_data.get('name') or username).strip(),
            (form_data.get('branch') or 'General').strip(),
            (form_data.get('year') or '1').strip(),
            email,
            (form_data.get('phone') or '').strip(),
        )
        if existing_linked_id:
            conn.execute(
                """
                UPDATE Students
                SET roll_number = ?, name = ?, branch = ?, year = ?, email = ?, phone = ?
                WHERE id = ?
                """,
                (username, payload[0], payload[1], payload[2], payload[3], payload[4], existing_linked_id),
            )
            return existing_linked_id
        cursor = conn.execute(
            """
            INSERT INTO Students (roll_number, name, branch, year, email, phone, role)
            VALUES (?, ?, ?, ?, ?, ?, 'Student')
            """,
            (username, payload[0], payload[1], payload[2], payload[3], payload[4]),
        )
        return cursor.lastrowid

    if role == 'Faculty':
        payload = (
            (form_data.get('name') or username).strip(),
            (form_data.get('department') or 'General').strip(),
            (form_data.get('designation') or 'Faculty').strip(),
            email,
            (form_data.get('phone') or '').strip(),
            (form_data.get('specialization') or 'Library Systems').strip(),
        )
        if existing_linked_id:
            conn.execute(
                """
                UPDATE Faculty
                SET name = ?, department = ?, designation = ?, email = ?, phone = ?, specialization = ?
                WHERE id = ?
                """,
                (payload[0], payload[1], payload[2], payload[3], payload[4], payload[5], existing_linked_id),
            )
            return existing_linked_id
        cursor = conn.execute(
            """
            INSERT INTO Faculty (name, department, designation, email, phone, specialization)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        return cursor.lastrowid

    return None


def _delete_linked_record(conn, role: str, linked_id: int):
    """Delete Student/Faculty records when the linked user is deleted."""
    if not linked_id:
        return
    if role == 'Student':
        conn.execute("DELETE FROM Students WHERE id = ?", (linked_id,))
    elif role == 'Faculty':
        conn.execute("DELETE FROM Faculty WHERE id = ?", (linked_id,))


def _apply_query_result_limit(sql_query: str) -> str:
    """Append or tighten the configured LIMIT clause for SELECT queries."""
    max_rows = max(1, int(_get_setting('max_query_result_limit', '100')))
    limit_match = re.search(r'\bLIMIT\s+(\d+)\b', sql_query, re.IGNORECASE)
    if limit_match:
        current_limit = int(limit_match.group(1))
        if current_limit > max_rows:
            return re.sub(r'\bLIMIT\s+\d+\b', f'LIMIT {max_rows}', sql_query, flags=re.IGNORECASE)
        return sql_query
    return sql_query.rstrip().rstrip(';') + f' LIMIT {max_rows}'


def _password_meets_policy(password: str) -> bool:
    """Require at least 8 chars with one letter and one digit for new passwords."""
    password = password or ''
    return (
        len(password) >= 8
        and re.search(r'[A-Za-z]', password) is not None
        and re.search(r'\d', password) is not None
    )


def _load_admin_dashboard_context():
    """Collect data for the consolidated admin control panel."""
    conn = get_db_connection(MAIN_DB)
    try:
        stats = {
            'total_users': conn.execute("SELECT COUNT(*) AS cnt FROM Users").fetchone()['cnt'],
            'active_sessions': conn.execute(
                "SELECT COUNT(*) AS cnt FROM SessionLog WHERE status = 'Active' AND (logout_time IS NULL OR logout_time = '')"
            ).fetchone()['cnt'],
            'failed_queries': conn.execute(
                "SELECT COUNT(*) AS cnt FROM QueryHistory WHERE success = 0"
            ).fetchone()['cnt'],
            'blocked_queries': conn.execute(
                "SELECT COUNT(*) AS cnt FROM SecurityLog WHERE event_type IN ('blocked_query', 'unauthorized_access', 'failed_query')"
            ).fetchone()['cnt'],
            'security_blocked_queries': conn.execute(
                "SELECT COUNT(*) AS cnt FROM SecurityLog WHERE event_type = 'blocked_query'"
            ).fetchone()['cnt'],
        }

        most_active_users = [
            dict(row) for row in conn.execute(
                "SELECT user_id, COUNT(*) AS count FROM QueryHistory GROUP BY user_id ORDER BY count DESC LIMIT 5"
            ).fetchall()
        ]
        users = []
        for row in conn.execute(
            "SELECT id, username, email, role, linked_id, full_name FROM Users ORDER BY username"
        ).fetchall():
            resolved_name, resolved_email = _resolve_linked_profile(
                conn, _normalize_role(row['role']), row['linked_id'], row['username'], row['email'], row['full_name']
            )
            users.append({
                'id': row['id'],
                'username': row['username'],
                'full_name': resolved_name,
                'email': resolved_email,
                'role': _normalize_role(row['role']),
                'linked_id': row['linked_id'],
            })

        roles, _ = _get_role_metadata(conn)
        permissions = _get_permission_metadata(conn)
        role_permission_rows = conn.execute(
            "SELECT role_id, permission_id FROM RolePermissions"
        ).fetchall()
        assigned_map = {(row['role_id'], row['permission_id']) for row in role_permission_rows}

        permissions_by_category = {}
        for permission in permissions:
            category = permission['permission_category'] or 'general'
            permissions_by_category.setdefault(category, []).append(dict(permission))

        role_permissions = []
        for role in roles:
            assigned_names = [
                permission['permission_name']
                for permission in permissions
                if (role['id'], permission['id']) in assigned_map
            ]
            role_permissions.append({
                'id': role['id'],
                'name': _normalize_role(role['role_name']),
                'level': role['role_level'],
                'description': role['role_description'],
                'assigned_permissions': assigned_names,
                'table_permissions': sorted(
                    perm.split(':', 1)[1]
                    for perm in assigned_names
                    if perm.startswith('table_access:')
                ),
                'query_enabled': DEFAULT_QUERY_PERMISSION in assigned_names,
            })

        activity_logs = [
            dict(row) for row in conn.execute(
                "SELECT id, user_id, action, timestamp FROM ActivityLogs ORDER BY timestamp DESC LIMIT 50"
            ).fetchall()
        ]
        security_events = [
            dict(row) for row in conn.execute(
                """
                SELECT event_type, details, timestamp, severity, user_id
                FROM SecurityLog
                ORDER BY timestamp DESC
                LIMIT 25
                """
            ).fetchall()
        ]
        failed_logins = [
            dict(row) for row in conn.execute(
                """
                SELECT username, ip_address, attempt_time, failure_reason, blocked
                FROM FailedLoginAttempts
                ORDER BY attempt_time DESC
                LIMIT 25
                """
            ).fetchall()
        ]
        llm_stats = {
            'success_count': conn.execute(
                "SELECT COUNT(*) AS cnt FROM ActivityLogs WHERE action = 'llm_query_success'"
            ).fetchone()['cnt'],
            'failure_count': conn.execute(
                "SELECT COUNT(*) AS cnt FROM ActivityLogs WHERE action = 'llm_query_failure'"
            ).fetchone()['cnt'],
        }
        settings = {
            'max_query_result_limit': _get_setting('max_query_result_limit', '100'),
            'voice_input_enabled': _setting_enabled('voice_input_enabled', True),
            'ai_query_enabled': _setting_enabled('ai_query_enabled', True),
            'ollama_sql_enabled': _setting_enabled('ollama_sql_enabled', True),
        }
        return {
            'stats': stats,
            'users': users,
            'roles': [dict(row) for row in roles],
            'permissions_by_category': permissions_by_category,
            'role_permissions': role_permissions,
            'activity_logs': activity_logs,
            'security_events': security_events,
            'failed_logins': failed_logins,
            'settings': settings,
            'llm_stats': llm_stats,
            'most_active_users': most_active_users,
        }
    finally:
        conn.close()

# ── Jinja2 custom filters ────────────────────────────────────────────────────
@app.template_filter("days_overdue")
def days_overdue_filter(due_date_str):
    """Return the number of days a book is overdue (0 if not overdue or invalid)."""
    if not due_date_str:
        return 0
    try:
        due = datetime.strptime(str(due_date_str)[:10], "%Y-%m-%d").date()
        delta = (datetime.now().date() - due).days
        return max(delta, 0)
    except Exception:
        return 0


# ── Security headers on every response ──────────────────────────────────────
if _SECURITY_HEADERS_AVAILABLE:
    @app.after_request
    def add_security_headers(response):
        """Attach HTTP security headers without breaking voice / CSRF-free flow."""
        return apply_security_headers(response)


# ---------------------------------------------------------------------------
# Main dashboard (index) – kept here so url_for('index') resolves correctly
# ---------------------------------------------------------------------------

    if 'how much do i owe' in q_lower:
        return (
            f"SELECT s.name, SUM(f.fine_amount) as total_balance "
            f"FROM Students s LEFT JOIN Fines f ON s.id = f.student_id "
            f"WHERE s.id = {sid} AND f.status = 'Unpaid' GROUP BY s.id, s.name"
        )

    if 'when are my' in q_lower and 'due' in q_lower:
        return _books_base + " AND i.return_date IS NULL ORDER BY i.due_date ASC"

    return sql_query


def _fallback_columns(sql_query: str) -> list:
    """Return a sensible fallback column list when a query returns no rows."""
    sq = sql_query.lower()
    if 'books' in sq:
        return ['id', 'title', 'author', 'category', 'total_copies', 'available_copies']
    if 'students' in sq:
        return ['id', 'roll_number', 'name', 'branch', 'year', 'email', 'gpa']
    if 'faculty' in sq:
        return ['id', 'name', 'department', 'designation', 'email']
    if 'fines' in sq:
        return ['id', 'student_id', 'fine_amount', 'fine_type', 'status', 'issue_date']
    if 'issued' in sq:
        return ['id', 'student_id', 'book_id', 'issue_date', 'due_date', 'return_date']
    return ['id', 'name']


# Authentication
@app.route('/register', methods=['GET', 'POST'])
def register():
    """Register a new user with role-aware profile creation."""
    if request.method == 'GET':
        return render_template('register.html')

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    role = _normalize_role(request.form.get('role', 'Student'))
    full_name = request.form.get('name', '').strip() or username
    email = request.form.get('email', '').strip() or f"{username.lower()}@library.local"

    if role not in REGISTRATION_ROLES:
        flash('Please choose a valid registration role.', 'error')
        return render_template('register.html')
    if not username or not password:
        flash('Username and password are required.', 'error')
        return render_template('register.html')
    if not _password_meets_policy(password):
        flash('Password must be at least 8 characters long and include both letters and numbers.', 'error')
        return render_template('register.html')
    if '@' not in email:
        flash('Please enter a valid email address.', 'error')
        return render_template('register.html')

    conn = get_db_connection(MAIN_DB)
    try:
        existing_user = conn.execute(
            "SELECT id FROM Users WHERE username = ?",
            (username,),
        ).fetchone()
        if existing_user:
            flash('That username is already registered.', 'error')
            return render_template('register.html')

        linked_id = _save_linked_record(conn, role, request.form, username, email)
        user_cursor = conn.execute(
            """
            INSERT INTO Users (username, password, role, email, linked_id, full_name)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                generate_password_hash(password),
                role,
                email,
                linked_id,
                full_name,
            ),
        )
        _sync_user_role_assignment(conn, username, role, username)
        conn.commit()
        _log_activity(username, f'user_registered:{role}')
        flash('Registration successful. Please sign in.', 'success')
        return redirect(url_for('login'))
    except sqlite3.IntegrityError:
        conn.rollback()
        flash('That username is already registered.', 'error')
        return render_template('register.html')
    except Exception as exc:
        conn.rollback()
        print(f"[register] error: {exc}")
        flash('Registration failed. Please try again.', 'error')
        return render_template('register.html')
    finally:
        conn.close()


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    if request.method == 'GET':
        return render_template('login.html')
    
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    
    if not username or not password:
        flash('Please enter username and password', 'error')
        return render_template('login.html')

    try:
        conn = get_db_connection(MAIN_DB)
        user = conn.execute(
            """
            SELECT id, username, password, role, linked_id, email
            FROM Users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()

        if not user:
            _record_failed_login(username, 'unknown_username')
            _log_security_event('login_failure', f'Unknown username: {username}', 'medium', username)
            conn.close()
            flash('Invalid username or password', 'error')
            return render_template('login.html')

        stored_password = user['password']
        valid_password = check_password_hash(stored_password, password)
        if not valid_password:
            _record_failed_login(username, 'invalid_password')
            _log_security_event('login_failure', f'Invalid password for {username}', 'medium', username)
            conn.close()
            flash('Invalid username or password', 'error')
            return render_template('login.html')

        session['user_id'] = user['username']
        session['role'] = _normalize_role(user['role'])
        session['student_id'] = user['linked_id'] if _normalize_role(user['role']) == 'Student' else None
        _record_session_login(session['user_id'], session['role'])
        _log_activity(session['user_id'], 'login')
        _log_security_event('login_success', f"Successful login for {session['user_id']}", 'low', session['user_id'])
        conn.close()
    except Exception as exc:
        print(f"[login] error: {exc}")
        flash('Invalid username or password', 'error')
        return render_template('login.html')

    flash(f'Welcome, {session["role"]}!', 'success')
    # All roles land on the main query interface; role-specific dashboards are
    # accessible as separate sections from within the query interface.
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    """Logout user"""
    if session.get('user_id'):
        _record_session_logout(session['user_id'])
        _log_activity(session['user_id'], 'logout')
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/')
def index():
    """Main query interface with embedded role-specific dashboard widgets."""
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    user_id = session["user_id"]
    user_role = session.get("role", "Student")
    student_id = session.get("student_id")

    user_info = {"username": user_id, "role": user_role, "permissions": []}

    dashboard_data = {}
    try:
        conn = get_db_connection(MAIN_DB)

        if user_role == "Student" and student_id:
            student_info = conn.execute(
                "SELECT * FROM Students WHERE id = ?", (student_id,)
            ).fetchone()
            current_books = conn.execute(
                """SELECT i.*, b.title, b.author FROM Issued i
                   JOIN Books b ON i.book_id = b.id
                   WHERE i.student_id = ? AND i.return_date IS NULL
                   ORDER BY i.due_date ASC LIMIT 5""",
                (student_id,),
            ).fetchall()
            overdue_books = conn.execute(
                """SELECT i.*, b.title, b.author FROM Issued i
                   JOIN Books b ON i.book_id = b.id
                   WHERE i.student_id = ? AND i.return_date IS NULL
                   AND i.due_date < date('now')""",
                (student_id,),
            ).fetchall()
            unpaid_fines = conn.execute(
                "SELECT * FROM Fines WHERE student_id = ? AND status = 'Unpaid'",
                (student_id,),
            ).fetchall()
            dashboard_data = {
                "student_info": dict(student_info) if student_info else {},
                "current_books": [dict(r) for r in current_books],
                "overdue_count": len(overdue_books),
                "unpaid_fines": len(unpaid_fines),
            }

        elif user_role in ("Librarian", "Faculty", "Administrator"):
            total_books = conn.execute(
                "SELECT COUNT(*) as cnt FROM Books"
            ).fetchone()["cnt"]
            total_students = conn.execute(
                "SELECT COUNT(*) as cnt FROM Students"
            ).fetchone()["cnt"]
            active_issues = conn.execute(
                "SELECT COUNT(*) as cnt FROM Issued WHERE return_date IS NULL"
            ).fetchone()["cnt"]
            unpaid_fines_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM Fines WHERE status = 'Unpaid'"
            ).fetchone()["cnt"]
            dashboard_data = {
                "total_books": total_books,
                "total_students": total_students,
                "active_issues": active_issues,
                "unpaid_fines": unpaid_fines_count,
            }

        conn.close()
    except Exception as exc:
        logger.error("index dashboard data fetch error: %s", exc)

    return render_template(
        "index.html",
        user=user_info.get("username", user_id),
        role=user_role,
        user=user_id,
    )


@app.route('/faculty_dashboard')
def faculty_dashboard_route():
    """Faculty dashboard – Faculty and Librarian roles."""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    role = session.get('role')
    print("Route accessed:", request.path)
    print("User role:", role)

    if role not in ('Faculty', 'Librarian', 'Administrator'):
        return "Access Denied", 403

    user_id = session['user_id']

    # Try to look up faculty info (match by email == user_id or first faculty)
    faculty_info = None
    try:
        conn = get_db_connection(MAIN_DB)
        faculty_info = conn.execute(
            "SELECT * FROM Faculty WHERE email = ? OR name = ? LIMIT 1",
            (user_id, user_id)
        ).fetchone()
        if faculty_info is None:
            faculty_info = conn.execute("SELECT * FROM Faculty LIMIT 1").fetchone()

        total_books = conn.execute("SELECT COUNT(*) as cnt FROM Books").fetchone()['cnt']
        total_students = conn.execute("SELECT COUNT(*) as cnt FROM Students").fetchone()['cnt']
        active_issues = conn.execute(
            "SELECT COUNT(*) as cnt FROM Issued WHERE return_date IS NULL"
        ).fetchone()['cnt']
        unpaid_fines_cnt = conn.execute(
            "SELECT COUNT(*) as cnt FROM Fines WHERE status = 'Unpaid'"
        ).fetchone()['cnt']
        recent_issues = conn.execute(
            """SELECT i.*, b.title, b.author, s.name as student_name
               FROM Issued i
               JOIN Books b ON i.book_id = b.id
               JOIN Students s ON i.student_id = s.id
               ORDER BY i.issue_date DESC LIMIT 10"""
        ).fetchall()
        conn.close()
        stats = {
            'total_books': total_books,
            'total_students': total_students,
            'active_issues': active_issues,
            'unpaid_fines': unpaid_fines_cnt,
        }
    except Exception as e:
        print(f"[faculty_dashboard] DB error: {e}")
        recent_issues = []
        stats = {}

    return render_template(
        'faculty_dashboard.html',
        role=role,
        user=user_id,
        faculty_info=faculty_info,
        stats=stats,
        recent_issues=recent_issues,
    )


@app.route('/librarian_dashboard')
def librarian_dashboard_route():
    """Librarian / Faculty dashboard"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    role = session.get('role')
    print("Route accessed:", request.path)
    print("User role:", role)

    if role not in ('Librarian', 'Faculty', 'Administrator'):
        return "Access Denied", 403

    user_id = session['user_id']

    try:
        conn = get_db_connection(MAIN_DB)
        total_books = conn.execute(
            "SELECT COUNT(*) as cnt FROM Books"
        ).fetchone()['cnt']
        total_students = conn.execute(
            "SELECT COUNT(*) as cnt FROM Students"
        ).fetchone()['cnt']
        active_issues = conn.execute(
            "SELECT COUNT(*) as cnt FROM Issued WHERE return_date IS NULL"
        ).fetchone()['cnt']
        unpaid_fines = conn.execute(
            "SELECT COUNT(*) as cnt FROM Fines WHERE status = 'Unpaid'"
        ).fetchone()['cnt']
        recent_issues = conn.execute(
            """SELECT i.*, b.title, b.author, s.name as student_name
               FROM Issued i
               JOIN Books b ON i.book_id = b.id
               JOIN Students s ON i.student_id = s.id
               ORDER BY i.issue_date DESC LIMIT 10"""
        ).fetchall()
        conn.close()
        stats = {
            'total_books': total_books,
            'total_students': total_students,
            'active_issues': active_issues,
            'unpaid_fines': unpaid_fines,
        }
    except Exception as e:
        print(f"[librarian_dashboard] DB error: {e}")
        recent_issues = []
        stats = {}

    return render_template(
        'librarian_dashboard.html',
        role=role,
        user=user_id,
        stats=stats,
        recent_issues=recent_issues,
    )


@app.route('/admin_dashboard')
def admin_dashboard_route():
    """Administrator dashboard"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'Administrator':
        return "Access Denied", 403

    dashboard_context = _load_admin_dashboard_context()
    return render_template(
        'admin_dashboard.html',
        role=session.get('role', 'Administrator'),
        user=session['user_id'],
        active_section=request.args.get('section', 'overview'),
        **dashboard_context,
    )

@app.route('/query', methods=['POST'])
def query():
    """
    NL-to-SQL query pipeline:
      1. Spell correction
      2. Context follow-up detection & query rewrite
      3. Clarification detection (returns options if vague & no choice given)
      4. Apply clarification choice (if provided)
      5. Vocabulary preprocessing (append schema hints)
      6. SQL generation via Ollama
      7. Student-specific SQL rewriting / row-level filtering
      8. SQL safety gate (SELECT-only, no DDL/write keywords)
      9. RBAC table-access validation
      10. Execute & return results
    """
    print("🔍 Query received - Processing request")

    if 'user_id' not in session:
        print("❌ User not logged in")
        return jsonify({'error': 'Not logged in'}), 401

    _query_start = time.time()
    user_query = ''
    sql_query = ''
    user_role = session.get('role', 'Student')
    try:
        data = request.get_json()
        user_query = data.get('query', '').strip()
        # Optional: clarification choice sent back from the frontend
        clarification_choice = data.get('clarification_choice', '').strip()
        print(f"📝 Query text: {user_query}")

        student_id = session.get('student_id')
        print(f"👤 User role: {user_role}, Student ID: {student_id}")

        if not user_query:
            print("❌ No query provided")
            return jsonify({'error': 'No query provided'}), 400

        if not _setting_enabled('ai_query_enabled', True):
            _record_query_history(session.get('user_id', ''), user_query, '', time.time() - _query_start, False, user_role)
            _log_activity(session.get('user_id', ''), 'ai_query_disabled')
            return jsonify({'error': 'AI query processing is currently disabled by the administrator.'}), 503

        # ── Step 1: Spell correction ──────────────────────────────────────
        corrected_query = correct_query(user_query)
        if corrected_query != user_query:
            print("[SPELL FIX]", corrected_query)
        user_query = corrected_query

        # ── Step 2: Context follow-up detection & rewrite ─────────────────
        print("[CONTEXT] previous query:", session.get("last_query"))
        if is_followup(user_query):
            last_q = get_last_query(session)
            if last_q:
                rewritten_query = rewrite_followup(user_query, last_q)
                print("[CONTEXT REWRITE]", rewritten_query)
                user_query = rewritten_query

        # ── Step 3 & 4: Clarification chatbot ────────────────────────────
        if clarification_choice:
            # User selected an option – expand into specific NL query
            user_query = apply_clarification_choice(user_query, clarification_choice)
            print(f"🗣️ Clarification applied: {user_query}")
        else:
            if is_ambiguous_query(user_query):
                clarif = get_clarification(user_query)
                print(f"❓ Ambiguous query – returning clarification options")
                return jsonify({
                    'needs_clarification': True,
                    'clarification': clarif
                })

        # ── Step 5: Vocabulary preprocessing ─────────────────────────────
        augmented_query = preprocess_query(user_query, MAIN_DB)
        if augmented_query != user_query:
            print("[VOCABULARY HINTS]", augmented_query)

        print("🔗 Connecting to database...")
        conn = get_db_connection(MAIN_DB)

        print("🤖 Generating SQL query...")
        if not _setting_enabled('ollama_sql_enabled', True):
            _record_query_history(session.get('user_id', ''), user_query, '', time.time() - _query_start, False, user_role)
            _log_activity(session.get('user_id', ''), 'ollama_disabled')
            return jsonify({'error': 'Ollama SQL generation is currently disabled by the administrator.'}), 503
        try:
            sql_query = generate_sql(augmented_query)
            _log_activity(session.get('user_id', ''), 'llm_query_success')
        except Exception as llm_error:
            print(f"❌ LLM generation failed: {llm_error}")
            _record_query_history(session.get('user_id', ''), user_query, '', time.time() - _query_start, False, user_role)
            _log_activity(session.get('user_id', ''), 'llm_query_failure')
            _log_security_event('failed_query', f"LLM failure for {session.get('user_id', '')}: {llm_error}", 'medium', session.get('user_id'))
            return jsonify({'error': 'AI SQL generation is temporarily unavailable. Please try again later.'}), 503
        # Defensive guard: generate_sql should always return non-empty, but
        # fall back to a safe default if it somehow doesn't.
        if not sql_query or not sql_query.strip():
            print("[FALLBACK SQL] generate_sql returned empty, using default")
            sql_query = "SELECT * FROM Books LIMIT 10"
        print(f"⚙️ Generated SQL: {sql_query}")

        # Replace student ID placeholders emitted by the SQL generator
        if user_role == 'Student' and student_id:
            sql_query = sql_query.replace('[CURRENT_STUDENT_ID]', str(student_id))

        # ── Step 7: Student-specific SQL rewriting ────────────────────────
        print("Role:", session.get("role"))
        print("Student Filter Applied:", session.get("student_id"))
        if user_role == 'Student' and student_id:
            sql_query = _apply_student_filters(user_query, sql_query, student_id)

        # ── Step 8: Security layer (injection check + table access + isolation)
        if SECURITY_LAYER_AVAILABLE:
            allowed, sql_query, sec_error = security_validate_sql(
                sql_query, user_role, student_id
            )
            if not allowed:
                print(f"🚫 Security layer blocked query: {sec_error}")
                _record_query_history(session.get('user_id', ''), user_query, sql_query, time.time() - _query_start, False, user_role)
                _log_activity(session.get('user_id', ''), 'blocked_query')
                _log_security_event('blocked_query', f"Security layer blocked query: {sec_error} | SQL: {sql_query}", 'high', session.get('user_id'))
                return jsonify({
                    'success': False,
                    'error': 'Query blocked by security layer',
                }), 400

        # ── Step 9: SQL safety gate ───────────────────────────────────────
        safe, reason = _is_safe_sql(sql_query)
        if not safe:
            print(f"🚫 SQL blocked by safety gate: {reason}")
            _record_query_history(session.get('user_id', ''), user_query, sql_query, time.time() - _query_start, False, user_role)
            _log_activity(session.get('user_id', ''), 'blocked_query')
            _log_security_event('blocked_query', f"Safety gate blocked query: {reason} | SQL: {sql_query}", 'high', session.get('user_id'))
            return jsonify({'error': f'Query not permitted: {reason}'}), 400

        # ── Step 10: RBAC table-access validation ─────────────────────────
        if RBAC_AVAILABLE:
            user_id_for_rbac = session.get('user_id', '')
            ok, msg = rbac.validate_query_access(user_id_for_rbac, sql_query)
            if not ok:
                print(f"🚫 RBAC denied: {msg}")
                _record_query_history(user_id_for_rbac, user_query, sql_query, time.time() - _query_start, False, user_role)
                _log_activity(user_id_for_rbac, 'blocked_query')
                _log_security_event('blocked_query', f"RBAC denied query: {msg} | SQL: {sql_query}", 'high', user_id_for_rbac)
                return jsonify({'error': f'Access denied: {msg}'}), 403

            # Apply additional row-level filter for students via RBAC helper
            if user_role == 'Student' and student_id:
                sql_query = apply_row_level_filter(str(student_id), sql_query)

        sql_query = _apply_query_result_limit(sql_query)

        print(f"[EXECUTING SQL] {sql_query}")
        results = conn.execute(sql_query).fetchall()
        conn.close()

        rows = [dict(row) for row in results]

        # Store context for follow-up queries.
        # We store the (possibly rewritten) query so that chained follow-ups
        # continue to reference the correct subject (e.g. "books").
        session["last_query"] = user_query
        session["last_sql"] = sql_query

        # Extract columns dynamically
        if rows:
            columns = list(rows[0].keys())
        else:
            columns = _fallback_columns(sql_query)

        print(f"📊 Returning {len(rows)} rows with columns: {columns}")

        # ── Save context for follow-up queries ────────────────────────────
        save_context(session, user_query, sql_query)
        response_time = time.time() - _query_start
        _record_query_history(session.get('user_id', ''), user_query, sql_query, response_time, True, user_role)
        _log_activity(session.get('user_id', ''), 'query_executed')

        return jsonify({
            'success':    True,
            'data':       rows,
            'columns':    columns,
            'sql':        sql_query,
            'database':   MAIN_DB,
            'user_role':  user_role,
            'student_id': student_id,
        })

    except Exception as e:
        print(f"❌ Query execution failed: {str(e)}")
        import traceback
        traceback.print_exc()
        _record_query_history(session.get('user_id', ''), user_query, sql_query, time.time() - _query_start, False, user_role)
        _log_activity(session.get('user_id', ''), 'failed_query')
        _log_security_event('failed_query', str(e), 'medium', session.get('user_id'))
        return jsonify({'error': f'Query execution failed: {str(e)}'}), 500

# API endpoints
@app.route('/api/user-info')
def api_user_info():
    """Get user information – fixed to read from session (no NameError)."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    user_id_val = session.get('user_id', '')
    user_role_val = session.get('role', 'Student')
    permissions = []

    if RBAC_AVAILABLE:
        try:
            perms = rbac.get_user_permissions(user_id_val)
            permissions = list(perms)[:20]  # cap for JSON size
        except Exception:
            pass

    return jsonify({
        'username':   user_id_val,
        'role':       user_role_val,
        'student_id': session.get('student_id'),
        'permissions': permissions,
    })

@app.route('/api/ui-config')
def api_ui_config():
    """Get UI configuration"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    features = ['multi_db']
    if _setting_enabled('ai_query_enabled', True):
        features.append('text_to_sql')
    if _setting_enabled('voice_input_enabled', True):
        features.append('voice_input')

    return jsonify({
        'role': session.get('role', 'Student'),
        'features': features
    })

@app.route('/api/dashboard-data')
def api_dashboard_data():
    """Get dashboard data"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    return jsonify({
        'stats': {
            'queries_today': 12,
            'active_users': 3,
            'database_size': '2.4GB',
            'last_update': '2024-02-27 19:30:00'
        },
        'recent_queries': [
            'show all books',
            'list students',
            'check fines'
        ]
    })


@app.route('/api/vocabulary')
def api_vocabulary():
    """
    Debug endpoint – returns vocabulary metadata and a sample.
    GET /api/vocabulary?db=main|archive&rebuild=1
    """
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    db_key = request.args.get('db', 'main')
    db_path = ARCHIVE_DB if db_key == 'archive' else MAIN_DB
    force = request.args.get('rebuild', '0') == '1'

    try:
        from domain_vocabulary import get_vocabulary_sample, invalidate_cache
        if force:
            invalidate_cache(db_path)
        sample = get_vocabulary_sample(db_path)
        return jsonify({'success': True, 'vocabulary': sample})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/query_analytics')
def api_query_analytics():
    """Query analytics – Administrator only.

    Returns JSON with:
      - queries_today      int
      - most_common        list of {query, count}
      - top_users          list of {user_id, count}
      - avg_execution_time float (seconds)
      - queries_per_day    list of {date, count}
    """
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if session.get('role') != 'Administrator':
        return jsonify({'error': 'Access denied'}), 403

    try:
        conn = get_db_connection(MAIN_DB)
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        queries_today = conn.execute(
            "SELECT COUNT(*) as cnt FROM QueryHistory WHERE timestamp LIKE ?",
            (today + '%',),
        ).fetchone()['cnt']

        most_common = [
            dict(r) for r in conn.execute(
                "SELECT query, COUNT(*) as count FROM QueryHistory "
                "GROUP BY query ORDER BY count DESC LIMIT 10"
            ).fetchall()
        ]

        top_users = [
            dict(r) for r in conn.execute(
                "SELECT user_id, COUNT(*) as count FROM QueryHistory "
                "GROUP BY user_id ORDER BY count DESC LIMIT 10"
            ).fetchall()
        ]

        avg_row = conn.execute(
            "SELECT AVG(response_time) as avg_time FROM QueryHistory "
            "WHERE response_time IS NOT NULL"
        ).fetchone()
        avg_execution_time = round(avg_row['avg_time'] or 0, 4)

        queries_per_day = [
            dict(r) for r in conn.execute(
                "SELECT substr(timestamp, 1, 10) as date, COUNT(*) as count "
                "FROM QueryHistory GROUP BY date ORDER BY date DESC LIMIT 30"
            ).fetchall()
        ]

        conn.close()
        return jsonify({
            'success': True,
            'queries_today': queries_today,
            'most_common': most_common,
            'top_users': top_users,
            'avg_execution_time': avg_execution_time,
            'queries_per_day': queries_per_day,
        })
    except Exception as e:
        print(f"[api_query_analytics] error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/query', methods=['GET'])
def query_page():
    """Redirect GET /query to main dashboard (query console is on the main page)."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('index'))


@app.route('/analytics')
def analytics():
    """Analytics view – admin only."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'Administrator':
        return "Access Denied", 403
    user_role = session.get('role', 'Student')
    user_id = session['user_id']

    try:
        conn = get_db_connection(MAIN_DB)
        books_per_category = conn.execute(
            "SELECT category, COUNT(*) as count FROM Books GROUP BY category ORDER BY count DESC"
        ).fetchall()
        issues_per_month = conn.execute(
            "SELECT strftime('%Y-%m', issue_date) as month, COUNT(*) as count "
            "FROM Issued GROUP BY month ORDER BY month DESC LIMIT 12"
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"[analytics] DB error: {e}")
        books_per_category = []
        issues_per_month = []

    return render_template('analytics.html',
                           user=user_id,
                           role=user_role,
                           books_per_category=[dict(r) for r in books_per_category],
                           issues_per_month=[dict(r) for r in issues_per_month])


@app.route('/recommendations')
def recommendations():
    """Recommendations view – renders the main dashboard with query console."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'Administrator':
        return "Access Denied", 403
    return redirect(url_for('admin_dashboard_route', section='users'))


# ── Role-protected routes ────────────────────────────────────────────────────

def _require_librarian_or_admin():
    """Return a 403 response when the logged-in user is not at least Librarian."""
    role = session.get('role', 'Student')
    if role not in ('Librarian', 'Faculty', 'Administrator'):
        _log_security_event('unauthorized_access', f"{session.get('user_id', 'anonymous')} denied librarian/admin route {request.path}", 'high', session.get('user_id'))
        _log_activity(session.get('user_id', 'anonymous'), 'unauthorized_access')
        return "Access Denied", 403
    return None


def _require_admin():
    """Return a 403 response when the logged-in user is not an Administrator."""
    if session.get('role') != 'Administrator':
        _log_security_event('unauthorized_access', f"{session.get('user_id', 'anonymous')} denied admin route {request.path}", 'high', session.get('user_id'))
        _log_activity(session.get('user_id', 'anonymous'), 'unauthorized_access')
        return "Access Denied", 403
    return None


@app.route('/students')
def students_view():
    """All students – librarian/admin only."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_librarian_or_admin()
    if redir:
        return redir

    user_id = session['user_id']
    user_role = session.get('role')

    try:
        conn = get_db_connection(MAIN_DB)
        students = conn.execute(
            "SELECT id, roll_number, name, branch, year, email, gpa FROM Students ORDER BY name"
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"[students_view] DB error: {e}")
        students = []

    return render_template('index.html',
                           user=user_id,
                           role=user_role,
                           user_info={'username': user_id, 'role': user_role, 'permissions': []},
                           page_title='All Students',
                           dashboard_data=_get_library_stats(),
                           prefill_query='show all students')


@app.route('/issued_books')
def issued_books_view():
    """Issued books overview – librarian/admin only."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_librarian_or_admin()
    if redir:
        return redir

    user_id = session['user_id']
    user_role = session.get('role')

    return render_template('index.html',
                           user=user_id,
                           role=user_role,
                           user_info={'username': user_id, 'role': user_role, 'permissions': []},
                           page_title='Issued Books',
                           dashboard_data=_get_library_stats(),
                           prefill_query='show all currently issued books')


@app.route('/fine_management')
def fine_management_view():
    """Fine management – librarian/admin only."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_librarian_or_admin()
    if redir:
        return redir

    user_id = session['user_id']
    user_role = session.get('role')

    return render_template('index.html',
                           user=user_id,
                           role=user_role,
                           user_info={'username': user_id, 'role': user_role, 'permissions': []},
                           page_title='Fine Management',
                           dashboard_data=_get_library_stats(),
                           prefill_query='show all unpaid fines')


@app.route('/fines')
def fines_view():
    """Fines – alias for fine_management, librarian/admin only."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_librarian_or_admin()
    if redir:
        return redir
    print("Route accessed:", request.path)
    print("User role:", session.get("role"))
    return redirect(url_for('fine_management_view'))


# ── JSON API endpoints ───────────────────────────────────────────────────────

@app.route('/api/students')
def api_students():
    """Return all students as JSON – librarian/admin only."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if session.get('role') not in ('Librarian', 'Faculty', 'Administrator'):
        return jsonify({'error': 'Access denied'}), 403
    print("Route accessed:", request.path)
    print("User role:", session.get("role"))
    try:
        conn = get_db_connection(MAIN_DB)
        rows = conn.execute(
            "SELECT id, roll_number, name, branch, year, email, gpa FROM Students ORDER BY name"
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        print(f"[api_students] error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/issued_books')
def api_issued_books():
    """Return currently issued books as JSON – librarian/admin only."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if session.get('role') not in ('Librarian', 'Faculty', 'Administrator'):
        return jsonify({'error': 'Access denied'}), 403
    print("Route accessed:", request.path)
    print("User role:", session.get("role"))
    try:
        conn = get_db_connection(MAIN_DB)
        rows = conn.execute(
            """SELECT i.id, s.roll_number, s.name as student_name, b.title, b.author,
                      i.issue_date, i.due_date, i.return_date, i.status
               FROM Issued i
               JOIN Books b ON i.book_id = b.id
               JOIN Students s ON i.student_id = s.id
               WHERE i.return_date IS NULL
               ORDER BY i.issue_date DESC"""
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        print(f"[api_issued_books] error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/fines')
def api_fines():
    """Return fines as JSON – librarian/admin only."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if session.get('role') not in ('Librarian', 'Faculty', 'Administrator'):
        return jsonify({'error': 'Access denied'}), 403
    print("Route accessed:", request.path)
    print("User role:", session.get("role"))
    try:
        conn = get_db_connection(MAIN_DB)
        rows = conn.execute(
            """SELECT f.id, s.roll_number, s.name as student_name,
                      f.fine_amount, f.fine_type, f.status, f.issue_date
               FROM Fines f
               JOIN Students s ON f.student_id = s.id
               ORDER BY f.issue_date DESC"""
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        print(f"[api_fines] error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/user_management')
def user_management_view():
    """User management – admin only."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_admin()
    if redir:
        return redir
    return redirect(url_for('admin_dashboard_route', section='users'))


@app.route('/system_statistics')
def system_statistics_view():
    """System statistics – admin only."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_admin()
    if redir:
        return redir
    return redirect(url_for('admin_dashboard_route', section='analytics'))


@app.route('/admin/activity_logs')
def admin_activity_logs():
    """Activity logs view within the consolidated admin dashboard."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_admin()
    if redir:
        return redir
    return redirect(url_for('admin_dashboard_route', section='logs'))


@app.route('/admin/add_user', methods=['POST'])
def admin_add_user():
    """Create a new system user from the admin dashboard."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_admin()
    if redir:
        return redir

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    role = _normalize_role(request.form.get('role', 'Student'))
    full_name = request.form.get('name', '').strip() or username
    email = request.form.get('email', '').strip() or f"{username.lower()}@library.local"

    if role not in SUPPORTED_ROLES:
        flash('Invalid role selected.', 'error')
        return redirect(url_for('admin_dashboard_route', section='users'))
    if not username or not password:
        flash('Username and password are required to create a user.', 'error')
        return redirect(url_for('admin_dashboard_route', section='users'))
    if not _password_meets_policy(password):
        flash('Password must be at least 8 characters long and include both letters and numbers.', 'error')
        return redirect(url_for('admin_dashboard_route', section='users'))
    if '@' not in email:
        flash('A valid email address is required.', 'error')
        return redirect(url_for('admin_dashboard_route', section='users'))

    conn = get_db_connection(MAIN_DB)
    try:
        existing = conn.execute(
            "SELECT id FROM Users WHERE username = ?",
            (username,),
        ).fetchone()
        if existing:
            flash('Username already exists.', 'error')
            return redirect(url_for('admin_dashboard_route', section='users'))

        linked_id = _save_linked_record(conn, role, request.form, username, email)
        conn.execute(
            """
            INSERT INTO Users (username, password, role, email, linked_id, full_name)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, generate_password_hash(password), role, email, linked_id, full_name),
        )
        _sync_user_role_assignment(conn, username, role, session['user_id'])
        conn.commit()
        _log_activity(session['user_id'], f'user_created:{username}:{role}')
        flash('User created successfully.', 'success')
    except sqlite3.IntegrityError:
        conn.rollback()
        flash('Username already exists.', 'error')
    except Exception as exc:
        conn.rollback()
        print(f"[admin_add_user] error: {exc}")
        flash('Failed to create user.', 'error')
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard_route', section='users'))


@app.route('/admin/update_user/<int:user_id>', methods=['POST'])
def admin_update_user(user_id):
    """Update user profile details and linked role-specific records."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_admin()
    if redir:
        return redir

    role = _normalize_role(request.form.get('role', 'Student'))
    email = request.form.get('email', '').strip()
    full_name = request.form.get('name', '').strip()
    if role not in SUPPORTED_ROLES:
        flash('Invalid role selected.', 'error')
        return redirect(url_for('admin_dashboard_route', section='users'))
    if not email or '@' not in email:
        flash('A valid email address is required.', 'error')
        return redirect(url_for('admin_dashboard_route', section='users'))

    conn = get_db_connection(MAIN_DB)
    try:
        user = conn.execute(
            "SELECT id, username, role, linked_id FROM Users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not user:
            flash('User not found.', 'error')
            return redirect(url_for('admin_dashboard_route', section='users'))

        linked_id = _save_linked_record(
            conn,
            role,
            request.form,
            user['username'],
            email,
            user['linked_id'] if role in ('Student', 'Faculty') else None,
        )
        if role not in ('Student', 'Faculty') and user['role'] in ('Student', 'Faculty'):
            linked_id = None
        conn.execute(
            "UPDATE Users SET email = ?, role = ?, linked_id = ?, full_name = ? WHERE id = ?",
            (email, role, linked_id, full_name or user['username'], user_id),
        )
        _sync_user_role_assignment(conn, user['username'], role, session['user_id'])
        conn.commit()
        _log_activity(session['user_id'], f'user_updated:{user["username"]}')
        flash('User updated successfully.', 'success')
    except Exception as exc:
        conn.rollback()
        print(f"[admin_update_user] error: {exc}")
        flash('Failed to update user.', 'error')
    finally:
        conn.close()
    return redirect(url_for('admin_dashboard_route', section='users'))


@app.route('/admin/change_role/<int:user_id>', methods=['POST'])
def admin_change_role(user_id):
    """Change a user role without editing other profile fields."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_admin()
    if redir:
        return redir

    new_role = _normalize_role(request.form.get('role', '').strip())
    if new_role not in SUPPORTED_ROLES:
        flash('Invalid role selected.', 'error')
        return redirect(url_for('admin_dashboard_route', section='permissions'))

    conn = get_db_connection(MAIN_DB)
    try:
        user = conn.execute(
            "SELECT username, email, linked_id FROM Users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not user:
            flash('User not found.', 'error')
            return redirect(url_for('admin_dashboard_route', section='permissions'))

        linked_id = user['linked_id']
        if new_role in ('Student', 'Faculty') and not linked_id:
            linked_id = _save_linked_record(conn, new_role, request.form, user['username'], user['email'])
        elif new_role not in ('Student', 'Faculty'):
            linked_id = None

        conn.execute(
            "UPDATE Users SET role = ?, linked_id = ? WHERE id = ?",
            (new_role, linked_id, user_id),
        )
        _sync_user_role_assignment(conn, user['username'], new_role, session['user_id'])
        conn.commit()
        _log_activity(session['user_id'], f'role_changed:{user["username"]}:{new_role}')
        flash('Role updated successfully.', 'success')
    except Exception as exc:
        conn.rollback()
        print(f"[admin_change_role] error: {exc}")
        flash('Failed to change role.', 'error')
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard_route', section='permissions'))


@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
def admin_delete_user(user_id):
    """Delete a user and any directly linked student/faculty profile."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_admin()
    if redir:
        return redir

    conn = get_db_connection(MAIN_DB)
    try:
        user = conn.execute(
            "SELECT username, role, linked_id FROM Users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not user:
            flash('User not found.', 'error')
            return redirect(url_for('admin_dashboard_route', section='users'))
        if user['username'] == session['user_id']:
            flash('You cannot delete your own active account.', 'error')
            return redirect(url_for('admin_dashboard_route', section='users'))
        if _normalize_role(user['role']) == 'Administrator':
            admin_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM Users WHERE role = 'Administrator'"
            ).fetchone()['cnt']
            if admin_count <= 1:
                flash('You cannot delete the last administrator account.', 'error')
                return redirect(url_for('admin_dashboard_route', section='users'))

        conn.execute("DELETE FROM UserRoles WHERE user_id = ?", (user['username'],))
        _delete_linked_record(conn, _normalize_role(user['role']), user['linked_id'])
        conn.execute("DELETE FROM Users WHERE id = ?", (user_id,))
        conn.commit()
        _log_activity(session['user_id'], f'user_deleted:{user["username"]}')
        flash('User deleted successfully.', 'success')
    except Exception as exc:
        conn.rollback()
        print(f"[admin_delete_user] error: {exc}")
        flash('Failed to delete user.', 'error')
    finally:
        conn.close()
    return redirect(url_for('admin_dashboard_route', section='users'))


@app.route('/admin/update_permissions/<int:role_id>', methods=['POST'])
def admin_update_permissions(role_id):
    """Update role permissions, table access, and query execution flags."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_admin()
    if redir:
        return redir

    selected_permissions = set(request.form.getlist('permissions'))
    conn = get_db_connection(MAIN_DB)
    try:
        permission_rows = _get_permission_metadata(conn)
        permission_map = {row['permission_name']: row['id'] for row in permission_rows}
        conn.execute("DELETE FROM RolePermissions WHERE role_id = ?", (role_id,))
        for permission_name in selected_permissions:
            permission_id = permission_map.get(permission_name)
            if permission_id:
                conn.execute(
                    "INSERT INTO RolePermissions (role_id, permission_id) VALUES (?, ?)",
                    (role_id, permission_id),
                )
        conn.commit()
        role_row = conn.execute("SELECT name FROM Roles WHERE id = ?", (role_id,)).fetchone()
        role_name = role_row['name'] if role_row else str(role_id)
        _log_activity(session['user_id'], f'permissions_updated:{role_name}')
        flash('Role permissions updated successfully.', 'success')
    except Exception as exc:
        conn.rollback()
        print(f"[admin_update_permissions] error: {exc}")
        flash('Failed to update permissions.', 'error')
    finally:
        conn.close()

    return redirect(url_for('admin_dashboard_route', section='permissions'))


@app.route('/admin/update_settings', methods=['POST'])
def admin_update_settings():
    """Persist admin-configurable system settings."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_admin()
    if redir:
        return redir

    max_limit = request.form.get('max_query_result_limit', '100').strip() or '100'
    if not max_limit.isdigit() or int(max_limit) <= 0:
        flash('Max query result limit must be a positive number.', 'error')
        return redirect(url_for('admin_dashboard_route', section='settings'))

    _set_setting('max_query_result_limit', max_limit, 'Maximum rows returned per query', session['user_id'])
    _set_setting(
        'voice_input_enabled',
        'true' if request.form.get('voice_input_enabled') == 'on' else 'false',
        'Enable voice input features',
        session['user_id'],
    )
    _set_setting(
        'ai_query_enabled',
        'true' if request.form.get('ai_query_enabled') == 'on' else 'false',
        'Enable AI query processing',
        session['user_id'],
    )
    _set_setting(
        'ollama_sql_enabled',
        'true' if request.form.get('ollama_sql_enabled') == 'on' else 'false',
        'Enable Ollama SQL generation',
        session['user_id'],
    )
    _log_activity(session['user_id'], 'settings_updated')
    flash('System settings saved successfully.', 'success')
    return redirect(url_for('admin_dashboard_route', section='settings'))


@app.route('/admin-dashboard')
def admin_dashboard():
    """Administrator dashboard."""
    return redirect(url_for('admin_dashboard_route', section=request.args.get('section', 'overview')))


# ── Alternative UI views ─────────────────────────────────────────────────────

@app.route("/modern")
def modern_ui():
    """Modern interface."""
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    return render_template("modern.html")


@app.route("/minimal")
def minimal_ui():
    """Minimal interface."""
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    return render_template("modern-minimal.html")


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal_error(error):
    return render_template("500.html"), 500


@app.errorhandler(403)
def forbidden(error):
    return render_template("403.html"), 403


# ---------------------------------------------------------------------------
# Context processor – inject current user into all templates
# ---------------------------------------------------------------------------

@app.context_processor
def inject_user():
    """Make ``current_user`` and ``user_role`` available in every template."""
    if "user_id" in session:
        return {
            "current_user": {
                "username": session["user_id"],
                "role": session.get("role", "Student"),
            },
            "user_role": session.get("role", "Student"),
        }
    return {}


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    app.run(debug=debug_mode, host="0.0.0.0", port=5000)
