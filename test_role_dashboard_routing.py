import unittest

import app as app_module


class RoleDashboardRoutingTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def _login_as_role(self, role, user_id="test-user"):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["role"] = role

    def test_dashboard_redirects_administrator_to_admin_dashboard(self):
        self._login_as_role("Administrator", user_id="admin")

        response = self.client.get("/dashboard", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/admin_dashboard"))

    def test_dashboard_redirects_librarian_to_librarian_dashboard(self):
        self._login_as_role("Librarian", user_id="librarian1")

        response = self.client.get("/dashboard", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/librarian_dashboard"))

    def test_librarian_is_still_denied_admin_dashboard(self):
        self._login_as_role("Librarian", user_id="librarian1")

        response = self.client.get("/admin_dashboard")

        self.assertEqual(response.status_code, 403)
        self.assertIn(b"Access Denied", response.data)

    def test_query_console_shows_librarian_dashboard_link_without_admin_link(self):
        self._login_as_role("Librarian", user_id="librarian1")

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'href="/librarian_dashboard"', response.data)
        self.assertNotIn(b'href="/admin_dashboard"', response.data)


if __name__ == "__main__":
    unittest.main()
