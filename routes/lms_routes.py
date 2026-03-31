"""
Library Management System (LMS) CRUD routes.

Provides three separate librarian dashboards:
  Librarian 1 – Book Manager  (/view_books, /add_book, /update_book/<id>, /delete_book/<id>)
  Librarian 2 – User Manager  (/lms/view_users, /lms/add_user)
  Librarian 3 – Issue Manager (/view_issued_books, /issue_book, /return_book/<id>, /overdue_books)
"""
import logging
from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from db.connection import get_management_db
from utils.rbac import role_required

logger = logging.getLogger(__name__)

lms_bp = Blueprint("lms", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_book(conn, book_id: int):
    return conn.execute("SELECT * FROM lms_books WHERE id = ?", (book_id,)).fetchone()


def _get_user(conn, user_id: int):
    return conn.execute("SELECT * FROM lms_users WHERE id = ?", (user_id,)).fetchone()


# ===========================================================================
# Librarian 1 – Book Manager
# ===========================================================================

@lms_bp.route("/view_books")
@role_required("Librarian", "Administrator")
def view_books():
    conn = get_management_db()
    try:
        books = conn.execute("SELECT * FROM lms_books ORDER BY title").fetchall()
    finally:
        conn.close()
    return render_template("lms_book_manager.html", books=books)


@lms_bp.route("/add_book", methods=["GET", "POST"])
@role_required("Librarian", "Administrator")
def add_book():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        quantity_raw = request.form.get("quantity", "0").strip()

        if not title or not author:
            flash("Title and author are required.", "error")
            return redirect(url_for("lms.add_book"))

        try:
            quantity = int(quantity_raw)
            if quantity < 0:
                raise ValueError
        except ValueError:
            flash("Quantity must be a non-negative integer.", "error")
            return redirect(url_for("lms.add_book"))

        conn = get_management_db()
        try:
            conn.execute(
                "INSERT INTO lms_books (title, author, quantity) VALUES (?, ?, ?)",
                (title, author, quantity),
            )
            conn.commit()
            flash(f"Book '{title}' added successfully.", "success")
        finally:
            conn.close()
        return redirect(url_for("lms.view_books"))

    return render_template("lms_book_manager.html", books=[], show_add_form=True)


@lms_bp.route("/update_book/<int:book_id>", methods=["GET", "POST"])
@role_required("Librarian", "Administrator")
def update_book(book_id: int):
    conn = get_management_db()
    try:
        book = _get_book(conn, book_id)
        if not book:
            flash("Book not found.", "error")
            return redirect(url_for("lms.view_books"))

        if request.method == "POST":
            title = request.form.get("title", "").strip()
            author = request.form.get("author", "").strip()
            quantity_raw = request.form.get("quantity", "0").strip()

            if not title or not author:
                flash("Title and author are required.", "error")
                return redirect(url_for("lms.update_book", book_id=book_id))

            try:
                quantity = int(quantity_raw)
                if quantity < 0:
                    raise ValueError
            except ValueError:
                flash("Quantity must be a non-negative integer.", "error")
                return redirect(url_for("lms.update_book", book_id=book_id))

            conn.execute(
                "UPDATE lms_books SET title = ?, author = ?, quantity = ? WHERE id = ?",
                (title, author, quantity, book_id),
            )
            conn.commit()
            flash(f"Book '{title}' updated successfully.", "success")
            return redirect(url_for("lms.view_books"))

        books = conn.execute("SELECT * FROM lms_books ORDER BY title").fetchall()
    finally:
        conn.close()

    return render_template("lms_book_manager.html", books=books, edit_book=book)


@lms_bp.route("/delete_book/<int:book_id>", methods=["POST"])
@role_required("Librarian", "Administrator")
def delete_book(book_id: int):
    conn = get_management_db()
    try:
        book = _get_book(conn, book_id)
        if not book:
            flash("Book not found.", "error")
            return redirect(url_for("lms.view_books"))

        # Prevent deletion if the book is currently issued
        active = conn.execute(
            "SELECT 1 FROM lms_issued_books WHERE book_id = ? AND status = 'issued'",
            (book_id,),
        ).fetchone()
        if active:
            flash("Cannot delete a book that is currently issued.", "error")
            return redirect(url_for("lms.view_books"))

        conn.execute("DELETE FROM lms_books WHERE id = ?", (book_id,))
        conn.commit()
        flash(f"Book '{book['title']}' deleted.", "success")
    finally:
        conn.close()
    return redirect(url_for("lms.view_books"))


# ===========================================================================
# Librarian 2 – User Manager
# ===========================================================================

@lms_bp.route("/lms/view_users")
@role_required("Librarian", "Administrator")
def view_users():
    conn = get_management_db()
    try:
        users = conn.execute("SELECT * FROM lms_users ORDER BY name").fetchall()
    finally:
        conn.close()
    return render_template("lms_user_manager.html", users=users)


@lms_bp.route("/lms/add_user", methods=["GET", "POST"])
@role_required("Librarian", "Administrator")
def add_user():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        role = request.form.get("role", "").strip()

        if not name or not role:
            flash("Name and role are required.", "error")
            return redirect(url_for("lms.add_user"))

        conn = get_management_db()
        try:
            conn.execute(
                "INSERT INTO lms_users (name, role) VALUES (?, ?)",
                (name, role),
            )
            conn.commit()
            flash(f"User '{name}' added successfully.", "success")
        finally:
            conn.close()
        return redirect(url_for("lms.view_users"))

    conn = get_management_db()
    try:
        users = conn.execute("SELECT * FROM lms_users ORDER BY name").fetchall()
    finally:
        conn.close()
    return render_template("lms_user_manager.html", users=users, show_add_form=True)


# ===========================================================================
# Librarian 3 – Issue Manager
# ===========================================================================

@lms_bp.route("/view_issued_books")
@role_required("Librarian", "Administrator")
def view_issued_books():
    conn = get_management_db()
    try:
        issued = conn.execute(
            """
            SELECT ib.id, b.title, b.author, u.name AS borrower, u.role AS borrower_role,
                   ib.issue_date, ib.return_date, ib.status
            FROM lms_issued_books ib
            JOIN lms_books b ON ib.book_id = b.id
            JOIN lms_users u ON ib.user_id = u.id
            ORDER BY ib.issue_date DESC
            """
        ).fetchall()
        books = conn.execute(
            "SELECT * FROM lms_books WHERE quantity > 0 ORDER BY title"
        ).fetchall()
        users = conn.execute("SELECT * FROM lms_users ORDER BY name").fetchall()
    finally:
        conn.close()
    return render_template(
        "lms_issue_manager.html",
        issued=issued,
        books=books,
        users=users,
        today=date.today().isoformat(),
    )


@lms_bp.route("/issue_book", methods=["POST"])
@role_required("Librarian", "Administrator")
def issue_book():
    book_id_raw = request.form.get("book_id", "").strip()
    user_id_raw = request.form.get("user_id", "").strip()
    issue_date = request.form.get("issue_date", date.today().isoformat()).strip()

    try:
        book_id = int(book_id_raw)
        user_id = int(user_id_raw)
    except ValueError:
        flash("Invalid book or user selection.", "error")
        return redirect(url_for("lms.view_issued_books"))

    conn = get_management_db()
    try:
        book = _get_book(conn, book_id)
        if not book:
            flash("Book not found.", "error")
            return redirect(url_for("lms.view_issued_books"))

        if book["quantity"] <= 0:
            flash("No copies of this book are available.", "error")
            return redirect(url_for("lms.view_issued_books"))

        user = _get_user(conn, user_id)
        if not user:
            flash("User not found.", "error")
            return redirect(url_for("lms.view_issued_books"))

        conn.execute(
            """
            INSERT INTO lms_issued_books (book_id, user_id, issue_date, status)
            VALUES (?, ?, ?, 'issued')
            """,
            (book_id, user_id, issue_date),
        )
        conn.execute(
            "UPDATE lms_books SET quantity = quantity - 1 WHERE id = ?",
            (book_id,),
        )
        conn.commit()
        flash(f"'{book['title']}' issued to {user['name']}.", "success")
    finally:
        conn.close()
    return redirect(url_for("lms.view_issued_books"))


@lms_bp.route("/return_book/<int:issue_id>", methods=["POST"])
@role_required("Librarian", "Administrator")
def return_book(issue_id: int):
    return_date = request.form.get("return_date", date.today().isoformat()).strip()

    conn = get_management_db()
    try:
        record = conn.execute(
            "SELECT * FROM lms_issued_books WHERE id = ?", (issue_id,)
        ).fetchone()
        if not record:
            flash("Issue record not found.", "error")
            return redirect(url_for("lms.view_issued_books"))

        if record["status"] == "returned":
            flash("This book has already been returned.", "warning")
            return redirect(url_for("lms.view_issued_books"))

        conn.execute(
            "UPDATE lms_issued_books SET return_date = ?, status = 'returned' WHERE id = ?",
            (return_date, issue_id),
        )
        conn.execute(
            "UPDATE lms_books SET quantity = quantity + 1 WHERE id = ?",
            (record["book_id"],),
        )
        conn.commit()
        flash("Book returned successfully.", "success")
    finally:
        conn.close()
    return redirect(url_for("lms.view_issued_books"))


@lms_bp.route("/overdue_books")
@role_required("Librarian", "Administrator")
def overdue_books():
    conn = get_management_db()
    try:
        overdue = conn.execute(
            """
            SELECT ib.id, b.title, b.author, u.name AS borrower, u.role AS borrower_role,
                   ib.issue_date,
                   CAST(julianday('now') - julianday(ib.issue_date) AS INTEGER) AS days_overdue
            FROM lms_issued_books ib
            JOIN lms_books b ON ib.book_id = b.id
            JOIN lms_users u ON ib.user_id = u.id
            WHERE ib.status = 'issued'
              AND julianday('now') - julianday(ib.issue_date) > 14
            ORDER BY days_overdue DESC
            """
        ).fetchall()
    finally:
        conn.close()
    return render_template("lms_issue_manager.html", overdue=overdue, show_overdue=True)
