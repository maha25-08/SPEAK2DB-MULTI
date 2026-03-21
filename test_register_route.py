import os
import shutil
import sqlite3
import tempfile
import unittest

import app as app_module
from werkzeug.security import check_password_hash


class RegisterRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='speak2db-register-')
        self.test_db = os.path.join(self.temp_dir, 'library_main.db')
        repo_root = os.path.dirname(os.path.abspath(__file__))
        shutil.copyfile(
            os.path.join(repo_root, 'library_main.db'),
            self.test_db,
        )
        self.original_main_db = app_module.MAIN_DB
        app_module.MAIN_DB = self.test_db
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.MAIN_DB = self.original_main_db
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_register_get_renders_form_without_administrator_option(self):
        response = self.client.get('/register')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<form method="POST" action="/register">', response.data)
        self.assertIn(b'name="username"', response.data)
        self.assertIn(b'name="email"', response.data)
        self.assertIn(b'name="password"', response.data)
        self.assertIn(b'<option>Student</option>', response.data)
        self.assertIn(b'<option>Faculty</option>', response.data)
        self.assertIn(b'<option>Librarian</option>', response.data)
        self.assertNotIn(b'Administrator', response.data)

    def test_register_student_creates_user_student_and_allows_login(self):
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
            'SELECT roll_number, name, branch, year, email, phone, role FROM Students WHERE roll_number = ?',
            ('ZZ9001',),
        ).fetchone()
        conn.close()

        self.assertEqual(user_row[0], 'ZZ9001')
        self.assertNotEqual(user_row[1], 'secret123')
        self.assertTrue(check_password_hash(user_row[1], 'secret123'))
        self.assertEqual(user_row[2:], ('Student', 'zz9001@example.com'))
        self.assertEqual(student_row, ('ZZ9001', 'ZZ9001', 'GEN', '1', 'zz9001@example.com', '', 'Student'))

        login_response = self.client.post(
            '/login',
            data={'username': 'ZZ9001', 'password': 'secret123'},
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 302)

    def test_register_rejects_invalid_or_duplicate_values(self):
        invalid_role = self.client.post(
            '/register',
            data={
                'username': 'eviladmin',
                'password': 'pass123',
                'role': 'Administrator',
                'email': 'eviladmin@example.com',
            },
            follow_redirects=True,
        )
        self.assertEqual(invalid_role.status_code, 200)
        self.assertIn(b'Please choose a valid role.', invalid_role.data)

        missing_email = self.client.post(
            '/register',
            data={
                'username': 'missingmail',
                'password': 'pass123',
                'role': 'Faculty',
                'email': '',
            },
            follow_redirects=True,
        )
        self.assertEqual(missing_email.status_code, 200)
        self.assertIn(b'All fields are required.', missing_email.data)

        invalid_email = self.client.post(
            '/register',
            data={
                'username': 'bademail',
                'password': 'pass123',
                'role': 'Faculty',
                'email': 'not-an-email',
            },
            follow_redirects=True,
        )
        self.assertEqual(invalid_email.status_code, 200)
        self.assertIn(b'Please enter a valid email address.', invalid_email.data)

        duplicate = self.client.post(
            '/register',
            data={
                'username': 'admin',
                'password': 'pass123',
                'role': 'Faculty',
                'email': 'new-admin@example.com',
            },
            follow_redirects=True,
        )
        self.assertEqual(duplicate.status_code, 200)
        self.assertIn(b'Username or email already exists.', duplicate.data)


if __name__ == '__main__':
    unittest.main()
