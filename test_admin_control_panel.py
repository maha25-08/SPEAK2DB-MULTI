import shutil
import sqlite3
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash

import app as app_module
from rbac_system_fixed import rbac


REPO_ROOT = Path(__file__).resolve().parent


@pytest.fixture()
def client(tmp_path, monkeypatch):
    main_db = tmp_path / 'library_main.db'
    archive_db = tmp_path / 'library_archive.db'
    shutil.copy(REPO_ROOT / 'library_main.db', main_db)
    shutil.copy(REPO_ROOT / 'library_archive.db', archive_db)

    monkeypatch.setattr(app_module, 'MAIN_DB', str(main_db))
    monkeypatch.setattr(app_module, 'ARCHIVE_DB', str(archive_db))
    rbac.db_path = str(main_db)

    app_module.app.config.update(TESTING=True)
    app_module._ensure_query_history_schema()
    app_module._ensure_admin_support_schema()

    with app_module.app.test_client() as test_client:
        yield test_client, main_db


def login_as_admin(test_client):
    with test_client.session_transaction() as sess:
        sess['user_id'] = 'admin'
        sess['role'] = 'Administrator'
        sess['student_id'] = None


def login_as_student(test_client, student_id=1, user_id='MT3001'):
    with test_client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['role'] = 'Student'
        sess['student_id'] = student_id


def test_admin_can_add_update_and_change_role_for_user(client):
    test_client, db_path = client
    login_as_admin(test_client)

    add_response = test_client.post(
        '/admin/add_user',
        data={
            'username': 'NEW1001',
            'name': 'New Student',
            'email': 'new1001@example.com',
            'password': 'pass',
            'role': 'Student',
            'branch': 'CSE',
            'year': '2',
            'phone': '9999999999',
        },
        follow_redirects=False,
    )
    assert add_response.status_code == 302

    conn = sqlite3.connect(db_path)
    user_row = conn.execute(
        "SELECT id, username, password, role, email FROM Users WHERE username = 'NEW1001'"
    ).fetchone()
    student_row = conn.execute(
        "SELECT name, branch, year FROM Students WHERE roll_number = 'NEW1001'"
    ).fetchone()
    assert user_row is not None
    assert user_row[3] == 'Student'
    assert user_row[2] != 'pass'
    assert check_password_hash(user_row[2], 'pass')
    assert student_row == ('New Student', 'CSE', '2')

    update_response = test_client.post(
        f'/admin/update_user/{user_row[0]}',
        data={
            'username': 'NEW1001',
            'name': 'Updated Student',
            'email': 'updated1001@example.com',
            'role': 'Student',
            'branch': 'IT',
            'year': '3',
            'phone': '8888888888',
        },
        follow_redirects=False,
    )
    assert update_response.status_code == 302

    change_role_response = test_client.post(
        f'/admin/change_role/{user_row[0]}',
        data={
            'role': 'Faculty',
            'name': 'Updated Student',
            'email': 'updated1001@example.com',
            'department': 'Computer Science',
            'designation': 'Assistant Professor',
            'phone': '8888888888',
        },
        follow_redirects=False,
    )
    assert change_role_response.status_code == 302

    updated_user = conn.execute(
        "SELECT role, email FROM Users WHERE id = ?",
        (user_row[0],),
    ).fetchone()
    faculty_row = conn.execute(
        "SELECT name, department, designation FROM Faculty WHERE email = 'updated1001@example.com'"
    ).fetchone()
    removed_student = conn.execute(
        "SELECT 1 FROM Students WHERE roll_number = 'NEW1001' OR email = 'updated1001@example.com'"
    ).fetchone()
    activity_log = conn.execute(
        "SELECT action FROM ActivityLogs WHERE action LIKE 'Role changed:%' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    assert updated_user == ('Faculty', 'updated1001@example.com')
    assert faculty_row == ('Updated Student', 'Computer Science', 'Assistant Professor')
    assert removed_student is None
    assert activity_log is not None


def test_login_migrates_plaintext_passwords_and_admin_role(client):
    test_client, db_path = client

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO Users (username, password, role, email) VALUES (?, ?, ?, ?)",
        ('legacyadmin', 'legacypass', 'Admin', 'legacyadmin@example.com'),
    )
    conn.commit()
    conn.close()

    app_module._ensure_admin_support_schema()

    conn = sqlite3.connect(db_path)
    migrated_user = conn.execute(
        "SELECT password, role FROM Users WHERE username = ?",
        ('legacyadmin',),
    ).fetchone()
    conn.close()

    assert migrated_user is not None
    assert migrated_user[1] == 'Administrator'
    assert migrated_user[0] != 'legacypass'
    assert check_password_hash(migrated_user[0], 'legacypass')

    response = test_client.post(
        '/login',
        data={'username': 'legacyadmin', 'password': 'legacypass'},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/admin_dashboard')
    with test_client.session_transaction() as sess:
        assert sess['user_id'] == 'legacyadmin'
        assert sess['role'] == 'Administrator'


def test_admin_settings_drive_query_limit_and_logs_api(client):
    test_client, db_path = client
    login_as_admin(test_client)

    settings_response = test_client.post(
        '/admin/update_settings',
        data={
            'max_query_result_limit': '5',
            'voice_input_enabled': '',
            'ai_query_enabled': 'on',
            'ollama_sql_enabled': '',
        },
        follow_redirects=False,
    )
    assert settings_response.status_code == 302

    query_response = test_client.post('/query', json={'query': 'show all books with title and author'})
    assert query_response.status_code == 200
    payload = query_response.get_json()
    assert payload['success'] is True
    assert payload['generator'] == 'rule-based'
    assert len(payload['data']) <= 5
    assert 'LIMIT 5' in payload['sql'].upper()

    logs_response = test_client.get('/admin/activity_logs')
    assert logs_response.status_code == 200
    logs_payload = logs_response.get_json()
    assert logs_payload['success'] is True
    assert any('System settings updated' in entry['action'] for entry in logs_payload['logs'])

    conn = sqlite3.connect(db_path)
    settings = dict(conn.execute(
        "SELECT setting_name, setting_value FROM SecuritySettings WHERE setting_name IN ('max_query_result_limit', 'voice_input_enabled', 'ollama_sql_enabled')"
    ).fetchall())
    conn.close()
    assert settings['max_query_result_limit'] == '5'
    assert settings['voice_input_enabled'] == 'false'
    assert settings['ollama_sql_enabled'] == 'false'


def test_role_permission_update_can_block_student_queries(client):
    test_client, db_path = client
    login_as_admin(test_client)

    # Revoke all Student role permissions, including execute_queries
    update_permissions = test_client.post(
        '/admin/update_permissions/Student',
        data={},
        follow_redirects=False,
    )
    assert update_permissions.status_code == 302

    login_as_student(test_client)
    blocked_response = test_client.post('/query', json={'query': 'show all books with title and author'})
    assert blocked_response.status_code == 403
    assert 'not allowed to execute queries' in blocked_response.get_json()['error'].lower()

    conn = sqlite3.connect(db_path)
    security_event = conn.execute(
        "SELECT event_type, details FROM SecurityLog WHERE event_type = 'blocked_query' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert security_event is not None


def test_ai_disable_setting_blocks_queries(client):
    test_client, _ = client
    login_as_admin(test_client)

    update_response = test_client.post(
        '/admin/update_settings',
        data={
            'max_query_result_limit': '10',
            'voice_input_enabled': 'on',
            'ollama_sql_enabled': 'on',
        },
        follow_redirects=False,
    )
    assert update_response.status_code == 302

    blocked_response = test_client.post('/query', json={'query': 'show all books with title and author'})
    assert blocked_response.status_code == 403
    assert 'disabled by the administrator' in blocked_response.get_json()['error'].lower()
