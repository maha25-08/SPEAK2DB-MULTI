from functools import wraps

from flask import jsonify, redirect, request, session, url_for


def _is_api_request() -> bool:
    return request.blueprint == 'api' or request.path.startswith('/api/')


def require_roles(*roles):
    """Require an authenticated session with one of the allowed roles."""
    allowed_roles = tuple(roles)

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not session.get('user_id'):
                if _is_api_request():
                    return jsonify({'success': False, 'error': 'Not logged in'}), 401
                return redirect(url_for('login'))

            current_role = session.get('role')
            if allowed_roles and current_role not in allowed_roles:
                if _is_api_request():
                    return jsonify({'success': False, 'error': 'Access denied'}), 403
                return 'Access Denied', 403

            return view_func(*args, **kwargs)

        return wrapped

    return decorator
