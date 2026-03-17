"""
Clarification helpers for Speak2DB.

The clarification flow should only interrupt the user when a query is
genuinely ambiguous. Ambiguity is detected using a small set of vague words
plus the presence or absence of known domain entities.
"""

import re
from typing import Dict, List, Optional, Tuple

KNOWN_ENTITIES: List[str] = [
    "book", "books",
    "student", "students",
    "fine", "fines",
    "issued", "issue", "borrowed",
    "reservation", "reservations",
    "faculty",
]

VAGUE_WORDS = {
    "data",
    "detail",
    "details",
    "info",
    "information",
    "record",
    "records",
    "something",
    "anything",
}

CLARIFICATION_OPTIONS: List[str] = [
    "Books",
    "Students",
    "Fines",
    "Issued Books",
    "Reservations",
]


def _normalize_query(query: str) -> str:
    """Return a trimmed lowercase query with collapsed whitespace."""
    return re.sub(r"\s+", " ", query.strip().lower())


def _contains_known_entity(query_lower: str) -> bool:
    """Return True when the query references a known library entity."""
    return any(
        re.search(r"\b" + re.escape(entity) + r"\b", query_lower)
        for entity in KNOWN_ENTITIES
    )


def is_ambiguous_query(query: str) -> bool:
    """
    Determine whether a query needs clarification before SQL generation.

    A query is ambiguous if it contains a vague word or if it does not mention
    any known library entity.
    """
    query_lower = _normalize_query(query)
    if not query_lower:
        return True

    if any(re.search(r"\b" + re.escape(word) + r"\b", query_lower) for word in VAGUE_WORDS):
        return True

    return not _contains_known_entity(query_lower)


def is_vague_query(query: str) -> Tuple[bool, Optional[str]]:
    """
    Backward-compatible wrapper for older callers.

    Returns the legacy tuple shape expected by earlier integrations.
    """
    return is_ambiguous_query(query), None


def get_clarification(query: str) -> Dict[str, List[str]]:
    """Return a generic clarification prompt for ambiguous queries."""
    return {
        "message": "What would you like to see?",
        "options": CLARIFICATION_OPTIONS,
    }


def apply_clarification_choice(query: str, choice: str) -> str:
    """Prefix the original query with the user's clarification choice."""
    return f"{choice.lower()} {query}".strip()
