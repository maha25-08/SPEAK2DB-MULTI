import unittest

import app as app_module
from flask import url_for

ADMIN_USER_ID = 'admin'
ADMIN_ROLE = 'Administrator'


class AdminDashboardEndpointTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def test_navbar_uses_blueprint_endpoint(self):
        with app_module.app.test_request_context():
            dashboard_href = url_for('dashboard.admin_dashboard')

        with self.client.session_transaction() as sess:
            sess['user_id'] = ADMIN_USER_ID
            sess['role'] = ADMIN_ROLE

        response = self.client.get('/admin_dashboard')

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            f'<a class="navbar-brand" href="{dashboard_href}">'.encode(),
            response.data,
        )


if __name__ == '__main__':
    unittest.main()
