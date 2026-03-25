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

DETAIL_CLARIFICATION_OPTIONS: List[str] = [
    "Student details",
    "Book details",
    "Fine records",
]

GENERIC_CLARIFICATION_OPTIONS: List[str] = [
    "Students",
    "Books",
    "Fines",
]

DATA_CLARIFICATION_MESSAGE = "What data do you want to see?"
DETAIL_CLARIFICATION_MESSAGE = "Can you clarify what details you need?"
GENERIC_CLARIFICATION_MESSAGE = "I didn't fully understand. What would you like to see?"

ENTITY_CANONICAL_MAP = {
    "book": "books",
    "books": "books",
    "student": "students",
    "students": "students",
    "fine": "fines",
    "fines": "fines",
    "issue": "issued books",
    "issued": "issued books",
    "borrowed": "issued books",
    "reservation": "reservations",
    "reservations": "reservations",
    "faculty": "faculty",
}

_QUERY_VERBS = {
    "show",
    "list",
    "display",
    "get",
    "fetch",
    "retrieve",
    "give",
    "tell",
}

_GENERIC_ONLY_WORDS = _QUERY_VERBS | {
    "all",
    "me",
    "what",
    "which",
    "should",
    "can",
    "could",
    "do",
    "i",
    "see",
    "check",
    "want",
    "need",
    "to",
    "everything",
    "anything",
    "something",
    "data",
    "detail",
    "details",
    "info",
    "information",
    "record",
    "records",
}

_SHORTHAND_FILLER_WORDS = _QUERY_VERBS | {
    "all",
    "data",
    "detail",
    "details",
    "info",
    "information",
    "record",
    "records",
}

_DETAIL_REQUEST_RE = re.compile(
    r"\b(detail|details|info|information|record|records)\b",
    re.IGNORECASE,
)


def _normalize_query(query: str) -> str:
    """Return a trimmed lowercase query with collapsed whitespace."""
    return re.sub(r"\s+", " ", query.strip().lower())


def _strip_terminal_punctuation(query: str) -> str:
    """Strip sentence-ending punctuation without altering words."""
    return re.sub(r"[?!.,;:]+$", "", query).strip()


def _extract_entities(query_lower: str) -> List[str]:
    """Return canonical entity names referenced in *query_lower*."""
    entities: List[str] = []
    for alias, canonical in ENTITY_CANONICAL_MAP.items():
        if re.search(r"\b" + re.escape(alias) + r"\b", query_lower):
            entities.append(canonical)
    # Preserve order while de-duplicating.
    return list(dict.fromkeys(entities))


def _contains_known_entity(query_lower: str) -> bool:
    """Return True when the query references a known library entity."""
    return bool(_extract_entities(query_lower))


def normalize_query_for_execution(query: str) -> str:
    """
    Rewrite shorthand entity requests into executable queries.

    Examples:
        "students?" -> "show students"
        "book details" -> "show books"
        "fines" -> "show fines"
    """
    query_lower = _normalize_query(_strip_terminal_punctuation(query))
    if not query_lower:
        return query.strip()

    tokens = re.findall(r"[a-z]+", query_lower)
    if not tokens:
        return query_lower

    entities = _extract_entities(query_lower)
    if len(entities) != 1:
        return query_lower

    if all(token in _SHORTHAND_FILLER_WORDS or token in ENTITY_CANONICAL_MAP for token in tokens):
        return f"show {entities[0]}".strip()

    return query_lower


def is_ambiguous_query(query: str) -> bool:
    """
    Determine whether a query needs clarification before SQL generation.

    A query is ambiguous when it is generic enough that the system cannot infer
    what the user wants to see. Clear entity requests should execute directly,
    while vague "data/details/everything" requests should trigger clarification.
    """
    query_lower = _normalize_query(_strip_terminal_punctuation(query))
    if not query_lower:
        return True

    if _contains_known_entity(query_lower):
        return False

    if any(re.search(r"\b" + re.escape(word) + r"\b", query_lower) for word in VAGUE_WORDS | {"everything"}):
        return True

    tokens = re.findall(r"[a-z]+", query_lower)
    if not tokens:
        return True

    return all(token in _GENERIC_ONLY_WORDS for token in tokens)


def is_vague_query(query: str) -> Tuple[bool, Optional[str]]:
    """
    Backward-compatible wrapper for older callers.

    Returns the legacy tuple shape expected by earlier integrations.
    """
    return is_ambiguous_query(query), None


def get_clarification(query: str) -> Optional[Dict[str, List[str]]]:
    """Return a natural clarification prompt when the query is ambiguous."""
    query_lower = _normalize_query(_strip_terminal_punctuation(query))
    if not is_ambiguous_query(query_lower):
        return None

    if _DETAIL_REQUEST_RE.search(query_lower):
        return {
            "message": DETAIL_CLARIFICATION_MESSAGE,
            "options": DETAIL_CLARIFICATION_OPTIONS,
        }

    if re.search(r"\bdata\b", query_lower):
        return {
            "message": DATA_CLARIFICATION_MESSAGE,
            "options": GENERIC_CLARIFICATION_OPTIONS,
        }

    return {
        "message": GENERIC_CLARIFICATION_MESSAGE,
        "options": GENERIC_CLARIFICATION_OPTIONS,
    }


def apply_clarification_choice(query: str, choice: str) -> str:
    """Merge the selected clarification choice into the original query."""
    choice_clean = _normalize_query(_strip_terminal_punctuation(choice))
    query_clean = _normalize_query(_strip_terminal_punctuation(query))
    if not choice_clean:
        return query_clean

    verb_match = re.match(
        r"^(show|list|display|get|fetch|retrieve)(?:\s+me)?\b",
        query_clean,
        flags=re.IGNORECASE,
    )
    if verb_match and is_ambiguous_query(query_clean):
        return f"{verb_match.group(1).lower()} {choice_clean}".strip()

    if is_ambiguous_query(query_clean):
        return f"show {choice_clean}".strip()

    return f"{choice_clean} {query_clean}".strip()
