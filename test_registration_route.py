import os
import shutil
import sqlite3
import tempfile
import unittest

import app as app_module
from werkzeug.security import check_password_hash


class RegistrationRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_main_db = app_module.MAIN_DB
        cls.temp_dir = tempfile.mkdtemp(prefix='speak2db-register-')
        cls.test_db = os.path.join(cls.temp_dir, 'library_main.db')
        repo_root = os.path.dirname(os.path.abspath(__file__))
        shutil.copyfile(
            os.path.join(repo_root, 'library_main.db'),
            cls.test_db,
        )
        app_module.MAIN_DB = cls.test_db
        app_module.app.config['TESTING'] = True

    @classmethod
    def tearDownClass(cls):
        app_module.MAIN_DB = cls.original_main_db
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        self.client = app_module.app.test_client()

    def test_register_get_renders_page(self):
        response = self.client.get('/register')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Register', response.data)

    def test_register_student_creates_user_and_allows_login(self):
        response = self.client.post(
            '/register',
            data={
                'username': 'ZZ9001',
                'password': 'secret123',
                'role': 'Student',
                'email': 'zz9001@example.com',
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])

        conn = sqlite3.connect(self.test_db)
        user_row = conn.execute(
            'SELECT username, password, role, email FROM Users WHERE username = ?',
            ('ZZ9001',),
        ).fetchone()
        student_row = conn.execute(
            'SELECT roll_number, email, role FROM Students WHERE roll_number = ?',
            ('ZZ9001',),
        ).fetchone()
        conn.close()

        self.assertEqual(user_row[0], 'ZZ9001')
        self.assertNotEqual(user_row[1], 'secret123')
        self.assertTrue(check_password_hash(user_row[1], 'secret123'))
        self.assertEqual(user_row[2:], ('Student', 'zz9001@example.com'))
        self.assertEqual(student_row, ('ZZ9001', 'zz9001@example.com', 'Student'))

        login_response = self.client.post(
            '/login',
            data={'username': 'ZZ9001', 'password': 'secret123'},
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 302)

    def test_register_rejects_administrator_role(self):
        response = self.client.post(
            '/register',
            data={
                'username': 'admin2',
                'password': 'secret123',
                'role': 'Administrator',
                'email': 'admin2@example.com',
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Please select a valid role.', response.data)

        conn = sqlite3.connect(self.test_db)
        user_row = conn.execute(
            'SELECT username FROM Users WHERE username = ?',
            ('admin2',),
        ).fetchone()
        conn.close()
        self.assertIsNone(user_row)

    def test_register_handles_duplicate_username(self):
        first_response = self.client.post(
            '/register',
            data={
                'username': 'dupuser',
                'password': 'secret123',
                'role': 'Student',
                'email': 'dupuser@example.com',
            },
            follow_redirects=True,
        )
        self.assertEqual(first_response.status_code, 200)

        response = self.client.post(
            '/register',
            data={
                'username': 'dupuser',
                'password': 'secret123',
                'role': 'Student',
                'email': 'another@example.com',
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Username already exists.', response.data)


if __name__ == '__main__':
    unittest.main()
