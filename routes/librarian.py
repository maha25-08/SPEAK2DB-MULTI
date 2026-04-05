"""
Librarian multi-page routes for SPEAK2DB.

URL scheme (all require Librarian or Administrator role):
  /librarian/dashboard      – overview with stats and recent issues
  /librarian/books          – books catalogue with AJAX CRUD
  /librarian/add_book       – standalone add-book form (GET + POST)
  /librarian/edit_book/<id> – edit-book form (GET + POST)
  /librarian/issued         – issued books management
  /librarian/fines          – fines management
"""
import logging

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from db.connection import MAIN_DB, get_db_connection
from utils.decorators import require_roles
from utils.helpers import get_library_stats

logger = logging.getLogger(__name__)

librarian_bp = Blueprint("librarian", __name__, url_prefix="/librarian")

_ROLES = ("Librarian", "Administrator")


# ---------------------------------------------------------------------------
# Dashboard (overview)
# ---------------------------------------------------------------------------

@librarian_bp.route("/dashboard")
@require_roles(*_ROLES)
def dashboard():
    """Librarian overview dashboard."""
    role = session.get("role")
    user_id = session["user_id"]
    recent_issues = []

    try:
        conn = get_db_connection(MAIN_DB)
        recent_issues = conn.execute(
            """SELECT i.*, b.title, b.author, s.name AS student_name
               FROM Issued i
               JOIN Books b ON i.book_id = b.id
               JOIN Students s ON i.student_id = s.id
               ORDER BY i.issue_date DESC LIMIT 10"""
        ).fetchall()
        conn.close()
    except Exception as exc:
        logger.error("librarian.dashboard DB error: %s", exc)

    stats = get_library_stats()
    return render_template(
        "librarian/dashboard.html",
        role=role,
        user=user_id,
        stats=stats,
        recent_issues=recent_issues,
        active_page="dashboard",
    )


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------

@librarian_bp.route("/books")
@require_roles(*_ROLES)
def books():
    """Books catalogue page (table populated via AJAX /api/books)."""
    role = session.get("role")
    user_id = session["user_id"]
    return render_template(
        "librarian/books.html",
        role=role,
        user=user_id,
        active_page="books",
    )


@librarian_bp.route("/add_book", methods=["GET", "POST"])
@require_roles(*_ROLES)
def add_book():
    """Add a new book (traditional form POST)."""
    role = session.get("role")
    user_id = session["user_id"]

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        author = (request.form.get("author") or "").strip()
        category = (request.form.get("category") or "").strip()
        try:
            total_copies = max(1, int(request.form.get("total_copies", 1)))
        except (TypeError, ValueError):
            total_copies = 1

        if not title or not author:
            flash("Title and author are required.", "danger")
        else:
            try:
                conn = get_db_connection(MAIN_DB)
                conn.execute(
                    "INSERT INTO Books (title, author, category, total_copies, available_copies) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (title, author, category, total_copies, total_copies),
                )
                conn.commit()
                conn.close()
                flash(f'Book "{title}" added successfully.', "success")
                return redirect(url_for("librarian.books"))
            except Exception as exc:
                logger.error("librarian.add_book error: %s", exc)
                flash("Failed to add book. Please try again.", "danger")

    return render_template(
        "librarian/add_book.html",
        role=role,
        user=user_id,
        active_page="books",
    )


@librarian_bp.route("/edit_book/<int:book_id>", methods=["GET", "POST"])
@require_roles(*_ROLES)
def edit_book(book_id: int):
    """Edit an existing book (traditional form POST)."""
    role = session.get("role")
    user_id = session["user_id"]

    try:
        conn = get_db_connection(MAIN_DB)
        book = conn.execute(
            "SELECT id, title, author, category, total_copies, available_copies FROM Books WHERE id = ?",
            (book_id,),
        ).fetchone()
        conn.close()
    except Exception as exc:
        logger.error("librarian.edit_book GET error: %s", exc)
        flash("Could not load book details.", "danger")
        return redirect(url_for("librarian.books"))

    if book is None:
        flash("Book not found.", "danger")
        return redirect(url_for("librarian.books"))

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        author = (request.form.get("author") or "").strip()
        category = (request.form.get("category") or "").strip()
        try:
            total_copies = max(1, int(request.form.get("total_copies", 1)))
        except (TypeError, ValueError):
            total_copies = 1

        if not title or not author:
            flash("Title and author are required.", "danger")
        else:
            try:
                conn = get_db_connection(MAIN_DB)
                issued_count = book["total_copies"] - book["available_copies"]
                new_available = max(0, total_copies - issued_count)
                conn.execute(
                    "UPDATE Books SET title=?, author=?, category=?, total_copies=?, available_copies=? WHERE id=?",
                    (title, author, category, total_copies, new_available, book_id),
                )
                conn.commit()
                conn.close()
                flash(f'Book "{title}" updated successfully.', "success")
                return redirect(url_for("librarian.books"))
            except Exception as exc:
                logger.error("librarian.edit_book POST error: %s", exc)
                flash("Failed to update book. Please try again.", "danger")

    return render_template(
        "librarian/edit_book.html",
        role=role,
        user=user_id,
        book=dict(book),
        active_page="books",
    )


# ---------------------------------------------------------------------------
# Issued books
# ---------------------------------------------------------------------------

@librarian_bp.route("/issued")
@require_roles(*_ROLES)
def issued():
    """Issued books management page (table populated via AJAX /api/issued)."""
    role = session.get("role")
    user_id = session["user_id"]
    return render_template(
        "librarian/issued.html",
        role=role,
        user=user_id,
        active_page="issued",
    )


# ---------------------------------------------------------------------------
# Fines
# ---------------------------------------------------------------------------

@librarian_bp.route("/fines")
@require_roles(*_ROLES)
def fines():
    """Fines management page (table populated via AJAX /api/fines)."""
    role = session.get("role")
    user_id = session["user_id"]
    return render_template(
        "librarian/fines.html",
        role=role,
        user=user_id,
        active_page="fines",
    )
