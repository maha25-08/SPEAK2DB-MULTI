"""
Spell-correction module for Speak2DB.

Corrects misspelled words in natural-language queries against a curated
domain dictionary using difflib.  When the optional ``rapidfuzz`` package
is installed it is used instead for faster, higher-quality matching.
"""

from __future__ import annotations

import re
from difflib import get_close_matches
from typing import List

# ── Domain dictionary ─────────────────────────────────────────────────────────
# All words that the corrector should be able to fix *to*.
DOMAIN_WORDS: List[str] = [
    # entities / tables
    "books", "book", "students", "student", "fines", "fine",
    "issued", "reservations", "reservation", "faculty",
    "statistics", "library", "publishers", "publisher",
    "departments", "department",
    # common status / filter words
    "available", "overdue", "borrowed", "unpaid", "paid",
    "pending", "returned", "active", "inactive",
    # operation verbs
    "show", "list", "display", "find", "get", "fetch",
    "give", "retrieve", "tell", "filter",
    # common query words
    "all", "my", "me", "only", "those", "them", "mine",
    "with", "without", "by", "in", "from", "where",
    "who", "what", "which", "how", "count", "total",
    "top", "most", "popular", "recent", "last", "days",
    "year", "category", "author", "title", "name",
    "data", "detail", "details", "info", "information", "record", "records",
    "everything",
    "due", "date", "amount", "status",
]

# Build a set for O(1) membership checks
_DOMAIN_SET: set = set(DOMAIN_WORDS)

# Try to import rapidfuzz; fall back to difflib silently
try:
    from rapidfuzz import process as _rf_process, fuzz as _rf_fuzz

    def _best_match(word: str, candidates: List[str], cutoff: float = 0.75) -> str | None:
        """Return the best match for *word* among *candidates* using rapidfuzz."""
        result = _rf_process.extractOne(
            word,
            candidates,
            scorer=_rf_fuzz.ratio,
            score_cutoff=cutoff * 100,  # rapidfuzz uses 0-100 scale
        )
        return result[0] if result else None

except ImportError:
    def _best_match(word: str, candidates: List[str], cutoff: float = 0.75) -> str | None:  # type: ignore[misc]
        """Return the best match for *word* among *candidates* using difflib."""
        matches = get_close_matches(word, candidates, n=1, cutoff=cutoff)
        return matches[0] if matches else None


# ── Token-level corrector ─────────────────────────────────────────────────────

def _correct_token(token: str) -> str:
    """
    Return the corrected form of a single *token*.

    If the token already exists in the domain dictionary (case-insensitive)
    it is returned unchanged.  Otherwise the closest match above the
    similarity threshold is returned, or the original token if no good
    match is found.
    """
    lower = token.lower()
    if lower in _DOMAIN_SET:
        return token  # already correct
    match = _best_match(lower, DOMAIN_WORDS, cutoff=0.75)
    return match if match is not None else token


# ── Public API ────────────────────────────────────────────────────────────────

def correct_query(query: str) -> str:
    """
    Return a spell-corrected version of *query*.

    Each whitespace-delimited token is corrected independently against the
    domain dictionary.  Punctuation attached to tokens is preserved.

    Examples::

        >>> correct_query("sho bokks")
        'show books'
        >>> correct_query("lst studnts")
        'list students'
    """
    if not query or not query.strip():
        return query

    tokens = query.split()
    corrected: List[str] = []

    for token in tokens:
        # Strip leading/trailing punctuation before matching, then re-attach
        leading = len(token) - len(token.lstrip(".,!?;:(\"'"))
        trailing_stripped = token.lstrip(".,!?;:(\"'").rstrip(".,!?;:)\"'")
        trailing = len(token.lstrip(".,!?;:(\"'")) - len(trailing_stripped)
        prefix = token[:leading]
        suffix = token[leading + len(trailing_stripped):]
        corrected_word = _correct_token(trailing_stripped)
        corrected.append(prefix + corrected_word + suffix)

    return " ".join(corrected)
