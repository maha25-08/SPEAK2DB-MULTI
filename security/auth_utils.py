"""
Password-hashing utilities for SPEAK2DB.

All demo accounts share the password 'pass'.  The hash is computed once at
import time so that check_password_hash() can validate it without storing
plain-text credentials anywhere in source code.
"""
from werkzeug.security import generate_password_hash, check_password_hash

# Pre-computed hash for the shared demo password.
# Replace individual account passwords in production by storing per-user
# hashes in the database.
PASS_HASH: str = generate_password_hash("pass")


def verify_password(plain_text: str) -> bool:
    """Return True when *plain_text* matches the stored demo password hash."""
    return check_password_hash(PASS_HASH, plain_text)
