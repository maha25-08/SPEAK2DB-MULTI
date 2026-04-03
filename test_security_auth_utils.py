"""Tests for security/auth_utils.py."""
import unittest

from werkzeug.security import generate_password_hash

from security.auth_utils import (
    PASS_HASH,
    is_password_hash,
    verify_password,
    verify_stored_password,
)


class TestIsPasswordHash(unittest.TestCase):
    def test_pbkdf2_hash_is_recognised(self):
        hashed = generate_password_hash("secret", method="pbkdf2:sha256")
        self.assertTrue(is_password_hash(hashed))

    def test_scrypt_hash_is_recognised(self):
        hashed = generate_password_hash("secret")
        # Werkzeug 2.x defaults to scrypt; tolerate either prefix
        self.assertTrue(is_password_hash(hashed))

    def test_plain_text_is_not_a_hash(self):
        self.assertFalse(is_password_hash("pass"))

    def test_empty_string_is_not_a_hash(self):
        self.assertFalse(is_password_hash(""))

    def test_none_is_not_a_hash(self):
        self.assertFalse(is_password_hash(None))

    def test_arbitrary_prefixed_string_is_not_a_hash(self):
        self.assertFalse(is_password_hash("md5:abc123"))


class TestVerifyPassword(unittest.TestCase):
    def test_correct_demo_password_returns_true(self):
        self.assertTrue(verify_password("pass"))

    def test_wrong_password_returns_false(self):
        self.assertFalse(verify_password("wrong"))

    def test_empty_password_returns_false(self):
        self.assertFalse(verify_password(""))


class TestVerifyStoredPassword(unittest.TestCase):
    def test_werkzeug_hash_valid_password(self):
        hashed = generate_password_hash("mypassword")
        self.assertTrue(verify_stored_password(hashed, "mypassword"))

    def test_werkzeug_hash_wrong_password(self):
        hashed = generate_password_hash("mypassword")
        self.assertFalse(verify_stored_password(hashed, "wrongpassword"))

    def test_plain_text_stored_password_matches(self):
        self.assertTrue(verify_stored_password("pass", "pass"))

    def test_plain_text_stored_password_mismatch(self):
        self.assertFalse(verify_stored_password("pass", "wrong"))

    def test_empty_stored_password_returns_false(self):
        self.assertFalse(verify_stored_password("", "pass"))

    def test_empty_plain_text_returns_false(self):
        self.assertFalse(verify_stored_password("pass", ""))

    def test_both_empty_returns_false(self):
        self.assertFalse(verify_stored_password("", ""))

    def test_none_stored_password_returns_false(self):
        self.assertFalse(verify_stored_password(None, "pass"))

    def test_none_plain_text_returns_false(self):
        self.assertFalse(verify_stored_password("pass", None))


class TestPassHashConstant(unittest.TestCase):
    def test_pass_hash_is_werkzeug_hash(self):
        self.assertTrue(is_password_hash(PASS_HASH))

    def test_pass_hash_validates_demo_password(self):
        from werkzeug.security import check_password_hash
        self.assertTrue(check_password_hash(PASS_HASH, "pass"))


if __name__ == "__main__":
    unittest.main()
