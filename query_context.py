"""
Context-based follow-up query understanding for Speak2DB.

Detects follow-up queries that reference a previous query and rewrites them
into a self-contained natural-language query before SQL generation.

Example:
    previous_query = "show books"
    followup_query = "only available ones"
    → rewrite_query(...) → "show available books"
"""

import re
from typing import Optional

# ── Keywords that signal a follow-up / refinement query ─────────────────────
# A query is considered a follow-up when it starts with (or contains only)
# one of these trigger words/phrases.
_FOLLOWUP_TRIGGERS = [
    "only",
    "those",
    "them",
    "available",
    "overdue",
    "issued",
    "unpaid",
    "mine",
    "filter",
    "that",
]

# Compiled pattern: query starts with a trigger word (possibly preceded by
# "show", "list", "get", "find", "display" for safety), OR is a very short
# phrase dominated by a trigger word.
_TRIGGER_RE = re.compile(
    r"^(show\s+|list\s+|get\s+|find\s+|display\s+)?("
    + "|".join(re.escape(t) for t in _FOLLOWUP_TRIGGERS)
    + r")\b",
    re.IGNORECASE,
)

# Maximum number of tokens a query may have to still be considered a follow-up.
# Longer queries are assumed to be self-contained even if they contain a
# trigger keyword.
_MAX_FOLLOWUP_TOKENS = 6

# ── Rewrite rules ────────────────────────────────────────────────────────────
# Ordered list of (follow-up pattern, rewrite template) pairs.
# Templates may contain {subject} which will be replaced by the main
# subject extracted from the previous query (e.g. "books", "students").
_REWRITE_RULES = [
    # books → only available ones
    (re.compile(r"\bavailable\b", re.IGNORECASE),
     "show available {subject}"),
    # books/issued → only overdue ones
    (re.compile(r"\boverdue\b", re.IGNORECASE),
     "show overdue {subject}"),
    # books → only issued ones
    (re.compile(r"\bissued\b", re.IGNORECASE),
     "show issued {subject}"),
    # fines → only unpaid ones
    (re.compile(r"\bunpaid\b", re.IGNORECASE),
     "show unpaid {subject}"),
    # books → only my borrowed ones / mine
    (re.compile(r"\b(mine|my)\b", re.IGNORECASE),
     "show my {subject}"),
    # students → only those with fines
    (re.compile(r"\b(fines?|penalties)\b", re.IGNORECASE),
     "show {subject} with fines"),
]

# ── Subject extraction ───────────────────────────────────────────────────────
# Map canonical keywords in a previous query to a short subject label.
_SUBJECT_MAP = [
    (re.compile(r"\bbooks?\b", re.IGNORECASE), "books"),
    (re.compile(r"\bstudents?\b", re.IGNORECASE), "students"),
    (re.compile(r"\bfines?\b", re.IGNORECASE), "fines"),
    (re.compile(r"\bfaculty\b", re.IGNORECASE), "faculty"),
    (re.compile(r"\bissued\b", re.IGNORECASE), "issued books"),
    (re.compile(r"\b(borrows?|borrowed)\b", re.IGNORECASE), "borrowed books"),
]


def _extract_subject(query: str) -> str:
    """Return the primary subject noun from *query* (e.g. 'books', 'students')."""
    for pattern, label in _SUBJECT_MAP:
        if pattern.search(query):
            return label
    # Fallback: use the last significant word in the query
    words = re.findall(r"[a-zA-Z]+", query)
    return words[-1].lower() if words else "records"


# ── Public API ───────────────────────────────────────────────────────────────

def detect_followup(query: str) -> bool:
    """
    Return True if *query* looks like a follow-up / refinement of a previous query.

    Detection logic:
    - Query starts with (or is dominated by) a known trigger keyword.
    - Query is short (≤ 6 tokens) – longer, self-contained queries are not
      treated as follow-ups even if they contain a trigger word.

    Args:
        query: The raw user query string.

    Returns:
        True if the query is a follow-up, False otherwise.
    """
    q = query.strip()
    tokens = re.findall(r"[a-zA-Z]+", q)

    # Short-circuit: empty or very long queries are never follow-ups
    if not tokens or len(tokens) > _MAX_FOLLOWUP_TOKENS:
        return False

    return bool(_TRIGGER_RE.match(q))


def rewrite_query(previous_query: str, followup_query: str) -> str:
    """
    Combine *previous_query* with *followup_query* to produce a self-contained
    natural-language query.

    Strategy:
    1. Extract the main subject from the previous query (e.g. "books").
    2. Apply the first matching rewrite rule against the follow-up query.
    3. Fall back to a simple concatenation if no rule matches.

    Args:
        previous_query: The last successfully processed NL query.
        followup_query: The new, context-dependent query fragment.

    Returns:
        A self-contained NL query string.
    """
    subject = _extract_subject(previous_query)
    followup_lower = followup_query.strip().lower()

    for pattern, template in _REWRITE_RULES:
        if pattern.search(followup_lower):
            rewritten = template.format(subject=subject)
            return rewritten

    # Generic fallback: prepend "show <subject>" and append the follow-up words
    # (strip leading trigger word to avoid redundancy).
    cleaned = re.sub(_TRIGGER_RE, "", followup_query).strip()
    if cleaned:
        return f"show {subject} {cleaned}".strip()
    return f"show {subject}"
