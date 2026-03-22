import os
import shutil
import sqlite3
import tempfile
import unittest

import app as app_module
from werkzeug.security import check_password_hash


class RegistrationAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_main_db = app_module.MAIN_DB
        cls.temp_dir = tempfile.mkdtemp(prefix='speak2db-register-tests-')
        cls.test_db = os.path.join(cls.temp_dir, 'library_main.db')
        repo_root = os.path.dirname(os.path.abspath(__file__))
        shutil.copyfile(os.path.join(repo_root, 'library_main.db'), cls.test_db)
        app_module.MAIN_DB = cls.test_db
        app_module.app.config['TESTING'] = True
        app_module._ensure_admin_support_schema()

    @classmethod
    def tearDownClass(cls):
        app_module.MAIN_DB = cls.original_main_db
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        self.client = app_module.app.test_client()

    def test_register_creates_hashed_user_and_allows_login(self):
        response = self.client.post(
            '/register',
            data={
                'username': 'REG1001',
                'password': 'secret123',
                'role': 'Student',
                'name': 'Registered Student',
                'email': 'reg1001@example.com',
                'branch': 'CSE',
                'year': '4',
                'phone': '9999999999',
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Registration successful', response.data)

        conn = sqlite3.connect(self.test_db)
        user_row = conn.execute(
            'SELECT username, password, role, email FROM Users WHERE username = ?',
            ('REG1001',),
        ).fetchone()
        student_row = conn.execute(
            'SELECT roll_number, name, email, branch, year FROM Students WHERE roll_number = ?',
            ('REG1001',),
        ).fetchone()
        conn.close()

        self.assertIsNotNone(user_row)
        self.assertNotEqual(user_row[1], 'secret123')
        self.assertTrue(check_password_hash(user_row[1], 'secret123'))
        self.assertEqual(user_row[2], 'Student')
        self.assertEqual(user_row[3], 'reg1001@example.com')
        self.assertEqual(student_row, ('REG1001', 'Registered Student', 'reg1001@example.com', 'CSE', '4'))

        login_response = self.client.post(
            '/login',
            data={'username': 'REG1001', 'password': 'secret123'},
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertEqual(login_response.headers['Location'], '/')

    def test_register_rejects_invalid_role_and_duplicate_username(self):
        invalid_role_response = self.client.post(
            '/register',
            data={
                'username': 'bad-admin',
                'password': 'secret123',
                'role': 'Administrator',
                'email': 'bad-admin@example.com',
            },
            follow_redirects=True,
        )
        self.assertEqual(invalid_role_response.status_code, 200)
        self.assertIn(b'Please choose a valid role', invalid_role_response.data)

        first_response = self.client.post(
            '/register',
            data={
                'username': 'dup-user',
                'password': 'secret123',
                'role': 'Librarian',
                'name': 'Duplicate User',
                'email': 'dup-user@example.com',
            },
            follow_redirects=True,
        )
        self.assertEqual(first_response.status_code, 200)
        self.assertIn(b'Registration successful', first_response.data)

        duplicate_response = self.client.post(
            '/register',
            data={
                'username': 'dup-user',
                'password': 'secret123',
                'role': 'Student',
                'name': 'Another User',
                'email': 'another@example.com',
            },
            follow_redirects=True,
        )
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertIn(b'Username or email already exists.', duplicate_response.data)

        conn = sqlite3.connect(self.test_db)
        user_count = conn.execute(
            'SELECT COUNT(*) FROM Users WHERE username = ?',
            ('dup-user',),
        ).fetchone()[0]
        admin_user = conn.execute(
            'SELECT COUNT(*) FROM Users WHERE username = ?',
            ('bad-admin',),
        ).fetchone()[0]
        conn.close()

        self.assertEqual(user_count, 1)
        self.assertEqual(admin_user, 0)

    def test_register_route_available_at_auth_prefix(self):
        response = self.client.get('/auth/register')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Create a new Speak2DB account', response.data)


if __name__ == '__main__':
    unittest.main()
