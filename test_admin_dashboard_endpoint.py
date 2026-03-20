import unittest

import app as app_module


class AdminDashboardEndpointTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def test_admin_dashboard_template_uses_registered_endpoint(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'admin'
            sess['role'] = 'Administrator'

        response = self.client.get('/admin_dashboard')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'href="/admin_dashboard"', response.data)


if __name__ == '__main__':
    unittest.main()
