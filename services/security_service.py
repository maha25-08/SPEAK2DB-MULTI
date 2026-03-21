"""Security and settings helpers for SPEAK2DB."""
import logging
import os
import re
import sqlite3
from datetime import datetime

from flask import request, session

from db.connection import MAIN_DB
from services.rbac_service import normalize_role

logger = logging.getLogger(__name__)
_LIMIT_PATTERN = re.compile(r'\bLIMIT\s+(\d+)(?:\s+OFFSET\s+\d+)?\b', re.IGNORECASE)


def request_ip() -> str:
    """Best-effort request IP address."""
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def request_user_agent() -> str:
    """Best-effort request user agent."""
    return request.headers.get('User-Agent', 'unknown')


def get_setting(name: str, default: str = '') -> str:
    """Read a system setting from SecuritySettings."""
    try:
        conn = sqlite3.connect(MAIN_DB)
        row = conn.execute(
            'SELECT setting_value FROM SecuritySettings WHERE setting_name = ?',
            (name,),
        ).fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default


def get_bool_setting(name: str, default: bool = False) -> bool:
    """Read a boolean system setting."""
    value = get_setting(name, 'true' if default else 'false')
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def get_int_setting(name: str, default: int) -> int:
    """Read an integer setting with a safe fallback."""
    raw_value = get_setting(name, str(default))
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        logger.warning("Invalid integer setting %s=%r; using %s", name, raw_value, default)
        return default


def set_setting(name: str, value: str, updated_by: str = None, description: str = None):
    """Insert or update a setting value in ``SecuritySettings``."""
    updated_by = updated_by or session.get('user_id', 'system')
    conn = sqlite3.connect(MAIN_DB)
    cursor = conn.cursor()
    existing = cursor.execute(
        'SELECT id FROM SecuritySettings WHERE setting_name = ?',
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


def log_activity(user_id: str, action: str):
    """Write a compact activity log entry."""
    try:
        conn = sqlite3.connect(MAIN_DB)
        conn.execute(
            'INSERT INTO ActivityLogs (user_id, action, timestamp) VALUES (?, ?, ?)',
            (user_id, action, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error('Activity log write failed: %s', exc)


def log_audit_event(user_id: str, role: str, action: str, resource_type: str, details: str, success: bool = True):
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
                normalize_role(role),
                action,
                resource_type,
                details,
                request_ip(),
                request_user_agent(),
                datetime.now().isoformat(),
                1 if success else 0,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error('Audit log write failed: %s', exc)


def log_security_event(event_type: str, details: str, severity: str = 'medium', user_id: str = None):
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
                request_ip(),
                request_user_agent(),
                user_id,
                session.get('audit_session_id'),
                datetime.now().isoformat(),
                severity,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error('Security log write failed: %s', exc)


def record_failed_login(username: str, reason: str):
    """Persist a failed login attempt for admin monitoring."""
    try:
        conn = sqlite3.connect(MAIN_DB)
        conn.execute(
            '''
            INSERT INTO FailedLoginAttempts (username, ip_address, user_agent, attempt_time, failure_reason, blocked)
            VALUES (?, ?, ?, ?, ?, 0)
            ''',
            (username, request_ip(), request_user_agent(), datetime.now().isoformat(), reason),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error('Failed-login record write failed: %s', exc)


def start_user_session_log(user_id: str, role: str):
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
                normalize_role(role),
                session.get('audit_session_id'),
                datetime.now().isoformat(),
                request_ip(),
                request_user_agent(),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error('Session log write failed: %s', exc)


def end_user_session_log():
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
        logger.error('Session log logout update failed: %s', exc)


def log_query_history(user_id: str, role: str, user_query: str, sql_query: str, success: bool, response_time: float = None):
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
                normalize_role(role),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.error('Query history write failed: %s', exc)


def apply_result_limit(sql_query: str, max_rows: int) -> str:
    """Cap query results with a configurable LIMIT."""
    if not sql_query or max_rows <= 0:
        return sql_query
    limit_match = _LIMIT_PATTERN.search(sql_query)
    if not limit_match:
        return sql_query.rstrip().rstrip(';') + f' LIMIT {max_rows}'
    current_limit = int(limit_match.group(1))
    if current_limit <= max_rows:
        return sql_query
    return _LIMIT_PATTERN.sub(
        lambda match: match.group(0).replace(match.group(1), str(max_rows), 1),
        sql_query,
        count=1,
    )
