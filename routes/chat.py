"""
Chatbot route for SPEAK2DB.

Handles natural language commands for Books CRUD via POST /chat.
Uses Flask session to track multi-turn clarification conversations.

Supported intents:
  add_book    – requires: title, author; optional: category, copies
  delete_book – requires: title
  update_book – requires: title + at least one update field
  view_books  – no required fields; executes immediately

Session keys used:
  chat_intent : str     – current pending intent
  chat_data   : dict    – data collected so far
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from flask import Blueprint, jsonify, request, session

from db.connection import get_db_connection, MAIN_DB
from utils.decorators import require_roles

logger = logging.getLogger(__name__)

chat_bp = Blueprint("chat", __name__)

# ---------------------------------------------------------------------------
# Required fields per intent
# ---------------------------------------------------------------------------

_REQUIRED: dict[str, list[str]] = {
    "add_book": ["title", "author"],
    "delete_book": ["title"],
    "update_book": ["title"],
    "view_books": [],
}

_CLARIFICATION_QUESTIONS: dict[str, str] = {
    "title": "What is the title of the book?",
    "author": "Who is the author?",
    "category": "What category does the book belong to? (or type 'skip' to leave blank)",
    "copies": "How many copies are there? (or type 'skip' to use 1)",
    "confirm_delete": "Are you sure you want to delete \"{title}\"? (yes/no)",
}

_ADD_OPTIONAL = ["category", "copies"]


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

def _detect_intent(text: str) -> Optional[str]:
    t = text.lower()
    if any(k in t for k in ("add", "insert", "create", "new")):
        return "add_book"
    if any(k in t for k in ("delete", "remove")):
        return "delete_book"
    if any(k in t for k in ("update", "change", "edit", "modify", "set")):
        return "update_book"
    if any(k in t for k in ("show", "list", "display", "view", "get", "fetch", "see", "what")):
        return "view_books"
    return None


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------

def _normalize_spaces(text: str) -> str:
    """Collapse multiple whitespace characters into a single space."""
    return " ".join(text.split())


def _extract_title_author(text: str) -> dict:
    """
    Extract title and author from text.

    Patterns recognised:
      "X by Y"   → title=X, author=Y
      "\"X\" by Y" → title=X, author=Y
    Returns only the keys that were actually found.
    """
    data: dict = {}
    # Normalise whitespace first to prevent ReDoS with many-space inputs
    text = _normalize_spaces(text)
    # Strip leading action words (add, delete, update, view etc.)
    clean = re.sub(
        r"^(add|insert|create|delete|remove|update|change|edit|view|show|list|get|new)"
        r"( a| the| an)? book ?",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    # "TITLE by AUTHOR" – split on literal " by " (single-space-normalised)
    lower = clean.lower()
    by_idx = lower.find(" by ")
    if by_idx != -1:
        data["title"] = clean[:by_idx].strip().strip('"').strip("'")
        data["author"] = clean[by_idx + 4:].strip().strip('"').strip("'")
        return data

    # Just a title without author
    if clean:
        data["title"] = clean.strip('"').strip("'")
    return data


def _extract_copies(text: str) -> Optional[int]:
    """Return an explicit copies count mentioned in the text."""
    # Normalise spaces first
    text = _normalize_spaces(text)
    m = re.search(r'\b(\d+) cop(?:y|ies)\b', text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'\bcopies? ?[=:] ?(\d+)\b', text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # "set copies to N" – use split approach to avoid ReDoS
    lower = text.lower()
    if "set" in lower and "to" in lower:
        idx_to = lower.rfind(" to ")
        if idx_to != -1:
            tail = lower[idx_to + 4:].strip()
            m2 = re.match(r'^(\d+)\b', tail)
            if m2:
                return int(m2.group(1))
    return None


def _extract_entities(text: str, intent: str) -> dict:
    """Extract as many fields as possible from user text."""
    data = _extract_title_author(text)
    copies = _extract_copies(text)
    if copies is not None:
        data["copies"] = copies

    # Category: "category: X" or "category X" (normalise spaces first)
    norm = _normalize_spaces(text)
    m = re.search(r'\bcategory ?[=:] ?([A-Za-z][^\s,]{0,50})\b', norm, re.IGNORECASE)
    if not m:
        m = re.search(r'\bcategory ([A-Za-z][^\s,]{0,50})\b', norm, re.IGNORECASE)
    if m:
        data["category"] = m.group(1).strip()

    return data


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

def _view_books() -> dict:
    try:
        conn = get_db_connection(MAIN_DB)
        rows = conn.execute(
            "SELECT id, title, author, category, total_copies, available_copies "
            "FROM Books ORDER BY title LIMIT 100"
        ).fetchall()
        conn.close()
        books = [dict(r) for r in rows]
        if not books:
            return {"message": "No books found in the library.", "action": "view", "data": []}
        return {
            "message": f"Found {len(books)} book(s).",
            "action": "view",
            "data": books,
        }
    except Exception as exc:
        logger.error("chat view_books error: %s", exc)
        return {"message": "Failed to retrieve books.", "action": "view", "data": []}


def _add_book(data: dict) -> dict:
    title = data.get("title", "").strip()
    author = data.get("author", "").strip()
    category = data.get("category", "").strip()
    try:
        copies = int(data.get("copies", 1))
        if copies < 1:
            copies = 1
    except (TypeError, ValueError):
        copies = 1

    if not title or not author:
        return {"message": "Title and author are required to add a book.", "action": "add", "success": False}

    try:
        conn = get_db_connection(MAIN_DB)
        conn.execute(
            "INSERT INTO Books (title, author, category, total_copies, available_copies) VALUES (?, ?, ?, ?, ?)",
            (title, author, category, copies, copies),
        )
        conn.commit()
        conn.close()
        logger.info("[Chat] Book added: title=%r, author=%r, copies=%d", title, author, copies)
        return {
            "message": f'Book "{title}" by {author} added successfully!',
            "action": "add",
            "success": True,
            "data": {"title": title, "author": author, "category": category, "copies": copies},
        }
    except Exception as exc:
        logger.error("chat add_book error: %s", exc)
        return {"message": "Failed to add book due to a database error.", "action": "add", "success": False}


def _delete_book(data: dict) -> dict:
    title = data.get("title", "").strip()
    if not title:
        return {"message": "Book title is required to delete.", "action": "delete", "success": False}

    try:
        conn = get_db_connection(MAIN_DB)
        existing = conn.execute(
            "SELECT id, title FROM Books WHERE LOWER(title) = LOWER(?)", (title,)
        ).fetchone()
        if not existing:
            conn.close()
            return {"message": f'No book found with title "{title}".', "action": "delete", "success": False}
        conn.execute("DELETE FROM Books WHERE id = ?", (existing["id"],))
        conn.commit()
        conn.close()
        logger.info("[Chat] Book deleted: title=%r", title)
        return {
            "message": f'Book "{existing["title"]}" deleted successfully.',
            "action": "delete",
            "success": True,
            "data": {"title": existing["title"]},
        }
    except Exception as exc:
        logger.error("chat delete_book error: %s", exc)
        return {"message": "Failed to delete book due to a database error.", "action": "delete", "success": False}


def _update_book(data: dict) -> dict:
    title = data.get("title", "").strip()
    if not title:
        return {"message": "Book title is required to update.", "action": "update", "success": False}

    try:
        conn = get_db_connection(MAIN_DB)
        existing = conn.execute(
            "SELECT * FROM Books WHERE LOWER(title) = LOWER(?)", (title,)
        ).fetchone()
        if not existing:
            conn.close()
            return {"message": f'No book found with title "{title}".', "action": "update", "success": False}

        new_author = data.get("author", existing["author"])
        new_category = data.get("category", existing["category"])
        try:
            new_copies = int(data.get("copies", existing["total_copies"]))
        except (TypeError, ValueError):
            new_copies = existing["total_copies"]

        # Ensure at least one field is actually changing
        if (new_author == existing["author"] and
                new_category == existing["category"] and
                new_copies == existing["total_copies"]):
            conn.close()
            return {
                "message": (
                    f'No changes detected for "{existing["title"]}". '
                    "Please specify what you'd like to update (author, category, or copies)."
                ),
                "action": "update",
                "success": False,
            }

        diff = new_copies - existing["total_copies"]
        new_available = max(0, existing["available_copies"] + diff)

        conn.execute(
            "UPDATE Books SET author = ?, category = ?, total_copies = ?, available_copies = ? WHERE id = ?",
            (new_author, new_category, new_copies, new_available, existing["id"]),
        )
        conn.commit()
        conn.close()
        logger.info("[Chat] Book updated: title=%r", title)
        return {
            "message": f'Book "{existing["title"]}" updated successfully.',
            "action": "update",
            "success": True,
            "data": {"title": existing["title"], "author": new_author, "category": new_category, "copies": new_copies},
        }
    except Exception as exc:
        logger.error("chat update_book error: %s", exc)
        return {"message": "Failed to update book due to a database error.", "action": "update", "success": False}


# ---------------------------------------------------------------------------
# Clarification flow helpers
# ---------------------------------------------------------------------------

def _next_missing_field(intent: str, data: dict) -> Optional[str]:
    """Return the first required field that has not yet been collected."""
    for field in _REQUIRED.get(intent, []):
        if not data.get(field):
            return field
    return None


def _format_question(field: str, data: dict) -> str:
    q = _CLARIFICATION_QUESTIONS.get(field, f"Please provide the {field}:")
    return q.format(**data)


def _absorb_answer(answer: str, pending_field: str, data: dict) -> dict:
    """Store the user's plain answer into the correct field in data."""
    answer = answer.strip()
    skip_words = {"skip", "none", "n/a", "-", ""}

    if pending_field == "title":
        # Normalise spaces and strip leading action phrases if user re-stated the full command
        answer = _normalize_spaces(answer)
        clean = re.sub(
            r"^(add|insert|create|delete|remove|update|change|edit|view|show|list|get|new)"
            r"( a| the| an)? book ?",
            "",
            answer,
            flags=re.IGNORECASE,
        ).strip()
        # Also handle "by AUTHOR" if provided together with title in the answer
        lower = clean.lower()
        by_idx = lower.find(" by ")
        if by_idx != -1:
            data["title"] = clean[:by_idx].strip().strip('"').strip("'")
            if not data.get("author"):
                data["author"] = clean[by_idx + 4:].strip().strip('"').strip("'")
        elif clean:
            data["title"] = clean.strip('"').strip("'")
    elif pending_field in ("copies",):
        if answer.lower() in skip_words:
            data["copies"] = 1
        else:
            try:
                data["copies"] = int(re.sub(r"[^\d]", "", answer) or "1")
            except ValueError:
                data["copies"] = 1
    elif pending_field in ("category",):
        data["category"] = "" if answer.lower() in skip_words else answer
    else:
        if answer.lower() not in {"skip", "n/a", "-"}:
            data[pending_field] = answer
    return data


# ---------------------------------------------------------------------------
# Main chat endpoint
# ---------------------------------------------------------------------------

@chat_bp.route("/chat", methods=["POST"])
@require_roles("Librarian", "Administrator")
def chat():
    """
    Process a chat message and return a structured JSON response.

    Request body: { "message": "<user text>" }
    """
    body = request.get_json(silent=True) or {}
    user_text = (body.get("message") or "").strip()[:500]  # truncate to prevent ReDoS

    logger.debug("[Chat] User input: %r", user_text)

    if not user_text:
        return jsonify({"message": "Please type or say something.", "action": None})

    # ── Retrieve ongoing conversation state ──────────────────────────────────
    current_intent: Optional[str] = session.get("chat_intent")
    collected_data: dict = session.get("chat_data") or {}
    pending_field: Optional[str] = session.get("chat_pending_field")

    logger.debug("[Chat] State: intent=%r, pending=%r", current_intent, pending_field)

    # ── Handle confirmation flow for delete ──────────────────────────────────
    if current_intent == "delete_book" and pending_field == "confirm_delete":
        if user_text.lower() in ("yes", "y", "confirm", "ok"):
            result = _delete_book(collected_data)
        else:
            result = {"message": "Delete cancelled.", "action": "delete", "success": False}
        session.pop("chat_intent", None)
        session.pop("chat_data", None)
        session.pop("chat_pending_field", None)
        return jsonify(result)

    # ── If there's a pending clarification field, absorb the answer ──────────
    if current_intent and pending_field:
        collected_data = _absorb_answer(user_text, pending_field, collected_data)
        session["chat_data"] = collected_data
        session["chat_pending_field"] = None
        pending_field = None
        logger.debug("[Chat] After absorbing answer: %r", collected_data)

    # ── If there's no active intent, detect one from the new message ─────────
    if not current_intent:
        current_intent = _detect_intent(user_text)
        logger.debug("[Chat] Detected intent: %r", current_intent)
        if not current_intent:
            return jsonify({
                "message": (
                    "I didn't understand that. Try commands like:\n"
                    "• \"add book [title] by [author]\"\n"
                    "• \"delete book [title]\"\n"
                    "• \"update book [title]\"\n"
                    "• \"show books\""
                ),
                "action": None,
            })
        # Extract whatever entities are already in the first message
        collected_data = _extract_entities(user_text, current_intent)
        logger.debug("[Chat] Extracted data: %r", collected_data)
        session["chat_intent"] = current_intent
        session["chat_data"] = collected_data

    # ── view_books – execute immediately ─────────────────────────────────────
    if current_intent == "view_books":
        session.pop("chat_intent", None)
        session.pop("chat_data", None)
        session.pop("chat_pending_field", None)
        return jsonify(_view_books())

    # ── Check for missing required fields ────────────────────────────────────
    missing = _next_missing_field(current_intent, collected_data)
    if missing:
        session["chat_intent"] = current_intent
        session["chat_data"] = collected_data
        session["chat_pending_field"] = missing
        question = _format_question(missing, collected_data)
        return jsonify({"message": question, "action": "clarify", "field": missing})

    # ── All required fields are present – ask for optional fields if add ─────
    if current_intent == "add_book":
        for opt in _ADD_OPTIONAL:
            if opt not in collected_data:
                session["chat_intent"] = current_intent
                session["chat_data"] = collected_data
                session["chat_pending_field"] = opt
                question = _format_question(opt, collected_data)
                return jsonify({"message": question, "action": "clarify", "field": opt})

    # ── delete requires confirmation ──────────────────────────────────────────
    if current_intent == "delete_book" and not session.get("chat_confirmed"):
        title = collected_data.get("title", "this book")
        session["chat_intent"] = current_intent
        session["chat_data"] = collected_data
        session["chat_pending_field"] = "confirm_delete"
        return jsonify({
            "message": f'Are you sure you want to delete "{title}"? (yes/no)',
            "action": "clarify",
            "field": "confirm_delete",
        })

    # ── Execute the operation ─────────────────────────────────────────────────
    if current_intent == "add_book":
        result = _add_book(collected_data)
    elif current_intent == "delete_book":
        result = _delete_book(collected_data)
    elif current_intent == "update_book":
        result = _update_book(collected_data)
    else:
        result = {"message": "Unknown intent.", "action": None}

    # Clear session state after execution
    session.pop("chat_intent", None)
    session.pop("chat_data", None)
    session.pop("chat_pending_field", None)
    session.pop("chat_confirmed", None)

    return jsonify(result)


@chat_bp.route("/chat/reset", methods=["POST"])
@require_roles("Librarian", "Administrator")
def chat_reset():
    """Clear any pending chatbot conversation state."""
    session.pop("chat_intent", None)
    session.pop("chat_data", None)
    session.pop("chat_pending_field", None)
    session.pop("chat_confirmed", None)
    return jsonify({"message": "Conversation reset.", "action": "reset"})
