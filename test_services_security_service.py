"""Tests for services/security_service.py (pure-logic functions that do not require a DB)."""
import os
import sqlite3
import tempfile
import unittest

import db.connection as connection_module
import services.security_service as sec_svc


def _make_tmp_db():
    """Create a temporary SQLite DB with a SecuritySettings table."""
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.execute(
        '''
        CREATE TABLE SecuritySettings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_name TEXT UNIQUE,
            setting_value TEXT,
            description TEXT,
            updated_by TEXT,
            updated_date TEXT
        )
        '''
    )
    conn.commit()
    conn.close()
    return tmp.name


class TestApplyResultLimit(unittest.TestCase):
    def test_adds_limit_when_absent(self):
        result = sec_svc.apply_result_limit("SELECT * FROM Books", 50)
        self.assertIn("LIMIT 50", result)

    def test_does_not_modify_when_limit_below_cap(self):
        sql = "SELECT * FROM Books LIMIT 20"
        result = sec_svc.apply_result_limit(sql, 100)
        self.assertEqual(result, sql)

    def test_caps_limit_exceeding_max(self):
        sql = "SELECT * FROM Books LIMIT 500"
        result = sec_svc.apply_result_limit(sql, 100)
        self.assertIn("LIMIT 100", result)
        self.assertNotIn("LIMIT 500", result)

    def test_empty_sql_returned_unchanged(self):
        self.assertEqual(sec_svc.apply_result_limit("", 100), "")

    def test_none_sql_returned_unchanged(self):
        self.assertIsNone(sec_svc.apply_result_limit(None, 100))

    def test_zero_max_rows_returns_sql_unchanged(self):
        sql = "SELECT * FROM Books"
        result = sec_svc.apply_result_limit(sql, 0)
        self.assertEqual(result, sql)

    def test_limit_with_offset_is_handled(self):
        sql = "SELECT * FROM Books LIMIT 200 OFFSET 5"
        result = sec_svc.apply_result_limit(sql, 50)
        self.assertIn("LIMIT 50", result)

    def test_case_insensitive_limit_detection(self):
        sql = "SELECT * FROM Books limit 500"
        result = sec_svc.apply_result_limit(sql, 100)
        self.assertIn("100", result)
        self.assertNotIn("500", result)


class TestGetSetting(unittest.TestCase):
    def setUp(self):
        self.db_path = _make_tmp_db()
        self.original_main_db = connection_module.MAIN_DB
        sec_svc.MAIN_DB = self.db_path
        connection_module.MAIN_DB = self.db_path

    def tearDown(self):
        sec_svc.MAIN_DB = self.original_main_db
        connection_module.MAIN_DB = self.original_main_db
        os.unlink(self.db_path)

    def _insert_setting(self, name, value):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO SecuritySettings (setting_name, setting_value) VALUES (?, ?)",
            (name, value),
        )
        conn.commit()
        conn.close()

    def test_get_existing_setting(self):
        self._insert_setting('max_results', '200')
        self.assertEqual(sec_svc.get_setting('max_results', '100'), '200')

    def test_get_missing_setting_returns_default(self):
        self.assertEqual(sec_svc.get_setting('nonexistent', 'fallback'), 'fallback')

    def test_get_bool_setting_true_values(self):
        for val in ('1', 'true', 'yes', 'on', 'True', 'YES'):
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO SecuritySettings (setting_name, setting_value) VALUES ('flag', ?)",
                (val,),
            )
            conn.commit()
            conn.close()
            self.assertTrue(sec_svc.get_bool_setting('flag'), f"Expected True for value {val!r}")

    def test_get_bool_setting_false_values(self):
        for val in ('0', 'false', 'no', 'off'):
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO SecuritySettings (setting_name, setting_value) VALUES ('flag2', ?)",
                (val,),
            )
            conn.commit()
            conn.close()
            self.assertFalse(sec_svc.get_bool_setting('flag2'), f"Expected False for value {val!r}")

    def test_get_bool_setting_missing_uses_default_true(self):
        self.assertTrue(sec_svc.get_bool_setting('missing_flag', default=True))

    def test_get_bool_setting_missing_uses_default_false(self):
        self.assertFalse(sec_svc.get_bool_setting('missing_flag2', default=False))

    def test_get_int_setting_returns_integer(self):
        self._insert_setting('timeout', '30')
        self.assertEqual(sec_svc.get_int_setting('timeout', 10), 30)

    def test_get_int_setting_invalid_returns_default(self):
        self._insert_setting('bad_int', 'abc')
        self.assertEqual(sec_svc.get_int_setting('bad_int', 99), 99)

    def test_get_int_setting_missing_returns_default(self):
        self.assertEqual(sec_svc.get_int_setting('no_such_key', 42), 42)


if __name__ == "__main__":
    unittest.main()
