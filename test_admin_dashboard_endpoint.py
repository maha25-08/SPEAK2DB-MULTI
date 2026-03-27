import unittest
import os
import shutil
import tempfile

import app as app_module
from flask import url_for

ADMIN_USER_ID = 'admin'
ADMIN_ROLE = 'Administrator'


class AdminDashboardEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix='speak2db-admin-endpoint-')
        cls.test_db = os.path.join(cls.temp_dir, 'library_main.db')
        repo_root = os.path.dirname(os.path.abspath(__file__))
        cls.original_main_db = app_module.MAIN_DB
        shutil.copyfile(
            os.path.join(repo_root, 'library_main.db'),
            cls.test_db,
        )
        app_module.MAIN_DB = cls.test_db
        ensure_admin_schema = getattr(
            app_module,
            '_ensure_admin_schema',
            app_module._ensure_admin_support_schema,
        )
        ensure_admin_schema()

    @classmethod
    def tearDownClass(cls):
        app_module.MAIN_DB = cls.original_main_db
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()

    def test_navbar_uses_blueprint_endpoint(self):
        with app_module.app.test_request_context():
            dashboard_href = url_for('admin_dashboard_route')

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
