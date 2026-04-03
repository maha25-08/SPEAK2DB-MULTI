"""Tests for utils/helpers.py (is_staff, record_query_event)."""
import unittest
from unittest.mock import MagicMock, patch

from utils.helpers import is_staff, record_query_event


class TestIsStaff(unittest.TestCase):
    def test_librarian_is_staff(self):
        self.assertTrue(is_staff('Librarian'))

    def test_faculty_is_staff(self):
        self.assertTrue(is_staff('Faculty'))

    def test_administrator_is_staff(self):
        self.assertTrue(is_staff('Administrator'))

    def test_student_is_not_staff(self):
        self.assertFalse(is_staff('Student'))

    def test_empty_string_is_not_staff(self):
        self.assertFalse(is_staff(''))

    def test_unknown_role_is_not_staff(self):
        self.assertFalse(is_staff('Guest'))

    def test_case_sensitive_student(self):
        self.assertFalse(is_staff('student'))

    def test_case_sensitive_admin(self):
        self.assertFalse(is_staff('administrator'))


class TestRecordQueryEvent(unittest.TestCase):
    def test_history_logger_is_called_with_correct_args(self):
        history_logger = MagicMock()
        record_query_event(
            user_id='u1',
            role='Student',
            user_query='show books',
            sql_query='SELECT * FROM Books',
            success=True,
            response_time=0.5,
            history_logger=history_logger,
        )
        history_logger.assert_called_once_with('u1', 'Student', 'show books', 'SELECT * FROM Books', True, 0.5)

    def test_activity_logger_called_when_message_provided(self):
        activity_logger = MagicMock()
        record_query_event(
            user_id='u1',
            role='Librarian',
            user_query='show books',
            sql_query='SELECT * FROM Books',
            success=True,
            response_time=1.0,
            activity_message='Ran query',
            activity_logger=activity_logger,
        )
        activity_logger.assert_called_once_with('u1', 'Ran query')

    def test_activity_logger_not_called_without_message(self):
        activity_logger = MagicMock()
        record_query_event(
            user_id='u1',
            role='Student',
            user_query='q',
            sql_query='SELECT 1',
            success=True,
            response_time=0.1,
            activity_logger=activity_logger,
        )
        activity_logger.assert_not_called()

    def test_audit_logger_called_when_entry_provided(self):
        audit_logger = MagicMock()
        record_query_event(
            user_id='u1',
            role='Administrator',
            user_query='drop test',
            sql_query='SELECT 1',
            success=False,
            response_time=0.2,
            audit_entry=('query', 'sql', 'details here'),
            audit_logger=audit_logger,
        )
        audit_logger.assert_called_once_with('u1', 'Administrator', 'query', 'sql', 'details here', success=False)

    def test_audit_logger_not_called_without_entry(self):
        audit_logger = MagicMock()
        record_query_event(
            user_id='u1',
            role='Student',
            user_query='q',
            sql_query='SELECT 1',
            success=True,
            response_time=0.1,
            audit_logger=audit_logger,
        )
        audit_logger.assert_not_called()

    def test_no_loggers_does_not_raise(self):
        record_query_event(
            user_id='u1',
            role='Student',
            user_query='q',
            sql_query='SELECT 1',
            success=True,
            response_time=0.0,
        )

    def test_all_loggers_called_together(self):
        history_logger = MagicMock()
        activity_logger = MagicMock()
        audit_logger = MagicMock()
        record_query_event(
            user_id='admin',
            role='Administrator',
            user_query='show all',
            sql_query='SELECT * FROM Books',
            success=True,
            response_time=0.8,
            activity_message='Admin query',
            audit_entry=('read', 'Books', 'all books'),
            history_logger=history_logger,
            activity_logger=activity_logger,
            audit_logger=audit_logger,
        )
        history_logger.assert_called_once()
        activity_logger.assert_called_once()
        audit_logger.assert_called_once()


if __name__ == "__main__":
    unittest.main()
