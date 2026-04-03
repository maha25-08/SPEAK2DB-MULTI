"""Tests for utils/sql_safety.py (validate_sql_query, is_safe_sql, ensure_limit, apply_student_filters)."""
import unittest

from utils.sql_safety import (
    validate_sql_query,
    is_safe_sql,
    ensure_limit,
    apply_student_filters,
)


class TestValidateSqlQueryStudent(unittest.TestCase):
    def test_student_select_is_allowed(self):
        self.assertTrue(validate_sql_query("SELECT * FROM Books", "Student"))

    def test_student_insert_is_blocked(self):
        self.assertFalse(validate_sql_query("INSERT INTO Books VALUES (1, 'X')", "Student"))

    def test_student_update_is_blocked(self):
        self.assertFalse(validate_sql_query("UPDATE Books SET title='X'", "Student"))

    def test_student_delete_is_blocked(self):
        self.assertFalse(validate_sql_query("DELETE FROM Books", "Student"))

    def test_student_drop_is_blocked(self):
        self.assertFalse(validate_sql_query("DROP TABLE Books", "Student"))

    def test_student_cannot_access_users_table(self):
        self.assertFalse(validate_sql_query("SELECT * FROM users", "Student"))

    def test_student_cannot_access_securitylog(self):
        self.assertFalse(validate_sql_query("SELECT * FROM securitylog", "Student"))

    def test_student_cannot_access_activitylogs(self):
        self.assertFalse(validate_sql_query("SELECT * FROM activitylogs", "Student"))

    def test_student_cannot_access_sessionlog(self):
        self.assertFalse(validate_sql_query("SELECT * FROM sessionlog", "Student"))

    def test_student_case_insensitive_table_block(self):
        self.assertFalse(validate_sql_query("SELECT * FROM USERS", "Student"))

    def test_empty_query_is_rejected(self):
        self.assertFalse(validate_sql_query("", "Student"))

    def test_whitespace_only_is_rejected(self):
        self.assertFalse(validate_sql_query("   ", "Student"))


class TestValidateSqlQueryLibrarian(unittest.TestCase):
    def test_librarian_select_is_allowed(self):
        self.assertTrue(validate_sql_query("SELECT * FROM Books", "Librarian"))

    def test_librarian_insert_is_allowed(self):
        self.assertTrue(validate_sql_query("INSERT INTO Books (title) VALUES ('X')", "Librarian"))

    def test_librarian_update_is_allowed(self):
        self.assertTrue(validate_sql_query("UPDATE Books SET title='X'", "Librarian"))

    def test_librarian_delete_is_allowed(self):
        self.assertTrue(validate_sql_query("DELETE FROM Books WHERE id=1", "Librarian"))

    def test_librarian_drop_is_blocked(self):
        self.assertFalse(validate_sql_query("DROP TABLE Books", "Librarian"))

    def test_librarian_create_is_blocked(self):
        self.assertFalse(validate_sql_query("CREATE TABLE X (id INT)", "Librarian"))

    def test_librarian_alter_is_blocked(self):
        self.assertFalse(validate_sql_query("ALTER TABLE Books ADD COLUMN x TEXT", "Librarian"))

    def test_librarian_cannot_access_users_table(self):
        self.assertFalse(validate_sql_query("SELECT * FROM users", "Librarian"))

    def test_librarian_pragma_is_blocked(self):
        self.assertFalse(validate_sql_query("PRAGMA table_info(Books)", "Librarian"))


class TestValidateSqlQueryAdministrator(unittest.TestCase):
    def test_administrator_select_is_allowed(self):
        self.assertTrue(validate_sql_query("SELECT * FROM Books", "Administrator"))

    def test_administrator_drop_is_allowed(self):
        self.assertTrue(validate_sql_query("DROP TABLE Books", "Administrator"))

    def test_administrator_can_access_users(self):
        self.assertTrue(validate_sql_query("SELECT * FROM users", "Administrator"))

    def test_administrator_insert_is_allowed(self):
        self.assertTrue(validate_sql_query("INSERT INTO Books (title) VALUES ('X')", "Administrator"))


class TestIsSafeSql(unittest.TestCase):
    def test_valid_select_is_safe(self):
        safe, reason = is_safe_sql("SELECT * FROM Books")
        self.assertTrue(safe)
        self.assertEqual(reason, "")

    def test_empty_sql_is_treated_as_safe(self):
        safe, reason = is_safe_sql("")
        self.assertTrue(safe)
        self.assertEqual(reason, "")

    def test_none_is_treated_as_safe(self):
        safe, reason = is_safe_sql(None)
        self.assertTrue(safe)
        self.assertEqual(reason, "")

    def test_non_select_is_unsafe(self):
        safe, reason = is_safe_sql("INSERT INTO Books VALUES (1)")
        self.assertFalse(safe)
        self.assertIn("Only SELECT", reason)

    def test_drop_in_select_is_unsafe(self):
        safe, reason = is_safe_sql("SELECT * FROM Books; DROP TABLE Books")
        self.assertFalse(safe)

    def test_multi_statement_is_unsafe(self):
        safe, reason = is_safe_sql("SELECT 1; SELECT 2")
        self.assertFalse(safe)
        self.assertIn("Multi-statement", reason)

    def test_select_with_trailing_semicolon_is_safe(self):
        safe, reason = is_safe_sql("SELECT * FROM Books;")
        self.assertTrue(safe)

    def test_blocked_keyword_in_subquery_is_unsafe(self):
        safe, reason = is_safe_sql("SELECT (DROP TABLE x) FROM Books")
        self.assertFalse(safe)


class TestEnsureLimit(unittest.TestCase):
    def test_adds_limit_when_absent(self):
        result = ensure_limit("SELECT * FROM Books", 50)
        self.assertIn("LIMIT 50", result)

    def test_does_not_add_limit_when_below_cap(self):
        sql = "SELECT * FROM Books LIMIT 10"
        result = ensure_limit(sql, 100)
        self.assertEqual(result, sql)

    def test_caps_limit_when_exceeding_cap(self):
        sql = "SELECT * FROM Books LIMIT 500"
        result = ensure_limit(sql, 100)
        self.assertIn("LIMIT 100", result)
        self.assertNotIn("LIMIT 500", result)

    def test_empty_sql_returned_unchanged(self):
        self.assertEqual(ensure_limit("", 100), "")

    def test_none_sql_returned_unchanged(self):
        self.assertIsNone(ensure_limit(None, 100))

    def test_limit_exactly_at_cap_is_unchanged(self):
        sql = "SELECT * FROM Books LIMIT 100"
        result = ensure_limit(sql, 100)
        self.assertEqual(result, sql)

    def test_limit_with_offset_is_handled(self):
        sql = "SELECT * FROM Books LIMIT 200 OFFSET 10"
        result = ensure_limit(sql, 50)
        self.assertIn("LIMIT 50", result)


class TestApplyStudentFilters(unittest.TestCase):
    SID = 42

    def test_fines_table_gets_student_id_filter(self):
        sql = "SELECT * FROM Fines"
        result = apply_student_filters("my fines", sql, self.SID)
        self.assertIn(f"student_id = {self.SID}", result)

    def test_fines_table_already_filtered_not_duplicated(self):
        sql = f"SELECT * FROM Fines WHERE student_id = {self.SID}"
        result = apply_student_filters("my fines", sql, self.SID)
        self.assertEqual(result.count(f"student_id = {self.SID}"), 1)

    def test_issued_table_gets_student_id_filter(self):
        sql = "SELECT * FROM Issued"
        result = apply_student_filters("my books", sql, self.SID)
        self.assertIn(f"student_id = {self.SID}", result)

    def test_reservations_table_gets_student_id_filter(self):
        sql = "SELECT * FROM Reservations"
        result = apply_student_filters("my reservations", sql, self.SID)
        self.assertIn(f"student_id = {self.SID}", result)

    def test_students_table_gets_id_filter(self):
        sql = "SELECT * FROM Students"
        result = apply_student_filters("my profile", sql, self.SID)
        self.assertIn(f"id = {self.SID}", result)

    def test_books_table_without_my_keyword_unchanged(self):
        sql = "SELECT * FROM Books"
        result = apply_student_filters("show all books", sql, self.SID)
        self.assertEqual(result, sql)

    def test_invalid_student_id_returns_original_sql(self):
        sql = "SELECT * FROM Fines"
        result = apply_student_filters("my fines", sql, "bad_id")
        self.assertEqual(result, sql)

    def test_fines_with_existing_where_injects_and_condition(self):
        sql = "SELECT * FROM Fines WHERE status = 'Unpaid'"
        result = apply_student_filters("my fines", sql, self.SID)
        self.assertIn(f"student_id = {self.SID}", result)
        self.assertIn("Unpaid", result)


if __name__ == "__main__":
    unittest.main()
