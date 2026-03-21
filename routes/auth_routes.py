"""Authentication route registration for SPEAK2DB."""
import logging

from flask import flash, redirect, render_template, request, session, url_for

from security.auth_utils import verify_stored_password

logger = logging.getLogger(__name__)


def register_auth_routes(
    app,
    *,
    normalize_role,
    record_failed_login,
    log_activity,
    log_security_event,
    start_user_session_log,
    end_user_session_log,
    log_audit_event,
    get_db_connection,
    main_db_getter,
):
    """Register login/logout routes on the Flask app."""

    @app.route('/login', methods=['GET', 'POST'], endpoint='login')
    def login():
        if request.method == 'GET':
            return render_template('login.html')

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash('Please enter username and password', 'error')
            return render_template('login.html')

        authenticated = False
        try:
            conn = get_db_connection(main_db_getter())
            user_row = conn.execute(
                'SELECT username, password, role, email FROM Users WHERE username = ? OR lower(email) = lower(?)',
                (username, username),
            ).fetchone()

            if user_row and verify_stored_password(user_row['password'], password):
                normalized_role = normalize_role(user_row['role'])
                session['user_id'] = user_row['username']
                session['role'] = normalized_role
                session['student_id'] = None
                if normalized_role == 'Student':
                    student_row = conn.execute(
                        'SELECT id FROM Students WHERE roll_number = ? OR lower(email) = lower(?)',
                        (user_row['username'], user_row['email']),
                    ).fetchone()
                    session['student_id'] = student_row['id'] if student_row else None
                authenticated = True
            conn.close()
        except Exception as exc:
            logger.error('Authentication error: %s', exc)

        if not authenticated:
            record_failed_login(username, 'Invalid username or password')
            log_activity(username, 'Login failed')
            log_security_event('failed_login', f'Login failed for {username}', severity='high', user_id=username)
            flash('Invalid username or password', 'error')
            return render_template('login.html')

        start_user_session_log(session.get('user_id'), session.get('role', 'Student'))
        log_activity(session.get('user_id'), 'Login')
        log_audit_event(session.get('user_id'), session.get('role', 'Student'), 'LOGIN', 'SESSION', 'User logged in', success=True)
        flash(f"Welcome, {session.get('role', 'Student')}!", 'success')
        role = session.get('role', 'Student')
        if role == 'Administrator':
            return redirect(url_for('admin_dashboard_route'))
        if role == 'Librarian':
            return redirect(url_for('librarian_dashboard_route'))
        if role == 'Faculty':
            return redirect(url_for('faculty_dashboard_route'))
        return redirect(url_for('index'))

    @app.route('/logout', endpoint='logout')
    def logout():
        user_id = session.get('user_id')
        user_role = session.get('role', 'Student')
        if user_id:
            end_user_session_log()
            log_activity(user_id, 'Logout')
            log_audit_event(user_id, user_role, 'LOGOUT', 'SESSION', 'User logged out', success=True)
        session.clear()
        flash('You have been logged out.', 'info')
        return redirect(url_for('login'))
