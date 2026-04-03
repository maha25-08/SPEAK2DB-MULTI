"""Tests for utils/decorators.py (require_roles) and utils/rbac.py (check_role, login_required, role_required)."""
import unittest

import app as app_module
from flask import Flask, session


class TestRequireRolesDecorator(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        app_module.app.config['SECRET_KEY'] = 'test-secret'
        self.client = app_module.app.test_client()

    def _set_session(self, user_id=None, role=None):
        with self.client.session_transaction() as sess:
            if user_id:
                sess['user_id'] = user_id
                sess['role'] = role
            else:
                sess.pop('user_id', None)
                sess.pop('role', None)

    # ── /query requires login ────────────────────────────────────────────────

    def test_unauthenticated_api_request_returns_401(self):
        response = self.client.post('/query', json={'query': 'show books'})
        self.assertEqual(response.status_code, 401)

    def test_authenticated_student_can_post_to_query(self):
        self._set_session('MT3001', 'Student')
        response = self.client.post('/query', json={'query': 'show books'})
        self.assertIn(response.status_code, (200, 302))

    # ── /admin_dashboard requires Administrator ──────────────────────────────

    def test_student_accessing_admin_dashboard_is_denied(self):
        self._set_session('MT3001', 'Student')
        response = self.client.get('/admin_dashboard')
        self.assertIn(response.status_code, (302, 403))

    def test_admin_can_access_admin_dashboard(self):
        self._set_session('admin', 'Administrator')
        response = self.client.get('/admin_dashboard')
        self.assertEqual(response.status_code, 200)

    # ── /librarian_dashboard requires Librarian / Faculty / Administrator ────

    def test_student_cannot_access_librarian_dashboard(self):
        self._set_session('MT3001', 'Student')
        response = self.client.get('/librarian_dashboard')
        self.assertIn(response.status_code, (302, 403))

    def test_librarian_can_access_librarian_dashboard(self):
        self._set_session('librarian', 'Librarian')
        response = self.client.get('/librarian_dashboard')
        self.assertEqual(response.status_code, 200)


class TestRbacUtils(unittest.TestCase):
    """Unit tests for utils/rbac.py helpers operating inside a Flask request context."""

    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'test'

    def test_check_role_returns_true_for_matching_role(self):
        from utils.rbac import check_role
        with self.app.test_request_context('/'):
            with self.app.test_client() as c:
                with c.session_transaction() as sess:
                    sess['role'] = 'Administrator'
                with self.app.test_request_context('/'):
                    session['role'] = 'Administrator'
                    self.assertTrue(check_role(['Administrator']))

    def test_check_role_returns_false_for_wrong_role(self):
        from utils.rbac import check_role
        with self.app.test_request_context('/'):
            session['role'] = 'Student'
            self.assertFalse(check_role(['Administrator']))

    def test_check_role_returns_false_when_no_session(self):
        from utils.rbac import check_role
        with self.app.test_request_context('/'):
            self.assertFalse(check_role(['Administrator']))

    def test_login_required_returns_none_when_authenticated(self):
        from utils.rbac import login_required
        with self.app.test_request_context('/'):
            session['user_id'] = 'admin'
            result = login_required()
            self.assertIsNone(result)

    def test_login_required_returns_redirect_when_no_session(self):
        from utils.rbac import login_required
        from flask import Response

        # Register a /login route so url_for works
        @self.app.route('/login')
        def login():  # pragma: no cover
            return 'login page'

        with self.app.test_request_context('/'):
            result = login_required()
            self.assertIsNotNone(result)
            self.assertEqual(result.status_code, 302)

    def test_role_required_allows_matching_role(self):
        from utils.rbac import role_required

        @self.app.route('/admin-only')
        @role_required('Administrator')
        def admin_only():
            return 'ok', 200

        @self.app.route('/login')
        def login():  # pragma: no cover
            return 'login page'

        with self.app.test_client() as c:
            with c.session_transaction() as sess:
                sess['user_id'] = 'admin'
                sess['role'] = 'Administrator'
            resp = c.get('/admin-only')
            self.assertEqual(resp.status_code, 200)

    def test_role_required_rejects_wrong_role(self):
        from utils.rbac import role_required

        @self.app.route('/admin-only2')
        @role_required('Administrator')
        def admin_only2():  # pragma: no cover
            return 'ok', 200

        @self.app.route('/login2')
        def login2():  # pragma: no cover
            return 'login page'

        # Patch url_for('login') to work
        with self.app.test_client() as c:
            with c.session_transaction() as sess:
                sess['user_id'] = 'student'
                sess['role'] = 'Student'
            resp = c.get('/admin-only2')
            self.assertEqual(resp.status_code, 403)

    def test_role_required_redirects_unauthenticated_user(self):
        from utils.rbac import role_required

        @self.app.route('/login')
        def login():  # pragma: no cover
            return 'login page'

        @self.app.route('/secure')
        @role_required('Administrator')
        def secure():  # pragma: no cover
            return 'ok', 200

        with self.app.test_client() as c:
            resp = c.get('/secure')
            self.assertEqual(resp.status_code, 302)


if __name__ == "__main__":
    unittest.main()
