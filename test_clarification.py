import unittest

import app as speak2db_app
from clarification import (
    CLARIFICATION_OPTIONS,
    apply_clarification_choice,
    get_clarification,
    is_ambiguous_query,
)


class ClarificationLogicTests(unittest.TestCase):
    def test_clear_queries_do_not_trigger_clarification(self):
        self.assertFalse(is_ambiguous_query("show books"))
        self.assertFalse(is_ambiguous_query("list students"))
        self.assertFalse(is_ambiguous_query("my fines"))
        self.assertFalse(is_ambiguous_query("issued books"))

    def test_ambiguous_queries_trigger_clarification(self):
        self.assertTrue(is_ambiguous_query("show data"))
        self.assertTrue(is_ambiguous_query("get details"))
        self.assertTrue(is_ambiguous_query("show something"))
        self.assertTrue(is_ambiguous_query("what should I check"))

    def test_clarification_payload_is_generic(self):
        clarification = get_clarification("show data")
        self.assertEqual(clarification["message"], "What would you like to see?")
        self.assertEqual(clarification["options"], CLARIFICATION_OPTIONS)

    def test_clarification_choice_prefixes_original_query(self):
        self.assertEqual(
            apply_clarification_choice("show data", "Books"),
            "books show data",
        )


class ClarificationRouteTests(unittest.TestCase):
    def setUp(self):
        speak2db_app.app.config["TESTING"] = True
        self.client = speak2db_app.app.test_client()
        with self.client.session_transaction() as session:
            session["user_id"] = "MT3001"
            session["role"] = "Student"
            session["student_id"] = 1

    def test_query_route_returns_clarification_for_ambiguous_query(self):
        response = self.client.post("/query", json={"query": "show data"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["needs_clarification"])
        self.assertEqual(
            payload["clarification"],
            {
                "message": "What would you like to see?",
                "options": CLARIFICATION_OPTIONS,
            },
        )


if __name__ == "__main__":
    unittest.main()
