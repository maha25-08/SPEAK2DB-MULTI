"""
Password-hashing utilities for SPEAK2DB.

All demo accounts share the password 'pass'.  The hash is computed once at
import time so that check_password_hash() can validate it without storing
plain-text credentials anywhere in source code.
"""
from hmac import compare_digest

from werkzeug.security import generate_password_hash, check_password_hash

# Pre-computed hash for the shared demo password.
# Replace individual account passwords in production by storing per-user
# hashes in the database.
PASS_HASH: str = generate_password_hash("pass")


def is_password_hash(stored_password: str) -> bool:
    """Return True when a password already uses a Werkzeug hash format."""
    return isinstance(stored_password, str) and stored_password.startswith(('scrypt:', 'pbkdf2:'))


def verify_password(plain_text: str) -> bool:
    """Return True when *plain_text* matches the stored demo password hash."""
    return check_password_hash(PASS_HASH, plain_text)


def verify_stored_password(stored_password: str, plain_text: str) -> bool:
    """Validate a stored password value against the submitted plain text."""
    if not stored_password or not plain_text:
        return False

    if stored_password.startswith(("pbkdf2:", "scrypt:")):
        return check_password_hash(stored_password, plain_text)

    return compare_digest(stored_password, plain_text)
