"""Authentication route registration for SPEAK2DB."""
import logging
import re
import sqlite3

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from security.auth_utils import verify_stored_password

logger = logging.getLogger(__name__)
_EMAIL_PATTERN = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
DEFAULT_STUDENT_BRANCH = 'GEN'
DEFAULT_STUDENT_YEAR = '1'
DEFAULT_STUDENT_PHONE = ''


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

    allowed_registration_roles = {'Student', 'Faculty', 'Librarian'}

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

    @app.route('/register', methods=['GET', 'POST'], endpoint='register')
    def register():
        if request.method == 'GET':
            return render_template('register.html')

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        email = request.form.get('email', '').strip().lower()
        role = normalize_role(request.form.get('role', '').strip())

        if not username or not password or not email or not role:
            flash('All fields are required.', 'error')
            return render_template('register.html')
        if not _EMAIL_PATTERN.match(email):
            flash('Please enter a valid email address.', 'error')
            return render_template('register.html')
        if role not in allowed_registration_roles:
            flash('Please choose a valid role.', 'error')
            return render_template('register.html')

        conn = get_db_connection(main_db_getter())
        try:
            existing_user = conn.execute(
                'SELECT 1 FROM Users WHERE username = ? OR email = ?',
                (username, email),
            ).fetchone()
            if existing_user:
                flash('Username or email already exists.', 'error')
                return render_template('register.html')

            conn.execute(
                'INSERT INTO Users (username, password, role, email) VALUES (?, ?, ?, ?)',
                (username, generate_password_hash(password), role, email),
            )
            if role == 'Student':
                student_name = username
                conn.execute(
                    '''
                    INSERT INTO Students (roll_number, name, branch, year, email, phone, role)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (username, student_name, DEFAULT_STUDENT_BRANCH, DEFAULT_STUDENT_YEAR, email, DEFAULT_STUDENT_PHONE, role),
                )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            logger.warning('Registration failed for %s: %s', username, exc)
            flash('Username or email already exists.', 'error')
            return render_template('register.html')
        except Exception as exc:
            conn.rollback()
            logger.error('Registration error for %s: %s', username, exc)
            flash('Unable to create account right now.', 'error')
            return render_template('register.html')
        finally:
            conn.close()

        flash('Registration successful. Please sign in.', 'success')
        return redirect(url_for('login'))

    @app.route('/register/student', methods=['GET', 'POST'], endpoint='register_student')
    def register_student():
        if request.method == 'GET':
            return render_template('register_student.html')

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        email = request.form.get('email', '').strip().lower()
        full_name = request.form.get('full_name', '').strip()
        branch = request.form.get('branch', '').strip()
        year = request.form.get('year', '').strip()

        if not username or not password or not email or not full_name or not branch or not year:
            flash('All fields are required.', 'error')
            return render_template('register_student.html')
        if not _EMAIL_PATTERN.match(email):
            flash('Please enter a valid email address.', 'error')
            return render_template('register_student.html')

        conn = get_db_connection(main_db_getter())
        try:
            existing_user = conn.execute(
                'SELECT 1 FROM Users WHERE username = ? OR email = ?',
                (username, email),
            ).fetchone()
            if existing_user:
                flash('Username or email already exists.', 'error')
                return render_template('register_student.html')

            conn.execute(
                'INSERT INTO Users (username, password, role, email) VALUES (?, ?, ?, ?)',
                (username, generate_password_hash(password), 'Student', email),
            )
            conn.execute(
                '''
                INSERT INTO Students (roll_number, name, branch, year, email, phone, role)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                (username, full_name, branch, year, email, DEFAULT_STUDENT_PHONE, 'Student'),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            logger.warning('Student registration failed for %s: %s', username, exc)
            flash('Username or email already exists.', 'error')
            return render_template('register_student.html')
        except Exception as exc:
            conn.rollback()
            logger.error('Student registration error for %s: %s', username, exc)
            flash('Unable to create account right now.', 'error')
            return render_template('register_student.html')
        finally:
            conn.close()

        flash('Registration successful. Please sign in.', 'success')
        return redirect(url_for('login'))

    @app.route('/register/faculty', methods=['GET', 'POST'], endpoint='register_faculty')
    def register_faculty():
        if request.method == 'GET':
            return render_template('register_faculty.html')

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        email = request.form.get('email', '').strip().lower()
        full_name = request.form.get('full_name', '').strip()
        department = request.form.get('department', '').strip()
        designation = request.form.get('designation', '').strip()
        specialization = request.form.get('specialization', '').strip()

        if not username or not password or not email or not full_name or not department or not designation or not specialization:
            flash('All fields are required.', 'error')
            return render_template('register_faculty.html')
        if not _EMAIL_PATTERN.match(email):
            flash('Please enter a valid email address.', 'error')
            return render_template('register_faculty.html')

        conn = get_db_connection(main_db_getter())
        try:
            existing_user = conn.execute(
                'SELECT 1 FROM Users WHERE username = ? OR email = ?',
                (username, email),
            ).fetchone()
            if existing_user:
                flash('Username or email already exists.', 'error')
                return render_template('register_faculty.html')

            conn.execute(
                'INSERT INTO Users (username, password, role, email) VALUES (?, ?, ?, ?)',
                (username, generate_password_hash(password), 'Faculty', email),
            )
            conn.execute(
                '''
                INSERT INTO Faculty (name, email, department, designation, specialization)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (full_name, email, department, designation, specialization),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            logger.warning('Faculty registration failed for %s: %s', username, exc)
            flash('Username or email already exists.', 'error')
            return render_template('register_faculty.html')
        except Exception as exc:
            conn.rollback()
            logger.error('Faculty registration error for %s: %s', username, exc)
            flash('Unable to create account right now.', 'error')
            return render_template('register_faculty.html')
        finally:
            conn.close()

        flash('Registration successful. Please sign in.', 'success')
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
