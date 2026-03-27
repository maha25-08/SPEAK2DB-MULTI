"""
Role-Based Access Control helpers for SPEAK2DB.

Provides the ``role_required`` decorator used to protect routes.
"""
from functools import wraps

from flask import jsonify, redirect, request, session, url_for


def _is_api_request() -> bool:
    return request.blueprint == 'api' or request.path.startswith('/api/')


def role_required(roles):
    """Protect a route so only users with one of the specified roles may access it.

    Args:
        roles: A list (or single string) of permitted role names, e.g. ["student"]
               or ["Student"].  Role comparison is case-insensitive.

    Behaviour:
        * If the user is not logged in → redirect to /login (or 401 for API).
        * If the user has the wrong role → return 403.
    """
    if isinstance(roles, str):
        roles = [roles]
    allowed_roles = {r.strip().lower() for r in roles}

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not session.get('user_id'):
                if _is_api_request():
                    return jsonify({'success': False, 'error': 'Not logged in'}), 401
                return redirect(url_for('login'))

            current_role = (session.get('role') or '').strip().lower()
            if allowed_roles and current_role not in allowed_roles:
                if _is_api_request():
                    return jsonify({'success': False, 'error': 'Access denied'}), 403
                return 'Access Denied', 403

            return view_func(*args, **kwargs)

        return wrapped

    return decorator
