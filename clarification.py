"""
Clarification chatbot module for Speak2DB.

Detects vague / ambiguous natural-language queries and returns structured
clarification options.  When the user selects an option the choice is applied
to produce a specific NL query that feeds back into the SQL pipeline.

Supports both exact pattern matching and fuzzy matching so that common
spelling mistakes (e.g. "sho bokks", "show studnts") still trigger
clarification.
"""

import re
from difflib import get_close_matches, SequenceMatcher
from typing import Dict, List, Optional, Tuple

# ── Patterns that mark a query as vague / generic ───────────────────────────
# Each pattern is matched against the *entire* (stripped, lowercased) query.
_VAGUE_PATTERNS: List[re.Pattern] = [
    re.compile(r"^(show|list|display|get|find|fetch|give me|retrieve)\s+(all\s+)?"
               r"(books?|titles?|catalog|catalogue|volumes?|library books?)\s*$", re.IGNORECASE),
    re.compile(r"^(show|list|display|get|find)\s+(all\s+)?"
               r"(students?|learners?|members?|patrons?|borrowers?)\s*$", re.IGNORECASE),
    re.compile(r"^(show|list|display|get)\s+(all\s+)?"
               r"(fines?|penalties|charges?|fees?)\s*$", re.IGNORECASE),
    re.compile(r"^(show|list|display|get)\s+(all\s+)?"
               r"(faculty|professors?|teachers?|lecturers?|staff)\s*$", re.IGNORECASE),
    re.compile(r"^(show|list|display|get)\s+(all\s+)?"
               r"(issued books?|loans?|borrowed books?|lending)\s*$", re.IGNORECASE),
    re.compile(r"^(what are|tell me about|give me)\s+(the\s+)?"
               r"(books?|students?|fines?|faculty)\s*$", re.IGNORECASE),
    re.compile(r"^(books?|students?|fines?|faculty)\s*$", re.IGNORECASE),
]

# ── Entity alias map ─────────────────────────────────────────────────────────
# Maps a canonical entity key -> list of strings that identify it in a query.
_ENTITY_ALIASES: Dict[str, List[str]] = {
    "books":    ["book", "books", "title", "titles", "catalog", "catalogue",
                 "volume", "volumes", "library book", "library books"],
    "students": ["student", "students", "learner", "learners", "member",
                 "members", "patron", "patrons", "borrower", "borrowers"],
    "fines":    ["fine", "fines", "penalty", "penalties", "charge", "charges",
                 "fee", "fees"],
    "faculty":  ["faculty", "professor", "professors", "teacher", "teachers",
                 "lecturer", "lecturers", "staff"],
    "issued":   ["issued", "issued books", "loan", "loans", "borrowed",
                 "borrowed books", "lending"],
}

# ── Vocabulary lists for fuzzy matching ────────────────────────────────────────────
_VAGUE_VERBS: List[str] = [
    "show", "list", "display", "get", "find", "fetch",
    "give", "retrieve", "tell", "what",
]

# All single-word entity tokens (flattened from _ENTITY_ALIASES)
_ENTITY_WORDS: List[str] = sorted(
    {word for aliases in _ENTITY_ALIASES.values() for word in aliases if " " not in word},
    key=len, reverse=True
)


# ── Per-entity clarification options ─────────────────────────────────────────
# Each value must a dict: {"question": str, "options": [{"label": str, "value": str}]}
CLARIFICATION_MENU: Dict[str, Dict] = {
    "books": {
        "question": "What would you like to know about books?",
        "options": [
            {"label": "All Books",
             "value": "show all books with title and author"},
            {"label": "Available Books",
             "value": "show books that are available for borrowing"},
            {"label": "Books by Category",
             "value": "show books grouped by category with counts"},
            {"label": "Most Borrowed Books",
             "value": "show books ordered by number of times they have been issued"},
        ],
    },
    "students": {
        "question": "Which student information would you like to see?",
        "options": [
            {"label": "All Students",
             "value": "show all students with name and roll number"},
            {"label": "Students with Unpaid Fines",
             "value": "show students who have unpaid fines"},
            {"label": "Students by Department",
             "value": "show students grouped by branch or department"},
            {"label": "Students Currently Borrowing",
             "value": "show students who currently have books issued and not returned"},
        ],
    },
    "fines": {
        "question": "Which fine records would you like to view?",
        "options": [
            {"label": "All Fines",
             "value": "show all fines with amount and status"},
            {"label": "Unpaid Fines",
             "value": "show fines where status is Unpaid"},
            {"label": "Fines per Student",
             "value": "show total fine amount per student"},
            {"label": "Recent Fines",
             "value": "show fines ordered by issue date descending"},
        ],
    },
    "faculty": {
        "question": "Which faculty information would you like?",
        "options": [
            {"label": "All Faculty",
             "value": "show all faculty with name and department"},
            {"label": "Faculty by Department",
             "value": "show faculty members grouped by department"},
        ],
    },
    "issued": {
        "question": "Which issued-book records would you like to see?",
        "options": [
            {"label": "Currently Issued (Not Returned)",
             "value": "show books currently issued that have not been returned"},
            {"label": "Overdue Books",
             "value": "show overdue books that are past their due date and not returned"},
            {"label": "Full Lending History",
             "value": "show all book lending history"},
        ],
    },
}


# ── Internal helpers ─────────────────────────────────────────────────────────

def _detect_entity(query_lower: str) -> Optional[str]:
    """Return the canonical entity key that best matches the query text."""
    for entity, aliases in _ENTITY_ALIASES.items():
        for alias in aliases:
            if re.search(r"\b" + re.escape(alias) + r"\b", query_lower):
                return entity
    return None


def _fuzzy_token_matches(word: str, candidates: List[str], cutoff: float = 0.75) -> bool:
    """Return True if *word* is close enough to any entry in *candidates*."""
    return bool(get_close_matches(word.lower(), candidates, n=1, cutoff=cutoff))


def _fuzzy_detect_entity(query_lower: str) -> Optional[str]:
    """
    Fuzzy-match each token in the query against known entity words.

    Returns the first canonical entity key whose aliases contain a word
    similar (≥ 0.75 similarity) to any token in the query, or None.
    """
    tokens = re.findall(r"[a-z]+", query_lower)
    for token in tokens:
        if len(token) < 3:
            continue
        for entity, aliases in _ENTITY_ALIASES.items():
            single_word_aliases = [a for a in aliases if " " not in a]
            if _fuzzy_token_matches(token, single_word_aliases):
                return entity
    return None


def _is_fuzzy_vague(query: str) -> Tuple[bool, Optional[str]]:
    """
    Fuzzy fallback: detect vague queries that contain spelling mistakes.

    Strategy: a query is considered vague when it has 1–3 tokens, at least one
    token fuzzy-matches a known *verb* (show / list / …), and at least one
    other token fuzzy-matches a known *entity* word (book / student / …).
    Short token limit (≤ 3) avoids false positives on specific queries such as
    "find books by Dan Brown" or "show students with GPA above 3.5".
    """
    tokens = re.findall(r"[a-z]+", query.lower())
    # Only consider very short queries; longer ones are likely specific
    if len(tokens) == 0 or len(tokens) > 3:
        return False, None

    has_verb = any(_fuzzy_token_matches(t, _VAGUE_VERBS, cutoff=0.72) for t in tokens)
    if not has_verb:
        # Also accept bare entity-only queries (e.g. "bokks", "studdents")
        entity = _fuzzy_detect_entity(query)
        if entity and len(tokens) <= 2:
            return True, entity
        return False, None

    entity = _fuzzy_detect_entity(query)
    if entity is None:
        return False, None
    return True, entity


# ── Public API ───────────────────────────────────────────────────────────────

def is_vague_query(query: str) -> Tuple[bool, Optional[str]]:
    """
    Determine whether *query* is too vague to execute without clarification.

    Checks exact regex patterns first, then falls back to fuzzy token matching
    so that misspelled queries (e.g. "sho bokks", "show studnts") are also
    caught.

    Returns:
        (True, entity_key)  – vague; entity_key is one of the CLARIFICATION_MENU keys
        (False, None)       – specific enough to proceed
    """
    q = query.strip()

    # ── Exact pattern check ───────────────────────────────────────────────
    for pattern in _VAGUE_PATTERNS:
        if pattern.match(q):
            entity = _detect_entity(q.lower())
            return True, entity

    # ── Fuzzy fallback ────────────────────────────────────────────────────
    fuzzy_vague, entity = _is_fuzzy_vague(q)
    if fuzzy_vague and entity is not None:
        return True, entity

    return False, None


def get_clarification(query: str) -> Optional[Dict]:
    """
    Return a structured clarification payload for a vague query, or None.

    Returned dict format:
        {
          "question":      str,
          "original_query": str,
          "entity":         str,
          "options": [
              {"label": str, "value": str},
              ...
          ]
        }
    """
    vague, entity = is_vague_query(query)
    if not vague or entity is None:
        return None

    menu = CLARIFICATION_MENU.get(entity)
    if menu is None:
        return None

    return {
        "question":       menu["question"],
        "original_query": query,
        "entity":         entity,
        "options":        menu["options"],
    }


def apply_clarification_choice(original_query: str, choice_value: str) -> str:
    """
    Combine the original vague query with the user's chosen clarification.

    The *choice_value* is already a specific NL description (e.g. "show books
    that are available for borrowing").  We return it directly, optionally
    prefixed with context from the original query if it contains extra words.

    Args:
        original_query: the original vague NL query
        choice_value:   the "value" field from the selected option

    Returns:
        Expanded NL query string ready for SQL generation.
    """
    # choice_value is already a full, specific NL query – use it as-is.
    return choice_value.strip()
