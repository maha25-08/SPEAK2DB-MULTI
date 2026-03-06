"""
Context-memory module for Speak2DB.

Stores the last user query and generated SQL in the Flask session and
provides helpers to detect follow-up queries and rewrite them using the
previous context.
"""

from __future__ import annotations

import re
from typing import Optional

# Flask session is passed in by the caller so this module stays testable
# without a running Flask application.

# ── Follow-up trigger words ───────────────────────────────────────────────────
_FOLLOWUP_WORDS = {
    "only", "those", "them", "available", "overdue",
    "issued", "unpaid", "mine", "filter", "my", "borrowed",
    "just", "but", "with", "without", "that", "also",
}

# Regex: query starts with (or consists mostly of) a follow-up trigger
_FOLLOWUP_RE = re.compile(
    r"^\s*(only|just|but|filter|show\s+(only|just|me\s+))?\s*"
    r"(those|them|my|mine|available|overdue|issued|unpaid|borrowed|with|without)"
    r"\b",
    re.IGNORECASE,
)

# Short queries (≤ 4 words) whose first word is a trigger are follow-ups
_SHORT_FOLLOWUP_RE = re.compile(
    r"^\s*(only|those|them|mine|available|overdue|unpaid|borrowed|issued)\b",
    re.IGNORECASE,
)


# ── Session key constants ─────────────────────────────────────────────────────
SESSION_LAST_QUERY = "last_query"
SESSION_LAST_SQL   = "last_sql"


# ── Public helpers ────────────────────────────────────────────────────────────

def save_context(session: dict, user_query: str, sql: str) -> None:
    """Persist *user_query* and *sql* in the Flask *session*."""
    session[SESSION_LAST_QUERY] = user_query
    session[SESSION_LAST_SQL]   = sql


def get_last_query(session: dict) -> Optional[str]:
    """Return the previous user query from the session, or ``None``."""
    return session.get(SESSION_LAST_QUERY)


def get_last_sql(session: dict) -> Optional[str]:
    """Return the previously generated SQL from the session, or ``None``."""
    return session.get(SESSION_LAST_SQL)


def is_followup(query: str) -> bool:
    """
    Return ``True`` when *query* looks like a follow-up to the previous query.

    A query is considered a follow-up when:
    - It starts with a recognised follow-up trigger word, **or**
    - It is short (≤ 4 words) and its first word is a trigger word.
    """
    q = query.strip()
    if not q:
        return False
    # Explicit pattern match
    if _FOLLOWUP_RE.match(q):
        return True
    words = q.split()
    if len(words) <= 4 and _SHORT_FOLLOWUP_RE.match(q):
        return True
    return False


def rewrite_followup(current_query: str, previous_query: str) -> str:
    """
    Rewrite *current_query* by merging it with *previous_query*.

    Strategy:
    - Strip leading follow-up trigger phrases from *current_query*.
    - Append the remaining modifier words to a reconstructed query that
      incorporates the subject of *previous_query*.

    Examples::

        >>> rewrite_followup("only available ones", "show books")
        'show available books'
        >>> rewrite_followup("only my borrowed ones", "show books")
        'show my borrowed books'
    """
    if not previous_query:
        return current_query

    # 1. Extract the *modifier* part of the current query by removing
    #    leading trigger words like "only", "just", "filter", "show only".
    modifier = re.sub(
        r"^\s*(only|just|filter|show\s+(only|just|me\s+))?\s*"
        r"(those|them|ones?|the)?\s*",
        "",
        current_query,
        flags=re.IGNORECASE,
    ).strip()

    # Remove trailing filler ("ones", "the ones", etc.)
    modifier = re.sub(r"\b(?:ones?)\s*$", "", modifier, flags=re.IGNORECASE).strip()

    # 2. Determine the verb and subject from the previous query.
    #    Strip any previously appended [TABLES:…] or [HINT:…] hints.
    prev_clean = re.sub(r"\s*\[(?:TABLES?|HINT)[^\]]*\]", "", previous_query).strip()

    if modifier:
        # Reconstruct: verb + modifier + subject
        # Try to find an operation verb at the start of prev_clean
        verb_match = re.match(
            r"^(show|list|display|find|get|fetch|retrieve|give\s+me|tell\s+me)\s+",
            prev_clean,
            flags=re.IGNORECASE,
        )
        if verb_match:
            verb = verb_match.group(1)
            subject = prev_clean[verb_match.end():].strip()
            rewritten = f"{verb} {modifier} {subject}"
        else:
            # No leading verb – just prepend "show"
            rewritten = f"show {modifier} {prev_clean}"
    else:
        # Nothing left after stripping triggers – fall back to previous query
        rewritten = prev_clean

    return rewritten
