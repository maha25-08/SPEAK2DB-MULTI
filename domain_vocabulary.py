"""
Dynamic schema-driven domain vocabulary system for Speak2DB.

Inspects SQLite schema (tables, columns, foreign keys) and generates
a vocabulary dictionary mapping natural language phrases/synonyms to
schema interpretations. Used to preprocess queries before SQL generation.
"""

import sqlite3
import re
from typing import Dict, List, Optional, Tuple

# ── In-process vocabulary cache ─────────────────────────────────────────────
# Maps db_path -> full vocabulary data dict so repeated calls are free.
_vocab_cache: Dict[str, Dict] = {}

# ── Simple English singularization ──────────────────────────────────────────

def _singularize(word: str) -> str:
    """Return a naive singular form for common English plural patterns."""
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith(("ses", "ches", "xes", "shes")) and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 2:
        return word[:-1]
    return word


# ── Curated table synonyms ───────────────────────────────────────────────────
# Maps canonical table name (lowercase) -> list of NL synonyms.
TABLE_SYNONYMS: Dict[str, List[str]] = {
    "books": [
        "book", "title", "titles", "volume", "volumes",
        "library book", "library books", "catalog", "catalogue",
        "publication", "publications", "reading material",
    ],
    "students": [
        "student", "learner", "learners", "member", "members",
        "patron", "patrons", "borrower", "borrowers", "user", "users",
    ],
    "issued": [
        "issued book", "issued books", "borrowed", "borrowed book",
        "borrowed books", "checkout", "loan", "loans",
        "lending", "checked out", "lending record",
    ],
    "fines": [
        "fine", "penalty", "penalties", "overdue fine",
        "overdue fines", "charge", "charges", "fee", "fees",
        "unpaid fine", "outstanding fine",
    ],
    "reservations": [
        "reservation", "request", "requests",
        "hold", "holds", "booking", "bookings",
    ],
    "departments": [
        "department", "dept", "branch", "division", "school",
    ],
    "faculty": [
        "professor", "professors", "teacher", "teachers",
        "lecturer", "lecturers", "staff", "instructor", "instructors",
    ],
    "publishers": [
        "publisher", "publishing house",
    ],
}

# ── Status / computed-concept meanings ──────────────────────────────────────
# These are richer NL concepts that map to SQL WHERE predicates as hints.
STATUS_MEANINGS: Dict[str, str] = {
    "available books":      "Books WHERE available_copies > 0",
    "unavailable books":    "Books WHERE available_copies = 0",
    "currently issued":     "Issued WHERE return_date IS NULL",
    "overdue books":        "Issued WHERE return_date IS NULL AND due_date < date('now')",
    "overdue":              "Issued WHERE return_date IS NULL AND due_date < date('now')",
    "unpaid fines":         "Fines WHERE status = 'Unpaid'",
    "paid fines":           "Fines WHERE status = 'Paid'",
    "pending reservations": "Reservations WHERE status = 'Pending'",
    "active loans":         "Issued WHERE return_date IS NULL",
    "returned books":       "Issued WHERE return_date IS NOT NULL",
    "not returned":         "Issued WHERE return_date IS NULL",
    "books by category":    "Books GROUP BY category",
    "most popular books":   "Books JOIN Issued ORDER BY borrow_count DESC",
}

# ── Common operation verbs ───────────────────────────────────────────────────
OPERATION_VERBS: List[str] = [
    "show", "list", "display", "find", "get", "fetch",
    "what are", "tell me", "give me", "retrieve",
]


# ── Schema introspection ─────────────────────────────────────────────────────

# Characters allowed in SQLite table/column identifiers (alphanumeric + underscore)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_identifier(name: str) -> str:
    """Return a safely double-quoted SQLite identifier, rejecting unsafe names."""
    if not _SAFE_IDENTIFIER.match(name):
        raise ValueError(f"Unsafe identifier: {name!r}")
    return f'"{name}"'


def _get_schema_info(db_path: str) -> Dict:
    """Extract table names, columns, and foreign keys from SQLite schema."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    schema: Dict = {"tables": {}, "foreign_keys": []}

    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    tables = [row[0] for row in cur.fetchall()]

    for table in tables:
        # Validate table name before interpolating into PRAGMA statements
        quoted = _quote_identifier(table)
        cur.execute(f"PRAGMA table_info({quoted})")
        cols = [row[1] for row in cur.fetchall()]
        schema["tables"][table] = cols

        cur.execute(f"PRAGMA foreign_key_list({quoted})")
        for fk in cur.fetchall():
            schema["foreign_keys"].append(
                {
                    "from_table": table,
                    "from_col": fk[3],
                    "to_table": fk[2],
                    "to_col": fk[4],
                }
            )

    conn.close()
    return schema


# ── Vocabulary builder ───────────────────────────────────────────────────────

def build_vocabulary(db_path: str, force_rebuild: bool = False) -> Dict:
    """
    Build (or return cached) vocabulary data for the given DB path.

    The returned dict contains:
      - 'vocabulary'     : {NL phrase -> "table:X" or "column:T.C" or SQL hint}
      - 'schema'         : raw schema info from introspection
      - 'status_meanings': STATUS_MEANINGS dict
      - 'table_synonyms' : TABLE_SYNONYMS dict
    """
    if not force_rebuild and db_path in _vocab_cache:
        return _vocab_cache[db_path]

    schema = _get_schema_info(db_path)
    vocab: Dict[str, str] = {}

    # ── Auto-generate entries from schema ─────────────────────────────────
    for table, cols in schema["tables"].items():
        t_lower = table.lower()

        # Canonical table name and its singular
        vocab[t_lower] = f"table:{table}"
        singular = _singularize(t_lower)
        if singular != t_lower:
            vocab[singular] = f"table:{table}"

        # Curated synonyms from TABLE_SYNONYMS
        for syn in TABLE_SYNONYMS.get(t_lower, []):
            vocab[syn] = f"table:{table}"

        # Column-level entries: "table column" and "column of table"
        for col in cols:
            c_lower = col.lower()
            vocab[f"{t_lower} {c_lower}"] = f"column:{table}.{col}"
            vocab[f"{c_lower} of {t_lower}"] = f"column:{table}.{col}"
            # Singular table form + column
            if singular != t_lower:
                vocab[f"{singular} {c_lower}"] = f"column:{table}.{col}"

    # ── Status / computed concept hints ───────────────────────────────────
    for phrase, sql_hint in STATUS_MEANINGS.items():
        vocab[phrase] = f"hint:{sql_hint}"

    # ── Operation verbs (mapped to SELECT intent) ──────────────────────────
    for verb in OPERATION_VERBS:
        vocab[verb] = "op:SELECT"

    _vocab_cache[db_path] = {
        "vocabulary": vocab,
        "schema": schema,
        "status_meanings": STATUS_MEANINGS,
        "table_synonyms": TABLE_SYNONYMS,
    }
    return _vocab_cache[db_path]


# ── Query preprocessing ──────────────────────────────────────────────────────

def preprocess_query(query: str, db_path: str) -> str:
    """
    Augment a natural-language query with schema-aware hints.

    Hints are appended as bracketed tokens so the SQL generator can use them
    to pick the right tables/conditions without changing the user-visible query.
    Returns the augmented string (or the original if no hints matched).
    """
    vocab_data = build_vocabulary(db_path)
    vocab = vocab_data["vocabulary"]
    q_lower = query.lower()

    hints: List[str] = []
    matched_tables: set = set()

    # ── Match table references ────────────────────────────────────────────
    # Sort by length descending so longer phrases match before shorter subsets
    for phrase in sorted(vocab.keys(), key=len, reverse=True):
        interpretation = vocab[phrase]
        if interpretation.startswith("table:") and phrase in q_lower:
            table_name = interpretation.split(":", 1)[1]
            matched_tables.add(table_name)

    # ── Match status / computed-concept hints ─────────────────────────────
    for phrase, sql_hint in STATUS_MEANINGS.items():
        if phrase in q_lower:
            hints.append(f"[HINT: {sql_hint}]")

    if matched_tables:
        hints.append(f"[TABLES: {', '.join(sorted(matched_tables))}]")

    if hints:
        return query.rstrip() + "  " + " ".join(hints)
    return query


# ── Debug helper ─────────────────────────────────────────────────────────────

def get_vocabulary_sample(db_path: str, max_entries: int = 20) -> Dict:
    """
    Return vocabulary metadata and a sample for the GET /api/vocabulary endpoint.
    """
    vocab_data = build_vocabulary(db_path)
    vocab = vocab_data["vocabulary"]
    schema = vocab_data["schema"]

    # Pick a representative sample (prefer 'table:' entries first)
    table_entries = {k: v for k, v in vocab.items() if v.startswith("table:")}
    hint_entries  = {k: v for k, v in vocab.items() if v.startswith("hint:")}
    other_entries = {k: v for k, v in vocab.items()
                     if not v.startswith("table:") and not v.startswith("hint:")}

    sample: Dict[str, str] = {}
    sample.update(dict(list(table_entries.items())[:max_entries // 3]))
    sample.update(dict(list(hint_entries.items())[: max_entries // 3]))
    sample.update(dict(list(other_entries.items())[: max_entries // 3]))

    return {
        "db_path":        db_path,
        "total_entries":  len(vocab),
        "tables":         list(schema["tables"].keys()),
        "column_counts":  {t: len(c) for t, c in schema["tables"].items()},
        "foreign_keys":   len(schema["foreign_keys"]),
        "sample":         sample,
        "status_meanings": STATUS_MEANINGS,
    }


def invalidate_cache(db_path: Optional[str] = None) -> None:
    """Remove cached vocabulary.  Pass None to clear all entries."""
    if db_path is None:
        _vocab_cache.clear()
    else:
        _vocab_cache.pop(db_path, None)
