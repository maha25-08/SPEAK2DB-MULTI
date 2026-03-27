import unittest

import app as speak2db_app
from clarification import (
    DATA_CLARIFICATION_MESSAGE,
    DETAIL_CLARIFICATION_OPTIONS,
    DETAIL_CLARIFICATION_MESSAGE,
    GENERIC_CLARIFICATION_OPTIONS,
    GENERIC_CLARIFICATION_MESSAGE,
    apply_clarification_choice,
    get_clarification,
    is_ambiguous_query,
    normalize_query_for_execution,
)


class ClarificationLogicTests(unittest.TestCase):
    def test_clear_queries_do_not_trigger_clarification(self):
        self.assertFalse(is_ambiguous_query("show books"))
        self.assertFalse(is_ambiguous_query("list students"))
        self.assertFalse(is_ambiguous_query("my fines"))
        self.assertFalse(is_ambiguous_query("issued books"))
        self.assertFalse(is_ambiguous_query("show students and fines"))
        self.assertFalse(is_ambiguous_query("books with reservations"))
        self.assertFalse(is_ambiguous_query("students?"))

    def test_ambiguous_queries_trigger_clarification(self):
        self.assertTrue(is_ambiguous_query("show data"))
        self.assertTrue(is_ambiguous_query("get details"))
        self.assertTrue(is_ambiguous_query("show something"))
        self.assertTrue(is_ambiguous_query("what should I check"))
        self.assertTrue(is_ambiguous_query("data?"))
        self.assertTrue(is_ambiguous_query("show everything"))

    def test_clarification_payload_matches_query_type(self):
        self.assertEqual(
            get_clarification("show data"),
            {
                "message": DATA_CLARIFICATION_MESSAGE,
                "options": GENERIC_CLARIFICATION_OPTIONS,
            },
        )
        self.assertEqual(
            get_clarification("show details"),
            {
                "message": DETAIL_CLARIFICATION_MESSAGE,
                "options": DETAIL_CLARIFICATION_OPTIONS,
            },
        )
        self.assertEqual(
            get_clarification("show everything"),
            {
                "message": GENERIC_CLARIFICATION_MESSAGE,
                "options": GENERIC_CLARIFICATION_OPTIONS,
            },
        )

    def test_clarification_choice_rewrites_original_query(self):
        self.assertEqual(
            apply_clarification_choice("show data", "Books"),
            "show books",
        )
        self.assertEqual(
            apply_clarification_choice("show details", "Student details"),
            "show student details",
        )

    def test_short_entity_queries_are_normalized_for_execution(self):
        self.assertEqual(normalize_query_for_execution("students?"), "show students")
        self.assertEqual(normalize_query_for_execution("fines?"), "show fines")
        self.assertEqual(normalize_query_for_execution("book details"), "show books")


class ClarificationRouteTests(unittest.TestCase):
    def setUp(self):
        speak2db_app.app.config["TESTING"] = True
        self.client = speak2db_app.app.test_client()

    def _login_student(self):
        with self.client.session_transaction() as session:
            session["user_id"] = "MT3001"
            session["role"] = "Student"
            session["student_id"] = 1

    def _login_librarian(self):
        with self.client.session_transaction() as session:
            session["user_id"] = "librarian"
            session["role"] = "Librarian"
            session.pop("student_id", None)

    def test_query_route_returns_clarification_for_ambiguous_query(self):
        self._login_student()
        response = self.client.post("/query", json={"query": "show data"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        # Clarification layer is disabled; query executes directly
        self.assertNotIn("needs_clarification", payload)
        self.assertTrue(payload.get("success"))

    def test_query_route_returns_detail_clarification_for_detail_request(self):
        self._login_student()
        response = self.client.post("/query", json={"query": "show details"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        # Clarification layer is disabled; query executes directly
        self.assertNotIn("needs_clarification", payload)
        self.assertTrue(payload.get("success"))

    def test_query_route_executes_short_entity_query_without_clarification(self):
        self._login_librarian()
        response = self.client.post("/query", json={"query": "students?"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertNotIn("needs_clarification", payload)
        self.assertIn("FROM Students", payload["sql"])

    def test_query_route_uses_followup_context_before_clarification(self):
        self._login_student()
        with self.client.session_transaction() as session:
            session["last_query"] = "show books"
            session["last_sql"] = "SELECT id,title,author FROM Books"

        response = self.client.post("/query", json={"query": "only available"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload.get("success"))
        self.assertNotIn("needs_clarification", payload)


if __name__ == "__main__":
    unittest.main()
