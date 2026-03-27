"""
Tests for RBAC protection of librarian and student routes.

Validates that:
- Librarian routes only allow "Librarian" and "Administrator" roles
- Student individual dashboard only allows "Student" role
- Unauthenticated requests are redirected to login
- Unauthorized roles receive a 403 response
"""
import unittest

import app as app_module


class LibrarianDashboardRBACTests(unittest.TestCase):
    """Tests for /librarian_dashboard canonical route."""

    @classmethod
    def setUpClass(cls):
        app_module.app.config['TESTING'] = True

    def setUp(self):
        self.client = app_module.app.test_client()

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.get('/librarian_dashboard', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])

    def test_librarian_role_allowed(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'librarian'
            sess['role'] = 'Librarian'

        response = self.client.get('/librarian_dashboard')
        self.assertEqual(response.status_code, 200)

    def test_administrator_role_allowed(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'admin'
            sess['role'] = 'Administrator'

        response = self.client.get('/librarian_dashboard')
        self.assertEqual(response.status_code, 200)

    def test_student_role_returns_403(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'MT3001'
            sess['role'] = 'Student'
            sess['student_id'] = 1

        response = self.client.get('/librarian_dashboard')
        self.assertEqual(response.status_code, 403)

    def test_faculty_role_returns_403(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'faculty'
            sess['role'] = 'Faculty'

        response = self.client.get('/librarian_dashboard')
        self.assertEqual(response.status_code, 403)


class LibrarianDashboardKebabRBACTests(unittest.TestCase):
    """Tests for /librarian-dashboard (kebab alias) route."""

    @classmethod
    def setUpClass(cls):
        app_module.app.config['TESTING'] = True

    def setUp(self):
        self.client = app_module.app.test_client()

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.get('/librarian-dashboard', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])

    def test_librarian_role_allowed(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'librarian'
            sess['role'] = 'Librarian'

        response = self.client.get('/librarian-dashboard')
        self.assertEqual(response.status_code, 200)

    def test_student_role_returns_403(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'MT3001'
            sess['role'] = 'Student'
            sess['student_id'] = 1

        response = self.client.get('/librarian-dashboard')
        self.assertEqual(response.status_code, 403)

    def test_faculty_role_returns_403(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'faculty'
            sess['role'] = 'Faculty'

        response = self.client.get('/librarian-dashboard')
        self.assertEqual(response.status_code, 403)


class StudentDashboardIndividualRBACTests(unittest.TestCase):
    """Tests for /student-dashboard-individual route."""

    @classmethod
    def setUpClass(cls):
        app_module.app.config['TESTING'] = True

    def setUp(self):
        self.client = app_module.app.test_client()

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.get('/student-dashboard-individual', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])

    def test_student_role_allowed(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'MT3001'
            sess['role'] = 'Student'
            sess['student_id'] = 1

        response = self.client.get('/student-dashboard-individual')
        self.assertEqual(response.status_code, 200)

    def test_librarian_role_returns_403(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'librarian'
            sess['role'] = 'Librarian'

        response = self.client.get('/student-dashboard-individual')
        self.assertEqual(response.status_code, 403)

    def test_administrator_role_returns_403(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'admin'
            sess['role'] = 'Administrator'

        response = self.client.get('/student-dashboard-individual')
        self.assertEqual(response.status_code, 403)

    def test_faculty_role_returns_403(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'faculty'
            sess['role'] = 'Faculty'

        response = self.client.get('/student-dashboard-individual')
        self.assertEqual(response.status_code, 403)


if __name__ == '__main__':
    unittest.main()
