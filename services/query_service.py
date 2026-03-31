"""Business logic for NL-to-SQL query execution."""
import logging
import time

from flask import session

from domain_vocabulary import preprocess_query
from clarification import normalize_query_for_execution
from ollama_sql import generate_complex_sql, generate_sql
from utils.helpers import record_query_event
from utils.constants import DEFAULT_QUERY_LIMIT
from utils.sql_safety import apply_student_filters, enforce_student_filter, validate_sql_query, fallback_columns
from services.rbac_service import normalize_role, role_allows_tables, role_can_execute_queries, role_can_use_ai_queries
from services.security_service import apply_result_limit

try:
    from rbac_system_fixed import rbac, apply_row_level_filter
    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False

try:
    from security_layer import validate_sql as security_validate_sql, validate_sql_query
    SECURITY_LAYER_AVAILABLE = True
except ImportError:
    SECURITY_LAYER_AVAILABLE = False

logger = logging.getLogger(__name__)


def generate_sql_for_query(user_query: str, conn, role_name: str, get_bool_setting):
    """Generate SQL while respecting AI and role controls."""
    if not get_bool_setting('ai_query_enabled', True):
        raise PermissionError('AI query processing is currently disabled by the administrator.')
    if not role_can_execute_queries(conn, role_name):
        raise PermissionError('This role is not allowed to execute queries.')

    if not get_bool_setting('ollama_sql_enabled', True) or not role_can_use_ai_queries(conn, role_name):
        return generate_complex_sql(user_query), 'rule-based'

    try:
        return generate_sql(user_query), 'hybrid'
    except Exception as exc:
        logger.warning('Falling back to rule-based SQL generation: %s', exc)
        return generate_complex_sql(user_query), 'rule-based-fallback'


def execute_query_request(
    payload: dict,
    activity_logger,
    *,
    user_session=None,
    main_db: str,
    get_db_connection,
    get_bool_setting,
    get_int_setting,
    log_audit_event,
    log_query_history,
    log_security_event,
):
    """Process a /query POST request payload and return ``(body, status)``."""
    user_session = user_session or session
    if not user_session.get('user_id'):
        return {'error': 'Not logged in'}, 401

    query_start = time.time()
    user_query = (payload or {}).get('query', '').strip()
    user_role = user_session.get('role', 'Student')
    student_id = user_session.get('student_id')
    sql_query = ''
    query_engine = 'unknown'
    conn = None

    def finish(success: bool, *, status: int, body: dict, activity: str = None, security: tuple = None, audit: tuple = None):
        response_time = round(time.time() - query_start, 4)
        if user_query and user_session.get('user_id'):
            record_query_event(
                user_id=user_session.get('user_id'),
                role=user_role,
                user_query=user_query,
                sql_query=sql_query,
                success=success,
                response_time=response_time,
                activity_message=activity,
                audit_entry=audit,
                activity_logger=activity_logger,
                history_logger=log_query_history,
                audit_logger=log_audit_event,
            )
            if security:
                event_type, details, severity = security
                log_security_event(event_type, details, severity=severity, user_id=user_session.get('user_id'))
        return body, status

    try:
        if not user_query:
            return {'error': 'No query provided'}, 400

        user_query = normalize_query_for_execution(user_query)
        augmented_query = preprocess_query(user_query, main_db)
        conn = get_db_connection(main_db)
        sql_query, query_engine = generate_sql_for_query(augmented_query, conn, user_role, get_bool_setting)
        if not sql_query or not sql_query.strip():
            sql_query = f'SELECT * FROM Books LIMIT {DEFAULT_QUERY_LIMIT}'
            query_engine = 'rule-based'

        if user_role == 'Student' and student_id:
            sql_query = sql_query.replace('[CURRENT_STUDENT_ID]', str(int(student_id)))
            sql_query = enforce_student_filter(user_query, sql_query, user_session)

        if SECURITY_LAYER_AVAILABLE:
            allowed, sql_query, sec_error = validate_sql_query(sql_query, user_role, student_id)
            if not allowed:
                return finish(
                    False,
                    status=400,
                    body={'success': False, 'error': 'Access Denied'},
                    activity='Blocked query (security layer)',
                    security=('blocked_query', f'Security layer blocked query: {sec_error}', 'high'),
                )

        if not validate_sql_query(sql_query, user_role):
            return finish(
                False,
                status=403,
                body={'error': 'Access Denied'},
                activity='Blocked query (role validation)',
                security=('blocked_query', f"Role validation blocked query for {user_session.get('user_id')}: role={user_role}", 'high'),
            )

        allowed_tables, table_message = role_allows_tables(conn, user_role, sql_query)
        if not allowed_tables:
            return finish(
                False,
                status=403,
                body={'error': table_message},
                activity=f'Blocked query (table access): {table_message}',
                security=('blocked_query', table_message, 'high'),
            )

        max_rows = get_int_setting('max_query_result_limit', DEFAULT_QUERY_LIMIT)
        sql_query = apply_result_limit(sql_query, max_rows)

        if RBAC_AVAILABLE:
            ok, message = rbac.validate_query_access(user_session.get('user_id', ''), sql_query)
            if not ok:
                return finish(
                    False,
                    status=403,
                    body={'error': f'Access denied: {message}'},
                    activity=f'Blocked query (RBAC): {message}',
                    security=('blocked_query', f"RBAC denied query for {user_session.get('user_id')}: {message}", 'high'),
                )
            if user_role == 'Student' and student_id:
                sql_query = apply_row_level_filter(str(student_id), sql_query)

        logger.info('Executing SQL via %s: %s', query_engine, sql_query)
        rows = [dict(row) for row in conn.execute(sql_query).fetchall()]
        columns = list(rows[0].keys()) if rows else fallback_columns(sql_query)

        user_session['last_query'] = user_query
        user_session['last_sql'] = sql_query

        response_time = round(time.time() - query_start, 4)
        record_query_event(
            user_id=user_session.get('user_id'),
            role=user_role,
            user_query=user_query,
            sql_query=sql_query,
            success=True,
            response_time=response_time,
            activity_message=f'Query executed ({query_engine})',
            audit_entry=('QUERY_EXECUTION', 'SQL', f'Query: {user_query[:120]} | SQL: {sql_query[:180]}'),
            activity_logger=activity_logger,
            history_logger=log_query_history,
            audit_logger=log_audit_event,
        )
        return {
            'success': True,
            'data': rows,
            'columns': columns,
            'sql': sql_query,
            'database': main_db,
            'user_role': user_role,
            'student_id': student_id,
            'generator': query_engine,
        }, 200
    except PermissionError as exc:
        message = str(exc)
        return finish(
            False,
            status=403,
            body={'error': message},
            activity=f'Blocked query: {message}',
            security=('blocked_query', f'{normalize_role(user_role)} query blocked: {message}', 'medium'),
        )
    except Exception as exc:
        logger.error('Query execution failed: %s', exc, exc_info=True)
        body, status = finish(
            False,
            status=500,
            body={'error': f'Query execution failed: {exc}'},
            activity='Query execution failed',
        )
        body['success'] = False
        return body, status
    finally:
        if conn is not None:
            conn.close()
