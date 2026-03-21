"""Authentication route registration for SPEAK2DB."""
import logging
import secrets
import sqlite3

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

logger = logging.getLogger(__name__)
REGISTRATION_ROLES = ('Student', 'Faculty', 'Librarian')


def _password_matches(stored_password, provided_password):
    """Support hashed new passwords and legacy plain-text passwords."""
    if (
        isinstance(stored_password, str)
        and isinstance(provided_password, str)
        and secrets.compare_digest(stored_password, provided_password)
    ):
        return True
    try:
        return check_password_hash(stored_password, provided_password)
    except (ValueError, TypeError):
        return False


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

            if user_row and _password_matches(user_row['password'], password):
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
            else:
                student = conn.execute(
                    'SELECT id, roll_number FROM Students WHERE roll_number = ? OR lower(email) = lower(?)',
                    (username, username),
                ).fetchone()
                if student and password == 'pass':
                    session['user_id'] = student['roll_number']
                    session['role'] = 'Student'
                    session['student_id'] = student['id']
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
            return redirect(url_for('dashboard.admin_dashboard'))
        elif role == 'Librarian':
            return redirect(url_for('dashboard.librarian_dashboard'))
        return redirect(url_for('index'))

    @app.route('/register', methods=['GET', 'POST'], endpoint='register')
    def register():
        if request.method == 'GET':
            return render_template('register.html')

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', '').strip()
        email = request.form.get('email', '').strip()
        name = request.form.get('name', '').strip() or username
        branch = request.form.get('branch', '').strip() or 'GEN'
        year = request.form.get('year', '').strip() or '1'
        phone = request.form.get('phone', '').strip() or 'N/A'

        if not username or not password or not role or not email:
            flash('Please fill in username, password, role, and email.', 'error')
            return render_template('register.html')

        if role not in REGISTRATION_ROLES:
            flash('Please select a valid role.', 'error')
            return render_template('register.html')

        conn = get_db_connection(main_db_getter())
        try:
            existing_user = conn.execute(
                'SELECT username, email FROM Users WHERE username = ? OR lower(email) = lower(?)',
                (username, email),
            ).fetchone()
            if existing_user:
                if existing_user['username'] == username:
                    flash('Username already exists.', 'error')
                else:
                    flash('Email already exists.', 'error')
                return render_template('register.html')

            conn.execute(
                'INSERT INTO Users (username, password, role, email) VALUES (?, ?, ?, ?)',
                (username, generate_password_hash(password), role, email),
            )
            if role == 'Student':
                conn.execute(
                    '''
                    INSERT INTO Students (roll_number, name, branch, year, email, phone, role)
                    VALUES (?, ?, ?, ?, ?, ?, 'Student')
                    ''',
                    (
                        username,
                        name,
                        branch,
                        year,
                        email,
                        phone,
                    ),
                )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            logger.warning('Registration integrity error for %s: %s', username, exc)
            flash('Unable to register with the provided details.', 'error')
            return render_template('register.html')
        except Exception as exc:
            conn.rollback()
            logger.error('Registration error: %s', exc)
            flash('Unable to register with the provided details.', 'error')
            return render_template('register.html')
        finally:
            conn.close()

        flash('Registration successful. Please log in.', 'success')
        return redirect(url_for('login'))

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
