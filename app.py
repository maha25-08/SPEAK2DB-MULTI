"""
🗃️ SPEAK2DB - NL-to-SQL Query Assistant
Integrated with domain vocabulary, clarification chatbot, RBAC,
SQL safety gate, and security headers.
"""

import logging
import os
import jinja2
import sqlite3
import time
from ollama_sql import generate_sql, generate_complex_sql
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Tuple
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for

# ── New pipeline modules ────────────────────────────────────────────────────
from domain_vocabulary import build_vocabulary, preprocess_query, get_vocabulary_sample
from clarification import is_ambiguous_query, get_clarification, apply_clarification_choice
from query_correction import correct_query
from query_context import save_context, is_followup, rewrite_followup, get_last_query
from routes.admin_routes import register_admin_routes
from routes.api import api_bp
from routes.auth_routes import register_auth_routes
from routes.dashboard import dashboard_bp
from routes.query_routes import register_query_routes
from routes.views import views_bp
from utils.helpers import is_staff
from utils.validators import (
    validate_managed_user_form as validate_managed_user_form_service,
    validate_query_result_limit as validate_query_result_limit_service,
)

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
MAIN_DB = os.getenv("MAIN_DB", "library_main.db")
ARCHIVE_DB = os.getenv("ARCHIVE_DB", "library_archive.db")
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

ROLE_CHOICES = ('Student', 'Faculty', 'Librarian', 'Administrator')
ROLE_PERMISSION_SCOPE = {
    'Student': 'Student',
    'Faculty': 'Librarian',
    'Librarian': 'Librarian',
    'Administrator': 'Administrator',
}
DEFAULT_QUERY_LIMIT = 100


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
app.register_blueprint(dashboard_bp)
app.register_blueprint(api_bp)
app.register_blueprint(views_bp)

# ── Run DB schema migrations at startup ─────────────────────────────────────
ensure_query_history_schema()


def _ensure_query_history_schema():
    """Compatibility wrapper used by tests and startup code."""
    ensure_query_history_schema()


def _normalize_role(role: str) -> str:
    """Normalize database and session role names."""
    role = (role or '').strip()
    mapping = {
        'Admin': 'Administrator',
        'Administrator': 'Administrator',
        'Faculty': 'Faculty',
        'Librarian': 'Librarian',
        'Student': 'Student',
    }
    return mapping.get(role, role or 'Student')


def _role_permission_scope(role: str) -> str:
    """Return the RBAC/permission scope used for a UI role."""
    return ROLE_PERMISSION_SCOPE.get(_normalize_role(role), 'Student')


def _request_ip() -> str:
    """Best-effort request IP address."""
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def _request_user_agent() -> str:
    """Best-effort request user agent."""
    return request.headers.get('User-Agent', 'unknown')


def _ensure_admin_support_schema():
    """Create lightweight admin-control tables and seed settings/permissions."""
    try:
        conn = sqlite3.connect(MAIN_DB)
        cursor = conn.cursor()
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS ActivityLogs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                action TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )

        default_settings = {
            'max_query_result_limit': ('100', 'Maximum rows returned by query console'),
            'voice_input_enabled': ('true', 'Enable voice input in supported UIs'),
            'ai_query_enabled': ('true', 'Enable AI-driven natural language query processing'),
            'ollama_sql_enabled': ('true', 'Enable Ollama-assisted SQL generation when available'),
        }
        for setting_name, (setting_value, description) in default_settings.items():
            cursor.execute(
                '''
                INSERT INTO SecuritySettings (setting_name, setting_value, description)
                SELECT ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM SecuritySettings WHERE setting_name = ?
                )
                ''',
                (setting_name, setting_value, description, setting_name),
            )

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'")
        table_names = sorted(row[0] for row in cursor.fetchall())

        required_permissions = {
            'execute_queries': ('query_control', 'Allow natural language query execution'),
            'use_ai_queries': ('query_control', 'Allow AI-assisted SQL generation'),
        }
        for table_name in table_names:
            required_permissions[f'table_access:{table_name}'] = (
                'table_access',
                f'Allow access to the {table_name} table',
            )

        for perm_name, (category, description) in required_permissions.items():
            cursor.execute(
                '''
                INSERT INTO Permissions (name, category, description)
                SELECT ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM Permissions WHERE name = ?
                )
                ''',
                (perm_name, category, description, perm_name),
            )

        role_defaults = {
            'Student': {'Books', 'Issued', 'Fines', 'Reservations', 'Students'},
            'Librarian': {
                'Books', 'Issued', 'Fines', 'Reservations', 'Students',
                'Users', 'Publishers', 'Departments', 'QueryHistory',
                'SpecialPermissions', 'Faculty'
            },
            'Administrator': set(table_names),
        }

        role_ids = {
            row[1]: row[0]
            for row in cursor.execute("SELECT id, name FROM Roles WHERE name IN ('Student', 'Librarian', 'Administrator')")
        }
        permission_lookup = {
            row[1]: row[0]
            for row in cursor.execute("SELECT id, name FROM Permissions")
        }

        for role_name, default_tables in role_defaults.items():
            role_id = role_ids.get(role_name)
            if not role_id:
                continue

            default_perm_names = {'execute_queries', 'use_ai_queries'}
            default_perm_names.update(f'table_access:{table_name}' for table_name in default_tables)
            for perm_name in sorted(default_perm_names):
                perm_id = permission_lookup.get(perm_name)
                if not perm_id:
                    continue
                existing_assignment = cursor.execute(
                    "SELECT 1 FROM RolePermissions WHERE role_id = ? AND permission_id = ?",
                    (role_id, perm_id),
                ).fetchone()
                if existing_assignment:
                    continue
                cursor.execute(
                    '''
                    INSERT INTO RolePermissions (role_id, permission_id)
                    VALUES (?, ?)
                    ''',
                    (role_id, perm_id),
                )

        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("[schema-init] Admin support migration skipped: %s", exc)


def _get_setting(name: str, default: str = '') -> str:
    """Read a system setting from SecuritySettings."""
    try:
        conn = get_db_connection(MAIN_DB)
        row = conn.execute(
            "SELECT setting_value FROM SecuritySettings WHERE setting_name = ?",
            (name,),
        ).fetchone()
        conn.close()
        return row['setting_value'] if row else default
    except Exception:
        return default


def _get_bool_setting(name: str, default: bool = False) -> bool:
    """Read a boolean system setting."""
    value = _get_setting(name, 'true' if default else 'false')
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _get_int_setting(name: str, default: int) -> int:
    """Read an integer setting with a safe fallback."""
    raw_value = _get_setting(name, str(default))
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        logger.warning("[settings] Invalid integer for %s: %r; using %s", name, raw_value, default)
        return default


def _set_setting(name: str, value: str, updated_by: str = None, description: str = None):
    """Insert or update a setting value."""
    updated_by = updated_by or session.get('user_id', 'system')
    conn = sqlite3.connect(MAIN_DB)
    cursor = conn.cursor()
    existing = cursor.execute(
        "SELECT id FROM SecuritySettings WHERE setting_name = ?",
        (name,),
    ).fetchone()
    if existing:
        cursor.execute(
            '''
            UPDATE SecuritySettings
            SET setting_value = ?, description = COALESCE(?, description), updated_by = ?, updated_date = CURRENT_TIMESTAMP
            WHERE id = ?
            ''',
            (str(value), description, updated_by, existing[0]),
        )
    else:
        cursor.execute(
            '''
            INSERT INTO SecuritySettings (setting_name, setting_value, description, updated_by, updated_date)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''',
            (name, str(value), description, updated_by),
        )
    conn.commit()
    conn.close()


def _log_activity(user_id: str, action: str):
    """Write a compact activity log entry."""
    try:
        conn = sqlite3.connect(MAIN_DB)
        conn.execute(
            "INSERT INTO ActivityLogs (user_id, action, timestamp) VALUES (?, ?, ?)",
            (user_id, action, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error("[activity-log] %s", exc)


def _log_audit_event(user_id: str, role: str, action: str, resource_type: str, details: str, success: bool = True):
    """Write a detailed audit log entry when the table is available."""
    try:
        conn = sqlite3.connect(MAIN_DB)
        conn.execute(
            '''
            INSERT INTO AuditLog (user_id, user_role, action, resource_type, details, ip_address, user_agent, timestamp, success)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                user_id,
                _normalize_role(role),
                action,
                resource_type,
                details,
                _request_ip(),
                _request_user_agent(),
                datetime.now().isoformat(),
                1 if success else 0,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error("[audit-log] %s", exc)


def _log_security_event(event_type: str, details: str, severity: str = 'medium', user_id: str = None):
    """Write a security monitoring record."""
    try:
        conn = sqlite3.connect(MAIN_DB)
        conn.execute(
            '''
            INSERT INTO SecurityLog (event_type, details, ip_address, user_agent, user_id, session_id, timestamp, severity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                event_type,
                details,
                _request_ip(),
                _request_user_agent(),
                user_id,
                session.get('audit_session_id'),
                datetime.now().isoformat(),
                severity,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error("[security-log] %s", exc)


def _record_failed_login(username: str, reason: str):
    """Persist a failed login attempt for admin monitoring."""
    try:
        conn = sqlite3.connect(MAIN_DB)
        conn.execute(
            '''
            INSERT INTO FailedLoginAttempts (username, ip_address, user_agent, attempt_time, failure_reason, blocked)
            VALUES (?, ?, ?, ?, ?, 0)
            ''',
            (username, _request_ip(), _request_user_agent(), datetime.now().isoformat(), reason),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error("[failed-login] %s", exc)


def _start_user_session_log(user_id: str, role: str):
    """Create a session log entry for the current login."""
    try:
        session['audit_session_id'] = session.get('audit_session_id') or os.urandom(16).hex()
        conn = sqlite3.connect(MAIN_DB)
        conn.execute(
            '''
            INSERT INTO SessionLog (user_id, user_role, session_id, login_time, ip_address, user_agent, status)
            VALUES (?, ?, ?, ?, ?, ?, 'Active')
            ''',
            (
                user_id,
                _normalize_role(role),
                session['audit_session_id'],
                datetime.now().isoformat(),
                _request_ip(),
                _request_user_agent(),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error("[session-log] %s", exc)


def _end_user_session_log():
    """Mark the current login session as logged out."""
    audit_session_id = session.get('audit_session_id')
    if not audit_session_id:
        return
    try:
        conn = sqlite3.connect(MAIN_DB)
        conn.execute(
            '''
            UPDATE SessionLog
            SET logout_time = ?, status = 'LoggedOut'
            WHERE session_id = ? AND logout_time IS NULL
            ''',
            (datetime.now().isoformat(), audit_session_id),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error("[session-log] logout update failed: %s", exc)


def _extract_tables_from_sql(sql_query: str) -> set:
    """Return tables referenced by FROM/JOIN clauses."""
    tables = set()
    if not sql_query:
        return tables
    tables.update(re.findall(r'\bFROM\s+(\w+)', sql_query, re.IGNORECASE))
    tables.update(re.findall(r'\bJOIN\s+(\w+)', sql_query, re.IGNORECASE))
    return tables


def _get_role_permission_config(conn, role_name: str) -> dict:
    """Fetch DB-backed permissions for a role scope."""
    role_scope = _role_permission_scope(role_name)
    permissions = [
        dict(row)
        for row in conn.execute(
            '''
            SELECT p.id, p.name, p.category, p.description
            FROM Roles r
            JOIN RolePermissions rp ON rp.role_id = r.id
            JOIN Permissions p ON p.id = rp.permission_id
            WHERE r.name = ?
            ORDER BY p.category, p.name
            ''',
            (role_scope,),
        ).fetchall()
    ]
    return {
        'permissions': permissions,
        'permission_names': {perm['name'] for perm in permissions},
        'table_access': {
            perm['name'].split(':', 1)[1]
            for perm in permissions
            if perm['category'] == 'table_access' and ':' in perm['name']
        },
    }


def _role_can_execute_queries(conn, role_name: str) -> bool:
    """Check role-level query permission."""
    config = _get_role_permission_config(conn, role_name)
    if _role_permission_scope(role_name) in {'Student', 'Librarian', 'Administrator'}:
        return 'execute_queries' in config['permission_names']
    return True


def _role_can_use_ai_queries(conn, role_name: str) -> bool:
    """Check whether a role may use AI-assisted query generation."""
    config = _get_role_permission_config(conn, role_name)
    if _role_permission_scope(role_name) in {'Student', 'Librarian', 'Administrator'}:
        return 'use_ai_queries' in config['permission_names']
    return True


def _role_allows_tables(conn, role_name: str, sql_query: str) -> Tuple[bool, str]:
    """Enforce DB-configured table access rules for a role when configured."""
    config = _get_role_permission_config(conn, role_name)
    allowed_tables = config['table_access']
    query_tables = _extract_tables_from_sql(sql_query)
    if not allowed_tables:
        if config['permissions'] and query_tables:
            return False, f"Role {_normalize_role(role_name)} has no table access permissions configured"
        return True, ""
    for table in query_tables:
        if table not in allowed_tables:
            return False, f"Role {_normalize_role(role_name)} cannot access table {table}"
    return True, ""


def _apply_result_limit(sql_query: str, max_rows: int) -> str:
    """Cap query results with a configurable LIMIT."""
    if not sql_query or max_rows <= 0:
        return sql_query

    limit_match = re.search(r'\bLIMIT\s+(\d+)\b', sql_query, re.IGNORECASE)
    if not limit_match:
        return sql_query.rstrip().rstrip(';') + f" LIMIT {max_rows}"

    current_limit = int(limit_match.group(1))
    if current_limit <= max_rows:
        return sql_query

    return re.sub(r'\bLIMIT\s+\d+\b', f'LIMIT {max_rows}', sql_query, count=1, flags=re.IGNORECASE)


def _generate_sql_for_query(user_query: str, conn, role_name: str) -> Tuple[str, str]:
    """Generate SQL while respecting admin AI/Ollama controls."""
    if not _get_bool_setting('ai_query_enabled', True):
        raise PermissionError('AI query processing is disabled by the administrator.')

    if not _role_can_execute_queries(conn, role_name):
        raise PermissionError(f'{_normalize_role(role_name)} queries are disabled for this role.')

    ollama_enabled = _get_bool_setting('ollama_sql_enabled', True)
    role_ai_enabled = _role_can_use_ai_queries(conn, role_name)

    if not ollama_enabled or not role_ai_enabled:
        return generate_complex_sql(user_query), 'rule-based'

    try:
        return generate_sql(user_query), 'hybrid'
    except Exception as exc:
        _log_activity(session.get('user_id', 'system'), f"LLM fallback triggered: {str(exc)[:80]}")
        return generate_complex_sql(user_query), 'rule-based-fallback'


def _log_query_history(user_id: str, role: str, user_query: str, sql_query: str, success: bool, response_time: float = None):
    """Persist query analytics/history."""
    try:
        conn = sqlite3.connect(MAIN_DB)
        conn.execute(
            '''
            INSERT INTO QueryHistory (user_id, query, sql_query, response_time, timestamp, success, role)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                user_id,
                user_query,
                sql_query,
                response_time,
                datetime.now().isoformat(),
                1 if success else 0,
                _normalize_role(role),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error("[query-history] %s", exc)


def _fetch_managed_users(conn):
    """Return a unified list of users for the admin control panel."""
    rows = conn.execute(
        '''
        SELECT
            u.id,
            u.username,
            u.role,
            u.email,
            u.created_date,
            COALESCE(
                (SELECT s.name FROM Students s
                 WHERE s.roll_number = u.username OR lower(s.email) = lower(u.email)
                 LIMIT 1),
                (SELECT f.name FROM Faculty f
                 WHERE lower(f.email) = lower(u.email)
                 LIMIT 1),
                u.username
            ) AS name,
            (SELECT s.roll_number FROM Students s
             WHERE s.roll_number = u.username OR lower(s.email) = lower(u.email)
             LIMIT 1) AS roll_number,
            (SELECT s.branch FROM Students s
             WHERE s.roll_number = u.username OR lower(s.email) = lower(u.email)
             LIMIT 1) AS branch,
            (SELECT s.year FROM Students s
             WHERE s.roll_number = u.username OR lower(s.email) = lower(u.email)
             LIMIT 1) AS year,
            (SELECT s.phone FROM Students s
             WHERE s.roll_number = u.username OR lower(s.email) = lower(u.email)
             LIMIT 1) AS student_phone,
            (SELECT f.department FROM Faculty f WHERE lower(f.email) = lower(u.email) LIMIT 1) AS department,
            (SELECT f.designation FROM Faculty f WHERE lower(f.email) = lower(u.email) LIMIT 1) AS designation,
            (SELECT f.phone FROM Faculty f WHERE lower(f.email) = lower(u.email) LIMIT 1) AS faculty_phone
        FROM Users u
        ORDER BY datetime(u.created_date) DESC, u.username ASC
        '''
    ).fetchall()
    return [dict(row) for row in rows]


def _fetch_activity_logs(conn, limit: int = 100):
    """Return recent activity log entries."""
    rows = conn.execute(
        "SELECT id, user_id, action, timestamp FROM ActivityLogs ORDER BY datetime(timestamp) DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _fetch_role_permission_matrix(conn):
    """Return permissions grouped by role for admin editing."""
    role_rows = conn.execute(
        "SELECT id, name, level FROM Roles WHERE name IN ('Student', 'Librarian', 'Administrator') ORDER BY level"
    ).fetchall()
    permission_rows = conn.execute(
        "SELECT id, name, category, description FROM Permissions ORDER BY category, name"
    ).fetchall()
    assigned_lookup = {}
    for row in conn.execute("SELECT role_id, permission_id FROM RolePermissions").fetchall():
        assigned_lookup.setdefault(row['role_id'], set()).add(row['permission_id'])

    matrix = []
    for role_row in role_rows:
        role_data = dict(role_row)
        grouped_permissions = {}
        for perm in permission_rows:
            grouped_permissions.setdefault(perm['category'], []).append({
                'id': perm['id'],
                'name': perm['name'],
                'description': perm['description'],
                'assigned': perm['id'] in assigned_lookup.get(role_row['id'], set()),
            })
        matrix.append({
            'id': role_row['id'],
            'name': role_row['name'],
            'label': 'Faculty / Librarian' if role_row['name'] == 'Librarian' else role_row['name'],
            'permissions_by_category': grouped_permissions,
        })
    return matrix


def _build_admin_dashboard_context(active_section: str = 'overview') -> dict:
    """Collect control-panel data for the admin dashboard."""
    conn = get_db_connection(MAIN_DB)
    try:
        stats = {
            'total_books': conn.execute("SELECT COUNT(*) AS cnt FROM Books").fetchone()['cnt'],
            'total_users': conn.execute("SELECT COUNT(*) AS cnt FROM Users").fetchone()['cnt'],
            'total_students': conn.execute("SELECT COUNT(*) AS cnt FROM Students").fetchone()['cnt'],
            'total_faculty': conn.execute("SELECT COUNT(*) AS cnt FROM Faculty").fetchone()['cnt'],
            'active_sessions': conn.execute(
                "SELECT COUNT(*) AS cnt FROM SessionLog WHERE status = 'Active' AND logout_time IS NULL"
            ).fetchone()['cnt'],
            'failed_queries': conn.execute(
                "SELECT COUNT(*) AS cnt FROM QueryHistory WHERE success = 0"
            ).fetchone()['cnt'],
            'blocked_queries': conn.execute(
                "SELECT COUNT(*) AS cnt FROM SecurityLog WHERE event_type LIKE '%blocked%'"
            ).fetchone()['cnt'],
            'unauthorized_attempts': conn.execute(
                "SELECT COUNT(*) AS cnt FROM SecurityLog WHERE event_type = 'unauthorized_access'"
            ).fetchone()['cnt'],
        }

        most_active_users = [
            dict(row)
            for row in conn.execute(
                '''
                SELECT user_id, COUNT(*) AS query_count
                FROM QueryHistory
                GROUP BY user_id
                ORDER BY query_count DESC, user_id ASC
                LIMIT 5
                '''
            ).fetchall()
        ]

        security_events = [
            dict(row)
            for row in conn.execute(
                '''
                SELECT event_type, details, timestamp, severity, user_id
                FROM SecurityLog
                ORDER BY datetime(timestamp) DESC, id DESC
                LIMIT 20
                '''
            ).fetchall()
        ]

        failed_logins = [
            dict(row)
            for row in conn.execute(
                '''
                SELECT username, ip_address, attempt_time, failure_reason, blocked
                FROM FailedLoginAttempts
                ORDER BY datetime(attempt_time) DESC, id DESC
                LIMIT 10
                '''
            ).fetchall()
        ]

        llm_usage = {
            'ai_enabled': _get_bool_setting('ai_query_enabled', True),
            'ollama_enabled': _get_bool_setting('ollama_sql_enabled', True),
            'hybrid_queries': conn.execute(
                "SELECT COUNT(*) AS cnt FROM ActivityLogs WHERE action LIKE 'Query executed (hybrid)%'"
            ).fetchone()['cnt'],
            'rule_based_queries': conn.execute(
                "SELECT COUNT(*) AS cnt FROM ActivityLogs WHERE action LIKE 'Query executed (rule-based)%'"
            ).fetchone()['cnt'],
            'llm_failures': conn.execute(
                "SELECT COUNT(*) AS cnt FROM ActivityLogs WHERE action LIKE 'LLM fallback%'"
            ).fetchone()['cnt'],
        }

        context = {
            'role': session.get('role', 'Administrator'),
            'user': session.get('user_id', 'admin'),
            'stats': stats,
            'recent_activity': _fetch_activity_logs(conn, limit=25),
            'managed_users': _fetch_managed_users(conn),
            'role_permissions': _fetch_role_permission_matrix(conn),
            'settings': {
                'max_query_result_limit': _get_int_setting('max_query_result_limit', DEFAULT_QUERY_LIMIT),
                'voice_input_enabled': _get_bool_setting('voice_input_enabled', True),
                'ai_query_enabled': _get_bool_setting('ai_query_enabled', True),
                'ollama_sql_enabled': _get_bool_setting('ollama_sql_enabled', True),
            },
            'security_events': security_events,
            'failed_logins': failed_logins,
            'most_active_users': most_active_users,
            'llm_usage': llm_usage,
            'active_section': active_section,
        }
        return context
    finally:
        conn.close()


def _get_user_with_details(conn, user_id: int):
    """Get a managed user row and derived profile details."""
    for user in _fetch_managed_users(conn):
        if int(user['id']) == int(user_id):
            return user
    return None


def _sync_role_profile_tables(conn, user_record: dict):
    """Keep Users/Students/Faculty aligned for the current role."""
    role = _normalize_role(user_record.get('role'))
    username = user_record.get('username', '').strip()
    email = user_record.get('email', '').strip().lower()
    name = user_record.get('name', '').strip() or username
    phone = (user_record.get('phone') or '').strip() or 'N/A'
    branch = (user_record.get('branch') or '').strip() or 'GEN'
    year = (user_record.get('year') or '').strip() or '1'
    department = (user_record.get('department') or '').strip() or 'General'
    designation = (user_record.get('designation') or '').strip() or ('Librarian' if role == 'Librarian' else 'Faculty')

    if role == 'Student':
        existing = conn.execute(
            "SELECT id FROM Students WHERE roll_number = ? OR lower(email) = lower(?)",
            (username, email),
        ).fetchone()
        if existing:
            conn.execute(
                '''
                UPDATE Students
                SET roll_number = ?, name = ?, branch = ?, year = ?, email = ?, phone = ?, role = 'Student'
                WHERE id = ?
                ''',
                (username, name, branch, year, email, phone, existing['id']),
            )
        else:
            conn.execute(
                '''
                INSERT INTO Students (roll_number, name, branch, year, email, phone, role)
                VALUES (?, ?, ?, ?, ?, ?, 'Student')
                ''',
                (username, name, branch, year, email, phone),
            )
        conn.execute(
            "DELETE FROM Faculty WHERE lower(email) = lower(?)",
            (email,),
        )
    elif role in ('Faculty', 'Librarian'):
        existing = conn.execute(
            "SELECT id FROM Faculty WHERE lower(email) = lower(?)",
            (email,),
        ).fetchone()
        if existing:
            conn.execute(
                '''
                UPDATE Faculty
                SET name = ?, department = ?, designation = ?, email = ?, phone = ?, specialization = ?
                WHERE id = ?
                ''',
                (name, department, designation, email, phone, designation, existing['id']),
            )
        else:
            conn.execute(
                '''
                INSERT INTO Faculty (name, department, designation, email, phone, specialization)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (name, department, designation, email, phone, designation),
            )
        conn.execute(
            "DELETE FROM Students WHERE roll_number = ? OR lower(email) = lower(?)",
            (username, email),
        )
    else:
        conn.execute(
            "DELETE FROM Students WHERE roll_number = ? OR lower(email) = lower(?)",
            (username, email),
        )
        conn.execute(
            "DELETE FROM Faculty WHERE lower(email) = lower(?)",
            (email,),
        )


def _validate_managed_user_form(form_data, existing_user: dict = None) -> Tuple[dict, str]:
    """Validate and normalize admin user-management payloads."""
    return validate_managed_user_form_service(form_data, existing_user)


_ensure_admin_support_schema()

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
# Student-specific SQL helpers
# ---------------------------------------------------------------------------

def _inject_and_condition(sql_query: str, condition: str) -> str:
    """Inject *condition* after WHERE and join it to existing predicates with AND."""
    match = re.search(r'\bWHERE\b', sql_query, re.IGNORECASE)
    if match:
        pos = match.end()
        return sql_query[:pos] + f" {condition} AND" + sql_query[pos:]
    return sql_query + f" WHERE {condition}"


def _apply_student_filters(
    sql_query: str,
    sid: int,
    has_where: bool,
    sq_lower: str,
    q_lower: str,
) -> str:
    """Apply student-specific SQL rewriting for student-only queries."""
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        return sql_query

    # Pattern 1: table-level security – always restrict personal tables to the
    # logged-in student, regardless of whether a WHERE clause already exists.
    for tbl in ('fines', 'issued', 'reservations'):
        if tbl in sq_lower:
            # Only inject when the exact student_id filter is not already present
            already_filtered = bool(
                re.search(r'\bstudent_id\s*=\s*' + str(sid) + r'\b', sql_query, re.IGNORECASE)
            )
            if not already_filtered:
                if has_where:
                    return _inject_and_condition(sql_query, f"student_id = {sid}")
                return sql_query + f" WHERE student_id = {sid}"
            return sql_query

    if 'students' in sq_lower and not has_where:
        return sql_query + f" WHERE id = {sid}"

    # Pattern 2: "my …" queries – use safe, schema-correct SQL templates
    if 'my' not in q_lower:
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
    # Departments join uses Students.branch = Departments.id (the PK column)
    _profile_base = (
        f"SELECT s.*, d.name as department_name FROM Students s "
        f"JOIN Departments d ON s.branch = d.id "
        f"WHERE s.id = {sid}"
    )

    # ── fine / payment patterns ────────────────────────────────────────────
    if any(k in q_lower for k in ('my fines', 'my fine', 'my fine records',
                                   'my payment history', 'my payment records')):
        return _fines_base + " ORDER BY f.issue_date DESC"

    if any(k in q_lower for k in ('my current fines', 'my unpaid fines',
                                   'my outstanding fines')):
        return _fines_base + " AND f.status = 'Unpaid' ORDER BY f.issue_date DESC"

    if 'my outstanding balance' in q_lower or 'my library account balance' in q_lower:
        return (
            f"SELECT s.name, SUM(f.fine_amount) as total_balance "
            f"FROM Students s LEFT JOIN Fines f ON s.id = f.student_id "
            f"WHERE s.id = {sid} AND f.status = 'Unpaid' GROUP BY s.id, s.name"
        )
    if 'my total fines' in q_lower:
        return (
            f"SELECT s.name, SUM(f.fine_amount) as total_balance "
            f"FROM Students s LEFT JOIN Fines f ON s.id = f.student_id "
            f"WHERE s.id = {sid} AND f.status = 'Unpaid' GROUP BY s.id, s.name"
        )

    # ── book / borrowing patterns ──────────────────────────────────────────
    if any(k in q_lower for k in ('my current books', 'books due')):
        return _books_base + " AND i.return_date IS NULL ORDER BY i.due_date ASC"

    if 'my overdue' in q_lower:
        return (
            _books_base
            + " AND i.return_date IS NULL AND i.due_date < date('now')"
        )

    if any(k in q_lower for k in ('my books', 'my issued books', 'my borrowed books',
                                   'my borrowing history', 'my reading history',
                                   'my total books')):
        return _books_base + " ORDER BY i.issue_date DESC"

    # ── reservation patterns ───────────────────────────────────────────────
    if any(k in q_lower for k in ('my reservations', 'my reserved books')):
        return (
            f"SELECT r.*, b.title, b.author FROM Reservations r "
            f"JOIN Books b ON r.book_id = b.id "
            f"WHERE r.student_id = {sid} ORDER BY r.reservation_date DESC"
        )

    # ── profile / account patterns ─────────────────────────────────────────
    if any(k in q_lower for k in ('my profile', 'my student info', 'my account details',
                                   'my student record', 'my personal information',
                                   'my personal details', 'my enrollment')):
        return _profile_base

    if any(k in q_lower for k in ('my account', 'my library account', 'my library status',
                                   'my library record', 'my library history',
                                   'my personal data')):
        return _profile_base

    # ── academic patterns ──────────────────────────────────────────────────
    if any(k in q_lower for k in ('my gpa', 'my attendance', 'my academic',
                                   'my semester', 'my course', 'my grades',
                                   'my current status', 'my current semester',
                                   'my current year')):
        return (
            f"SELECT gpa, attendance, role, created_date "
            f"FROM Students WHERE id = {sid}"
        )

    # ── generic "do i have …" / "what are my …" patterns ──────────────────
    if 'do i have' in q_lower or 'what are my' in q_lower or 'am i' in q_lower:
        if 'fine' in q_lower:
            return _fines_base + " AND f.status = 'Unpaid' ORDER BY f.issue_date DESC"
        if 'book' in q_lower:
            return _books_base + " AND i.return_date IS NULL ORDER BY i.due_date ASC"
        if 'reservat' in q_lower:
            return (
                f"SELECT r.*, b.title, b.author FROM Reservations r "
                f"JOIN Books b ON r.book_id = b.id "
                f"WHERE r.student_id = {sid} ORDER BY r.reservation_date DESC"
            )

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
    )


# API endpoints














# ── Role-protected routes ────────────────────────────────────────────────────













# ── JSON API endpoints ───────────────────────────────────────────────────────



























@app.route('/faculty_dashboard')
def faculty_dashboard_route():
    """Faculty dashboard – Faculty and Librarian roles."""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    role = session.get('role')
    logger.debug("Route accessed: %s", request.path)
    logger.debug("User role: %s", role)

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
        logger.error("[faculty_dashboard] DB error: %s", e)
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
    logger.debug("Route accessed: %s", request.path)
    logger.debug("User role: %s", role)

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
        logger.error("[librarian_dashboard] DB error: %s", e)
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
    redir = _require_admin()
    if redir:
        return redir

    return render_template('admin_dashboard.html', **_build_admin_dashboard_context('overview'))


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

    features = ['text_to_sql', 'multi_db']
    if _get_bool_setting('voice_input_enabled', True):
        features.append('voice_input')
    if _get_bool_setting('ai_query_enabled', True):
        features.append('ai_query')

    return jsonify({
        'role': session.get('role', 'Student'),
        'features': features,
        'settings': {
            'voice_input_enabled': _get_bool_setting('voice_input_enabled', True),
            'ai_query_enabled': _get_bool_setting('ai_query_enabled', True),
            'ollama_sql_enabled': _get_bool_setting('ollama_sql_enabled', True),
            'max_query_result_limit': _get_int_setting('max_query_result_limit', DEFAULT_QUERY_LIMIT),
        }
    })

@app.route('/api/dashboard-data')
def api_dashboard_data():
    """Get dashboard data"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    try:
        conn = get_db_connection(MAIN_DB)
        today = datetime.now().strftime('%Y-%m-%d')
        try:
            database_size = f"{round(os.path.getsize(MAIN_DB) / 1024 / 1024, 2)} MB"
        except OSError:
            database_size = 'Unavailable'

        stats = {
            'queries_today': conn.execute(
                "SELECT COUNT(*) AS cnt FROM QueryHistory WHERE timestamp LIKE ?",
                (today + '%',),
            ).fetchone()['cnt'],
            'active_users': conn.execute(
                "SELECT COUNT(*) AS cnt FROM SessionLog WHERE status = 'Active' AND logout_time IS NULL"
            ).fetchone()['cnt'],
            'database_size': database_size,
            'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        recent_queries = [
            row['query']
            for row in conn.execute(
                "SELECT query FROM QueryHistory ORDER BY datetime(timestamp) DESC, id DESC LIMIT 5"
            ).fetchall()
        ]
        conn.close()
        return jsonify({'stats': stats, 'recent_queries': recent_queries})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


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
        logger.error("[api_query_analytics] error: %s", e)
        return jsonify({'error': str(e)}), 500




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
        logger.error("[analytics] DB error: %s", e)
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
    redir = _require_admin()
    if redir:
        return redir
    return render_template('admin_dashboard.html', **_build_admin_dashboard_context('overview'))


# ── Role-protected routes ────────────────────────────────────────────────────

def _require_librarian_or_admin():
    """Return a 403 response when the logged-in user is not at least Librarian."""
    role = session.get('role', 'Student')
    if not is_staff(role):
        if 'user_id' in session:
            _log_activity(session['user_id'], f'Unauthorized access attempt: {request.path}')
            _log_security_event(
                'unauthorized_access',
                f"Role {role} attempted to access {request.path}",
                severity='high',
                user_id=session.get('user_id'),
            )
        return "Access Denied", 403
    return None


def _require_admin():
    """Return a 403 response when the logged-in user is not an Administrator."""
    if session.get('role') != 'Administrator':
        if 'user_id' in session:
            _log_activity(session['user_id'], f'Unauthorized access attempt: {request.path}')
            _log_security_event(
                'unauthorized_access',
                f"Role {session.get('role', 'Unknown')} attempted to access {request.path}",
                severity='high',
                user_id=session.get('user_id'),
            )
        return "Access Denied", 403
    return None


register_auth_routes(
    app,
    normalize_role=_normalize_role,
    record_failed_login=_record_failed_login,
    log_activity=_log_activity,
    log_security_event=_log_security_event,
    start_user_session_log=_start_user_session_log,
    end_user_session_log=_end_user_session_log,
    log_audit_event=_log_audit_event,
    get_db_connection=get_db_connection,
    main_db_getter=lambda: MAIN_DB,
)
register_query_routes(
    app,
    activity_logger=_log_activity,
    main_db_getter=lambda: MAIN_DB,
    get_db_connection=get_db_connection,
    get_bool_setting=_get_bool_setting,
    get_int_setting=_get_int_setting,
    log_audit_event=_log_audit_event,
    log_query_history=_log_query_history,
    log_security_event=_log_security_event,
)
register_admin_routes(
    app,
    main_db_getter=lambda: MAIN_DB,
    default_query_limit=DEFAULT_QUERY_LIMIT,
    role_choices=ROLE_CHOICES,
    require_admin=_require_admin,
    build_admin_dashboard_context=_build_admin_dashboard_context,
    fetch_activity_logs=_fetch_activity_logs,
    get_db_connection=get_db_connection,
    get_user_with_details=_get_user_with_details,
    normalize_role=_normalize_role,
    role_permission_scope=_role_permission_scope,
    set_setting=_set_setting,
    sync_role_profile_tables=_sync_role_profile_tables,
    validate_managed_user_form=validate_managed_user_form_service,
    validate_query_result_limit=validate_query_result_limit_service,
    log_activity=_log_activity,
    log_audit_event=_log_audit_event,
)


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
        logger.error("[students_view] DB error: %s", e)
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
    logger.debug("Route accessed: %s", request.path)
    logger.debug("User role: %s", session.get("role"))
    return redirect(url_for('fine_management_view'))


# ── JSON API endpoints ───────────────────────────────────────────────────────

@app.route('/api/students')
def api_students():
    """Return all students as JSON – librarian/admin only."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if session.get('role') not in ('Librarian', 'Faculty', 'Administrator'):
        return jsonify({'error': 'Access denied'}), 403
    logger.debug("Route accessed: %s", request.path)
    logger.debug("User role: %s", session.get("role"))
    try:
        conn = get_db_connection(MAIN_DB)
        rows = conn.execute(
            "SELECT id, roll_number, name, branch, year, email, gpa FROM Students ORDER BY name"
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        logger.error("[api_students] error: %s", e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/issued_books')
def api_issued_books():
    """Return currently issued books as JSON – librarian/admin only."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if session.get('role') not in ('Librarian', 'Faculty', 'Administrator'):
        return jsonify({'error': 'Access denied'}), 403
    logger.debug("Route accessed: %s", request.path)
    logger.debug("User role: %s", session.get("role"))
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
        logger.error("[api_issued_books] error: %s", e)
        return jsonify({'error': str(e)}), 500


@app.route('/api/fines')
def api_fines():
    """Return fines as JSON – librarian/admin only."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if session.get('role') not in ('Librarian', 'Faculty', 'Administrator'):
        return jsonify({'error': 'Access denied'}), 403
    logger.debug("Route accessed: %s", request.path)
    logger.debug("User role: %s", session.get("role"))
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
        logger.error("[api_fines] error: %s", e)
        return jsonify({'error': str(e)}), 500




















@app.route('/admin-dashboard')
def admin_dashboard():
    """Administrator dashboard."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_admin()
    if redir:
        return redir
    return redirect(url_for('admin_dashboard_route'))


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
