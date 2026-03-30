import os
import shutil
import sqlite3
import tempfile
import unittest

import app as app_module
from flask import url_for


class RoleDashboardRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix='speak2db-role-routing-')
        cls.test_db = os.path.join(cls.temp_dir, 'library_main.db')
        repo_root = os.path.dirname(os.path.abspath(__file__))
        cls.original_main_db = app_module.MAIN_DB
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
        app_module.MAIN_DB = cls.original_main_db
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        self.client = app_module.app.test_client()

    def test_named_dashboard_endpoints_build_expected_paths(self):
        with app_module.app.test_request_context():
            self.assertEqual(url_for('admin_dashboard_route'), '/admin_dashboard')
            self.assertEqual(url_for('librarian_dashboard_route'), '/librarian_dashboard')
            self.assertEqual(url_for('faculty_dashboard_route'), '/faculty_dashboard')
            self.assertIs(
                app_module.app.view_functions['admin_dashboard_route'],
                app_module.app.view_functions['dashboard.admin_dashboard'],
            )
            self.assertIs(
                app_module.app.view_functions['librarian_dashboard_route'],
                app_module.app.view_functions['dashboard.librarian_dashboard'],
            )
            self.assertIs(
                app_module.app.view_functions['faculty_dashboard_route'],
                app_module.app.view_functions['dashboard.faculty_dashboard'],
            )

    def test_login_redirects_by_role(self):
        credentials = [
            ('admin', 'pass', '/admin_dashboard'),
            ('librarian', 'pass', '/librarian_dashboard'),
            ('faculty', 'pass', '/faculty_dashboard'),
            ('MT3001', 'pass', '/'),
        ]

        for username, password, expected_location in credentials:
            with self.subTest(username=username):
                response = self.client.post(
                    '/login',
                    data={'username': username, 'password': password},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.headers['Location'].endswith(expected_location))

    def test_librarian_dashboard_renders_expected_content_for_librarian_role(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'librarian'
            sess['role'] = 'Librarian'

        response = self.client.get('/librarian_dashboard')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Librarian Dashboard', response.data)
        self.assertIn(b'Welcome librarian', response.data)
        self.assertIn(b'Total Books:', response.data)
        self.assertIn(b'Recent Issues', response.data)

    def test_student_profile_without_user_credentials_cannot_use_demo_bypass(self):
        conn = sqlite3.connect(self.test_db)
        conn.execute("DELETE FROM Users WHERE username = ?", ('MT3001',))
        conn.commit()
        conn.close()

        response = self.client.post(
            '/login',
            data={'username': 'MT3001', 'password': 'pass'},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Invalid username or password', response.data)


if __name__ == '__main__':
    unittest.main()
