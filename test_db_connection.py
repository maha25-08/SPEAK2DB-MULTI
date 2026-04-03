"""Tests for db/connection.py."""
import os
import sqlite3
import tempfile
import unittest

import db.connection as connection_module
from db.connection import (
    get_db_connection,
    get_main_db,
    get_archive_db,
    get_management_db,
    ensure_query_history_schema,
)


class TestGetDbConnection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name

    def tearDown(self):
        os.unlink(self.db_path)

    def test_returns_sqlite_connection(self):
        conn = get_db_connection(self.db_path)
        self.assertIsInstance(conn, sqlite3.Connection)
        conn.close()

    def test_row_factory_is_row(self):
        conn = get_db_connection(self.db_path)
        self.assertIs(conn.row_factory, sqlite3.Row)
        conn.close()

    def test_can_execute_simple_query(self):
        conn = get_db_connection(self.db_path)
        result = conn.execute("SELECT 1 AS val").fetchone()
        self.assertEqual(result["val"], 1)
        conn.close()

    def test_busy_timeout_pragma_is_applied(self):
        conn = get_db_connection(self.db_path)
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        self.assertEqual(timeout, connection_module.SQLITE_BUSY_TIMEOUT_MS)
        conn.close()


class TestHelperConnectors(unittest.TestCase):
    """get_main_db / get_management_db / get_archive_db point at the configured paths."""

    def _redirect_and_test(self, monkeypatched_attr, helper_fn):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        original = getattr(connection_module, monkeypatched_attr)
        try:
            setattr(connection_module, monkeypatched_attr, tmp_path)
            conn = helper_fn()
            self.assertIsInstance(conn, sqlite3.Connection)
            conn.close()
        finally:
            setattr(connection_module, monkeypatched_attr, original)
            os.unlink(tmp_path)

    def test_get_main_db_returns_connection(self):
        self._redirect_and_test("MAIN_DB", get_main_db)

    def test_get_archive_db_returns_connection(self):
        self._redirect_and_test("ARCHIVE_DB", get_archive_db)

    def test_get_management_db_returns_connection(self):
        self._redirect_and_test("MANAGEMENT_DB", get_management_db)


class TestEnsureQueryHistorySchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self.original_main_db = connection_module.MAIN_DB
        connection_module.MAIN_DB = self.db_path

    def tearDown(self):
        connection_module.MAIN_DB = self.original_main_db
        os.unlink(self.db_path)

    def test_adds_role_column_when_missing(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE TABLE QueryHistory (id INTEGER PRIMARY KEY, query TEXT)"
        )
        conn.commit()
        conn.close()

        ensure_query_history_schema()

        conn = sqlite3.connect(self.db_path)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(QueryHistory)").fetchall()}
        conn.close()
        self.assertIn("role", columns)

    def test_is_idempotent_when_role_column_already_exists(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE TABLE QueryHistory (id INTEGER PRIMARY KEY, query TEXT, role TEXT)"
        )
        conn.commit()
        conn.close()

        # Should not raise even though the column already exists.
        ensure_query_history_schema()

        conn = sqlite3.connect(self.db_path)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(QueryHistory)").fetchall()}
        conn.close()
        self.assertIn("role", columns)

    def test_does_not_raise_when_table_is_absent(self):
        # Table does not exist at all – migration should silently skip.
        ensure_query_history_schema()


if __name__ == "__main__":
    unittest.main()
