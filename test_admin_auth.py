import os
import shutil
import sqlite3
import tempfile
import unittest

import app as app_module
from werkzeug.security import check_password_hash


class AdminAuthControlPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix='speak2db-tests-')
        cls.test_db = os.path.join(cls.temp_dir, 'library_main.db')
        repo_root = os.path.dirname(os.path.abspath(__file__))
        shutil.copyfile(
            os.path.join(repo_root, 'library_main.db'),
            cls.test_db,
        )
        app_module.MAIN_DB = cls.test_db
        if hasattr(app_module, 'rbac'):
            app_module.rbac.db_path = cls.test_db
        ensure_admin_schema = getattr(
            app_module,
            '_ensure_admin_schema',
            app_module._ensure_admin_support_schema,
        )
        ensure_admin_schema()
        app_module.app.config['TESTING'] = True

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        self.client = app_module.app.test_client()

    def _login_admin(self):
        response = self.client.post(
            '/login',
            data={'username': 'admin', 'password': 'pass'},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def test_register_student_creates_hashed_user_and_linked_student(self):
        response = self.client.post(
            '/register',
            data={
                'username': 'ZZ9001',
                'password': 'secret123',
                'role': 'Student',
                'name': 'Zeta Student',
                'email': 'zz9001@example.com',
                'branch': 'CSE',
                'year': '4',
                'phone': '9999999999',
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])

        conn = sqlite3.connect(self.test_db)
        user_row = conn.execute(
            "SELECT username, password, role, linked_id, full_name FROM Users WHERE username = ?",
            ('ZZ9001',),
        ).fetchone()
        self.assertIsNotNone(user_row)
        self.assertNotEqual(user_row[1], 'secret123')
        self.assertTrue(user_row[1].startswith('scrypt:') or user_row[1].startswith('pbkdf2:'))
        self.assertTrue(check_password_hash(user_row[1], 'secret123'))
        self.assertEqual(user_row[2], 'Student')
        self.assertIsNotNone(user_row[3])
        student_row = conn.execute(
            "SELECT roll_number, name, email, branch, year FROM Students WHERE id = ?",
            (user_row[3],),
        ).fetchone()
        conn.close()
        self.assertEqual(student_row[0], 'ZZ9001')
        self.assertEqual(student_row[1], 'Zeta Student')
        self.assertEqual(student_row[2], 'zz9001@example.com')
        self.assertEqual(student_row[3], 'CSE')
        self.assertEqual(student_row[4], '4')

    def test_admin_can_create_update_change_role_and_delete_user(self):
        self._login_admin()

        add_response = self.client.post(
            '/admin/add_user',
            data={
                'username': 'lib_new',
                'password': 'secret123',
                'name': 'Library New',
                'email': 'lib_new@example.com',
                'role': 'Librarian',
            },
            follow_redirects=False,
        )
        self.assertEqual(add_response.status_code, 302)

        conn = sqlite3.connect(self.test_db)
        created = conn.execute(
            "SELECT id, username, password, role FROM Users WHERE username = ?",
            ('lib_new',),
        ).fetchone()
        self.assertIsNotNone(created)
        self.assertEqual(created[3], 'Librarian')
        self.assertNotEqual(created[2], 'secret123')

        update_response = self.client.post(
            f'/admin/update_user/{created[0]}',
            data={
                'name': 'Library Updated',
                'email': 'library.updated@example.com',
                'role': 'Librarian',
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        changed = conn.execute(
            "SELECT email, full_name FROM Users WHERE id = ?",
            (created[0],),
        ).fetchone()
        self.assertEqual(changed[0], 'library.updated@example.com')
        self.assertEqual(changed[1], 'Library Updated')

        change_role_response = self.client.post(
            f'/admin/change_role/{created[0]}',
            data={
                'role': 'Faculty',
                'department': 'Research',
                'designation': 'Professor',
                'name': 'Library Updated',
            },
            follow_redirects=False,
        )
        self.assertEqual(change_role_response.status_code, 302)
        role_row = conn.execute(
            "SELECT role FROM Users WHERE id = ?",
            (created[0],),
        ).fetchone()
        self.assertEqual(role_row[0], 'Faculty')

        log_page = self.client.get('/admin/activity_logs', follow_redirects=True)
        self.assertEqual(log_page.status_code, 200)
        self.assertIn(b'Activity Logs', log_page.data)

        delete_response = self.client.post(
            f'/admin/delete_user/{created[0]}',
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)
        deleted = conn.execute(
            "SELECT id FROM Users WHERE id = ?",
            (created[0],),
        ).fetchone()
        conn.close()
        self.assertIsNone(deleted)

    def test_admin_settings_toggle_changes_ui_config(self):
        self._login_admin()
        response = self.client.post(
            '/admin/update_settings',
            data={
                'max_query_result_limit': '25',
                'ai_query_enabled': 'on',
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        config_response = self.client.get('/api/ui-config')
        self.assertEqual(config_response.status_code, 200)
        payload = config_response.get_json()
        self.assertIn('text_to_sql', payload['features'])
        self.assertNotIn('voice_input', payload['features'])

        conn = sqlite3.connect(self.test_db)
        setting_rows = dict(conn.execute(
            "SELECT setting_name, setting_value FROM SecuritySettings WHERE setting_name IN ('max_query_result_limit', 'voice_input_enabled')"
        ).fetchall())
        conn.close()
        self.assertEqual(setting_rows['max_query_result_limit'], '25')
        self.assertEqual(setting_rows['voice_input_enabled'], 'false')


if __name__ == '__main__':
    unittest.main()
