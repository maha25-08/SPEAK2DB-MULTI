from flask import flash, render_template

import app as app_module
from services.security_service import apply_result_limit
from utils.constants import DEFAULT_QUERY_LIMIT
from utils.sql_safety import ensure_limit


def test_login_template_renders_categorized_flash_messages():
    with app_module.app.test_request_context('/login'):
        flash('Welcome, Administrator!', 'success')
        flash('Invalid username or password', 'error')

        html = render_template('login.html')

    assert 'flash-message success' in html
    assert 'flash-message error' in html
    assert 'Welcome, Administrator!' in html
    assert 'Invalid username or password' in html


def test_register_template_renders_categorized_flash_messages():
    with app_module.app.test_request_context('/register'):
        flash('Account created successfully.', 'success')
        flash('Email is required.', 'error')

        html = render_template('register.html')

    assert 'flash-message success' in html
    assert 'flash-message error' in html
    assert 'Account created successfully.' in html
    assert 'Email is required.' in html


def test_admin_dashboard_decorator_blocks_non_admin_users():
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 'MT3001'
            sess['role'] = 'Student'
            sess['student_id'] = 1

        response = client.get('/admin_dashboard')

    assert response.status_code == 403
    assert b'Unauthorized' in response.data


def test_api_students_decorator_handles_authentication_and_allowed_roles():
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        unauthenticated = client.get('/api/students')
        assert unauthenticated.status_code == 401
        assert unauthenticated.get_json() == {'success': False, 'error': 'Not logged in'}

        with client.session_transaction() as sess:
            sess['user_id'] = 'MT3001'
            sess['role'] = 'Student'
            sess['student_id'] = 1

        forbidden = client.get('/api/students')
        assert forbidden.status_code == 403
        assert forbidden.get_json() == {'success': False, 'error': 'Access denied'}

        with client.session_transaction() as sess:
            sess['user_id'] = 'faculty'
            sess['role'] = 'Faculty'
            sess['student_id'] = None

        allowed = client.get('/api/students')

    assert allowed.status_code == 200
    payload = allowed.get_json()
    assert payload['success'] is True
    assert isinstance(payload['data'], list)


def test_student_only_route_requires_explicit_role():
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 'MT3001'
            sess['student_id'] = 1

        response = client.get('/student_dashboard')

    assert response.status_code == 403
    assert b'Access Denied' in response.data


def test_select_queries_use_default_query_limit_when_missing_or_excessive():
    assert ensure_limit('SELECT * FROM Books') == f'SELECT * FROM Books LIMIT {DEFAULT_QUERY_LIMIT}'
    assert (
        ensure_limit('SELECT * FROM Books LIMIT 500')
        == f'SELECT * FROM Books LIMIT {DEFAULT_QUERY_LIMIT}'
    )
    assert (
        ensure_limit('SELECT * FROM Books LIMIT 500 OFFSET 10')
        == f'SELECT * FROM Books LIMIT {DEFAULT_QUERY_LIMIT} OFFSET 10'
    )
    assert (
        apply_result_limit('SELECT * FROM Books LIMIT 500', DEFAULT_QUERY_LIMIT)
        == f'SELECT * FROM Books LIMIT {DEFAULT_QUERY_LIMIT}'
    )
    assert (
        apply_result_limit('SELECT * FROM Books LIMIT 500 OFFSET 10', DEFAULT_QUERY_LIMIT)
        == f'SELECT * FROM Books LIMIT {DEFAULT_QUERY_LIMIT} OFFSET 10'
    )
