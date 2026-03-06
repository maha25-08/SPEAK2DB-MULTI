"""
query_correction.py
~~~~~~~~~~~~~~~~~~~~
Automatic spell-correction for natural-language queries before SQL generation.

Uses Python's built-in ``difflib`` plus the optional ``rapidfuzz`` package to
find the closest domain keyword for each misspelled word.

Pipeline position:
    user query → [query_correction] → domain vocabulary → SQL generation
"""

import re
from difflib import get_close_matches

# ── Optional rapidfuzz for faster / higher-quality fuzzy matching ─────────────
try:
    from rapidfuzz import process as _rf_process, fuzz as _rf_fuzz
    _RAPIDFUZZ_AVAILABLE = True
except ImportError:
    _RAPIDFUZZ_AVAILABLE = False

# ── Domain keyword dictionary ─────────────────────────────────────────────────
DOMAIN_KEYWORDS = [
    # Core entities
    "books", "students", "fines", "issued", "reservations", "faculty",
    "statistics", "library",
    # Common actions used in NL queries
    "show", "list", "display", "find", "get", "fetch", "search",
    # Additional useful words
    "all", "available", "overdue", "top", "count", "total", "by",
    "with", "from", "where", "order", "limit", "name", "date",
    "author", "category", "branch", "year", "email", "status",
    "department", "publisher", "database",
]

# Minimum similarity ratio (0–1) for a word to be corrected.
# Words below this threshold are left unchanged.
_SIMILARITY_THRESHOLD = 0.75
# Words shorter than this are not corrected (too ambiguous).
_MIN_WORD_LENGTH = 3


def _best_match(word: str) -> str | None:
    """Return the best-matching domain keyword for *word*, or None."""
    if _RAPIDFUZZ_AVAILABLE:
        result = _rf_process.extractOne(
            word,
            DOMAIN_KEYWORDS,
            scorer=_rf_fuzz.ratio,
            score_cutoff=_SIMILARITY_THRESHOLD * 100,  # rapidfuzz uses 0-100
        )
        return result[0] if result else None
    else:
        matches = get_close_matches(
            word,
            DOMAIN_KEYWORDS,
            n=1,
            cutoff=_SIMILARITY_THRESHOLD,
        )
        return matches[0] if matches else None


def correct_query(query: str) -> str:
    """
    Return a spell-corrected version of *query*.

    Each token is compared against DOMAIN_KEYWORDS.  When a close enough
    match is found **and** the token is not already a valid keyword, it is
    replaced by the closest keyword.

    The original casing is not preserved – output is lower-case, which is
    fine since all downstream processing is case-insensitive.

    Examples::

        >>> correct_query("sho bokks")
        'show books'
        >>> correct_query("lst studnts")
        'list students'
        >>> correct_query("shw fines")
        'show fines'
    """
    if not query or not query.strip():
        return query

    lowered = query.lower().strip()
    # Tokenise: keep only word characters (strip punctuation)
    tokens = re.findall(r'\b\w+\b', lowered)
    keyword_set = set(DOMAIN_KEYWORDS)

    corrected_tokens = []
    for token in tokens:
        if len(token) < _MIN_WORD_LENGTH or token in keyword_set:
            # Short words or already-valid keywords are kept as-is
            corrected_tokens.append(token)
        else:
            suggestion = _best_match(token)
            if suggestion and suggestion != token:
                corrected_tokens.append(suggestion)
            else:
                corrected_tokens.append(token)

    corrected = " ".join(corrected_tokens)

    if corrected != lowered:
        print(f"[QUERY CORRECTED] '{query}' → '{corrected}'")

    return corrected
