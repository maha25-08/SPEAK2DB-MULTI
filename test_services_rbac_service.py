"""Tests for services/rbac_service.py."""
import unittest

from services.rbac_service import (
    ROLE_CHOICES,
    ROLE_PERMISSION_SCOPE,
    normalize_role,
    role_permission_scope,
    extract_tables_from_sql,
)


class TestNormalizeRole(unittest.TestCase):
    def test_admin_maps_to_administrator(self):
        self.assertEqual(normalize_role('Admin'), 'Administrator')

    def test_administrator_is_unchanged(self):
        self.assertEqual(normalize_role('Administrator'), 'Administrator')

    def test_student_is_unchanged(self):
        self.assertEqual(normalize_role('Student'), 'Student')

    def test_librarian_is_unchanged(self):
        self.assertEqual(normalize_role('Librarian'), 'Librarian')

    def test_faculty_is_unchanged(self):
        self.assertEqual(normalize_role('Faculty'), 'Faculty')

    def test_empty_string_defaults_to_student(self):
        self.assertEqual(normalize_role(''), 'Student')

    def test_none_defaults_to_student(self):
        self.assertEqual(normalize_role(None), 'Student')

    def test_whitespace_only_defaults_to_student(self):
        self.assertEqual(normalize_role('   '), 'Student')

    def test_unknown_role_returned_as_is(self):
        # Unrecognised role is returned unchanged (not mapped)
        result = normalize_role('SuperAdmin')
        self.assertEqual(result, 'SuperAdmin')

    def test_role_choices_contains_all_expected_roles(self):
        self.assertIn('Student', ROLE_CHOICES)
        self.assertIn('Faculty', ROLE_CHOICES)
        self.assertIn('Librarian', ROLE_CHOICES)
        self.assertIn('Administrator', ROLE_CHOICES)


class TestRolePermissionScope(unittest.TestCase):
    def test_student_scope_is_student(self):
        self.assertEqual(role_permission_scope('Student'), 'Student')

    def test_librarian_scope_is_librarian(self):
        self.assertEqual(role_permission_scope('Librarian'), 'Librarian')

    def test_faculty_scope_is_librarian(self):
        self.assertEqual(role_permission_scope('Faculty'), 'Librarian')

    def test_administrator_scope_is_administrator(self):
        self.assertEqual(role_permission_scope('Administrator'), 'Administrator')

    def test_admin_alias_scope(self):
        self.assertEqual(role_permission_scope('Admin'), 'Administrator')

    def test_unknown_role_defaults_to_student_scope(self):
        self.assertEqual(role_permission_scope('Ghost'), 'Student')


class TestExtractTablesFromSql(unittest.TestCase):
    def test_single_from_table(self):
        tables = extract_tables_from_sql("SELECT * FROM Books")
        self.assertIn('Books', tables)

    def test_join_table_is_included(self):
        tables = extract_tables_from_sql("SELECT * FROM Books JOIN Authors ON Books.author_id = Authors.id")
        self.assertIn('Books', tables)
        self.assertIn('Authors', tables)

    def test_multiple_joins(self):
        sql = "SELECT * FROM Students JOIN Issued ON s.id = i.student_id JOIN Books ON b.id = i.book_id"
        tables = extract_tables_from_sql(sql)
        self.assertIn('Students', tables)
        self.assertIn('Issued', tables)
        self.assertIn('Books', tables)

    def test_case_insensitive_from(self):
        tables = extract_tables_from_sql("select * from Students")
        self.assertIn('Students', tables)

    def test_empty_sql_returns_empty_set(self):
        tables = extract_tables_from_sql("")
        self.assertEqual(tables, set())

    def test_none_returns_empty_set(self):
        tables = extract_tables_from_sql(None)
        self.assertEqual(tables, set())

    def test_no_from_returns_empty_set(self):
        tables = extract_tables_from_sql("SELECT 1")
        self.assertEqual(tables, set())

    def test_subquery_tables_are_included(self):
        sql = "SELECT * FROM (SELECT id FROM Departments) d"
        tables = extract_tables_from_sql(sql)
        self.assertIn('Departments', tables)


if __name__ == "__main__":
    unittest.main()
