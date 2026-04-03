"""Tests for utils/validators.py."""
import unittest

from utils.validators import validate_managed_user_form, validate_query_result_limit


class TestValidateManagedUserForm(unittest.TestCase):
    def _base_data(self, **overrides):
        data = {
            'username': 'USR001',
            'name': 'Test User',
            'email': 'test@example.com',
            'password': 'pass',
            'role': 'Student',
            'branch': 'CSE',
            'year': '2',
            'phone': '9999999999',
        }
        data.update(overrides)
        return data

    def test_valid_student_form_returns_no_error(self):
        normalized, error = validate_managed_user_form(self._base_data())
        self.assertEqual(error, '')

    def test_missing_username_returns_error(self):
        _, error = validate_managed_user_form(self._base_data(username=''))
        self.assertIn('Username', error)

    def test_missing_name_returns_error(self):
        _, error = validate_managed_user_form(self._base_data(name=''))
        self.assertIn('Name', error)

    def test_missing_email_returns_error(self):
        _, error = validate_managed_user_form(self._base_data(email=''))
        self.assertIn('email', error.lower())

    def test_invalid_email_without_at_returns_error(self):
        _, error = validate_managed_user_form(self._base_data(email='notanemail'))
        self.assertIn('email', error.lower())

    def test_invalid_role_returns_error(self):
        _, error = validate_managed_user_form(self._base_data(role='SuperUser'))
        self.assertIn('role', error.lower())

    def test_admin_role_normalized_from_Admin(self):
        data = self._base_data(role='Admin')
        normalized, error = validate_managed_user_form(data)
        self.assertEqual(error, '')
        self.assertEqual(normalized['role'], 'Administrator')

    def test_new_user_without_password_defaults_to_pass(self):
        data = self._base_data(password='')
        normalized, error = validate_managed_user_form(data, existing_user=None)
        self.assertEqual(error, '')
        self.assertEqual(normalized['password'], 'pass')

    def test_existing_user_update_without_password_leaves_blank(self):
        data = self._base_data(password='')
        normalized, error = validate_managed_user_form(data, existing_user={'id': 1})
        self.assertEqual(error, '')
        self.assertEqual(normalized['password'], '')

    def test_student_without_year_defaults_to_1(self):
        data = self._base_data(year='')
        normalized, error = validate_managed_user_form(data)
        self.assertEqual(error, '')
        self.assertEqual(normalized['year'], '1')

    def test_student_without_branch_defaults_to_GEN(self):
        data = self._base_data(branch='')
        normalized, error = validate_managed_user_form(data)
        self.assertEqual(error, '')
        self.assertEqual(normalized['branch'], 'GEN')

    def test_librarian_without_department_defaults(self):
        data = self._base_data(role='Librarian', department='')
        normalized, error = validate_managed_user_form(data)
        self.assertEqual(error, '')
        self.assertEqual(normalized['department'], 'General')

    def test_librarian_without_designation_defaults_to_Librarian(self):
        data = self._base_data(role='Librarian', designation='')
        normalized, error = validate_managed_user_form(data)
        self.assertEqual(error, '')
        self.assertEqual(normalized['designation'], 'Librarian')

    def test_faculty_without_designation_defaults_to_Faculty(self):
        data = self._base_data(role='Faculty', designation='')
        normalized, error = validate_managed_user_form(data)
        self.assertEqual(error, '')
        self.assertEqual(normalized['designation'], 'Faculty')

    def test_email_is_lowercased(self):
        data = self._base_data(email='TEST@EXAMPLE.COM')
        normalized, _ = validate_managed_user_form(data)
        self.assertEqual(normalized['email'], 'test@example.com')

    def test_valid_faculty_form_returns_no_error(self):
        data = self._base_data(role='Faculty', department='Computer Science', designation='Lecturer')
        _, error = validate_managed_user_form(data)
        self.assertEqual(error, '')

    def test_valid_administrator_form_returns_no_error(self):
        data = self._base_data(role='Administrator')
        _, error = validate_managed_user_form(data)
        self.assertEqual(error, '')


class TestValidateQueryResultLimit(unittest.TestCase):
    def test_valid_positive_integer_returns_no_error(self):
        value, error = validate_query_result_limit('100', 50)
        self.assertEqual(value, '100')
        self.assertEqual(error, '')

    def test_zero_returns_error(self):
        _, error = validate_query_result_limit('0', 50)
        self.assertIn('positive', error.lower())

    def test_negative_returns_error(self):
        _, error = validate_query_result_limit('-10', 50)
        self.assertIn('positive', error.lower())

    def test_non_digit_returns_error(self):
        _, error = validate_query_result_limit('abc', 50)
        self.assertIn('positive', error.lower())

    def test_empty_string_uses_default(self):
        value, error = validate_query_result_limit('', 50)
        self.assertEqual(error, '')
        self.assertEqual(value, '50')

    def test_none_uses_default(self):
        value, error = validate_query_result_limit(None, 75)
        self.assertEqual(error, '')
        self.assertEqual(value, '75')

    def test_whitespace_only_uses_default(self):
        value, error = validate_query_result_limit('   ', 100)
        self.assertEqual(error, '')
        self.assertEqual(value, '100')

    def test_value_one_is_valid(self):
        value, error = validate_query_result_limit('1', 50)
        self.assertEqual(error, '')
        self.assertEqual(value, '1')


if __name__ == "__main__":
    unittest.main()
