"""
JSON API endpoints for SPEAK2DB.
"""
import logging
import os
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, session

from db.connection import get_db_connection, MAIN_DB, ARCHIVE_DB
from utils.decorators import require_roles
from utils.rbac import role_required

try:
    from rbac_system_fixed import rbac
    _RBAC_AVAILABLE = True
except ImportError:
    _RBAC_AVAILABLE = False

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# User info
# ---------------------------------------------------------------------------

@api_bp.route("/user-info")
def user_info():
    """Return user information from session."""
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Not logged in"}), 401

    user_id_val = session.get("user_id", "")
    user_role_val = session.get("role", "Student")
    permissions = []

    if _RBAC_AVAILABLE:
        try:
            perms = rbac.get_user_permissions(user_id_val)
            permissions = list(perms)[:20]
        except Exception:
            pass

    return jsonify(
        {
            "success": True,
            "username": user_id_val,
            "role": user_role_val,
            "student_id": session.get("student_id"),
            "permissions": permissions,
        }
    )


@api_bp.route("/ui-config")
def ui_config():
    """Return UI configuration based on the logged-in user's role."""
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Not logged in"}), 401

    features = ["text_to_sql", "multi_db"]
    settings = {
        "voice_input_enabled": True,
        "ai_query_enabled": True,
        "ollama_sql_enabled": True,
        "max_query_result_limit": 100,
    }

    try:
        conn = get_db_connection(MAIN_DB)
        setting_rows = conn.execute(
            "SELECT setting_name, setting_value FROM SecuritySettings "
            "WHERE setting_name IN ('voice_input_enabled', 'ai_query_enabled', "
            "'ollama_sql_enabled', 'max_query_result_limit')"
        ).fetchall()
        conn.close()
        for row in setting_rows:
            name, value = row["setting_name"], row["setting_value"]
            if name == "max_query_result_limit":
                try:
                    settings[name] = int(value)
                except (TypeError, ValueError):
                    pass
            else:
                settings[name] = str(value).strip().lower() in {"1", "true", "yes", "on"}
    except Exception:
        pass  # keep defaults when SecuritySettings table is unavailable

    if settings["voice_input_enabled"]:
        features.append("voice_input")
    if settings["ai_query_enabled"]:
        features.append("ai_query")

    return jsonify(
        {
            "success": True,
            "role": session.get("role", "Student"),
            "features": features,
            "settings": settings,
        }
    )


@api_bp.route("/dashboard-data")
def dashboard_data():
    """Return dashboard statistics from the database."""
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Not logged in"}), 401

    try:
        conn = get_db_connection(MAIN_DB)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            database_size = f"{round(os.path.getsize(MAIN_DB) / 1024 / 1024, 2)} MB"
        except OSError:
            database_size = "Unavailable"

        stats = {
            "queries_today": conn.execute(
                "SELECT COUNT(*) AS cnt FROM QueryHistory "
                "WHERE date(timestamp) = ?",
                (today,),
            ).fetchone()["cnt"],
            "active_users": conn.execute(
                "SELECT COUNT(*) AS cnt FROM SessionLog "
                "WHERE status = 'Active' AND logout_time IS NULL"
            ).fetchone()["cnt"],
            "database_size": database_size,
            "last_update": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        }
        recent_queries = [
            row["query"]
            for row in conn.execute(
                "SELECT query FROM QueryHistory "
                "ORDER BY datetime(timestamp) DESC, id DESC LIMIT 5"
            ).fetchall()
        ]
        conn.close()
        return jsonify({"success": True, "stats": stats, "recent_queries": recent_queries})
    except Exception as exc:
        logger.error("dashboard-data error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

@api_bp.route("/vocabulary")
def vocabulary():
    """Debug endpoint – returns vocabulary metadata and a sample."""
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Not logged in"}), 401

    db_key = request.args.get("db", "main")
    db_path = ARCHIVE_DB if db_key == "archive" else MAIN_DB
    force = request.args.get("rebuild", "0") == "1"

    try:
        from domain_vocabulary import get_vocabulary_sample, invalidate_cache

        if force:
            invalidate_cache(db_path)
        sample = get_vocabulary_sample(db_path)
        return jsonify({"success": True, "vocabulary": sample})
    except Exception as exc:
        logger.error("vocabulary API error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Query analytics (Administrator only)
# ---------------------------------------------------------------------------

@api_bp.route("/query_analytics")
@role_required("Administrator")
def query_analytics():
    """Query analytics – Administrator only."""
    try:
        conn = get_db_connection(MAIN_DB)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        queries_today = conn.execute(
            "SELECT COUNT(*) as cnt FROM QueryHistory WHERE date(timestamp) = ?",
            (today,),
        ).fetchone()["cnt"]

        most_common = [
            dict(r)
            for r in conn.execute(
                "SELECT query, COUNT(*) as count FROM QueryHistory "
                "GROUP BY query ORDER BY count DESC LIMIT 10"
            ).fetchall()
        ]

        top_users = [
            dict(r)
            for r in conn.execute(
                "SELECT user_id, COUNT(*) as count FROM QueryHistory "
                "GROUP BY user_id ORDER BY count DESC LIMIT 10"
            ).fetchall()
        ]

        avg_row = conn.execute(
            "SELECT AVG(response_time) as avg_time FROM QueryHistory "
            "WHERE response_time IS NOT NULL"
        ).fetchone()
        avg_execution_time = round(avg_row["avg_time"] or 0, 4)

        queries_per_day = [
            dict(r)
            for r in conn.execute(
                "SELECT substr(timestamp, 1, 10) as date, COUNT(*) as count "
                "FROM QueryHistory GROUP BY date ORDER BY date DESC LIMIT 30"
            ).fetchall()
        ]

        conn.close()
        return jsonify(
            {
                "success": True,
                "queries_today": queries_today,
                "most_common": most_common,
                "top_users": top_users,
                "avg_execution_time": avg_execution_time,
                "queries_per_day": queries_per_day,
            }
        )
    except Exception as exc:
        logger.error("query_analytics error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Data endpoints (Librarian / Administrator only)
# ---------------------------------------------------------------------------

@api_bp.route("/students")
@require_roles("Librarian", "Faculty", "Administrator")
def students():
    """Return all students as JSON – Librarian/Administrator only."""
    logger.info("api/students accessed by role: %s", session.get("role"))
    try:
        conn = get_db_connection(MAIN_DB)
        rows = conn.execute(
            "SELECT id, roll_number, name, branch, year, email, gpa "
            "FROM Students ORDER BY name LIMIT 500"
        ).fetchall()
        conn.close()
        return jsonify({"success": True, "data": [dict(r) for r in rows]})
    except Exception as exc:
        logger.error("api/students error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@api_bp.route("/issued_books")
@require_roles("Librarian", "Faculty", "Administrator")
def issued_books():
    """Return currently issued books as JSON – Librarian/Administrator only."""
    logger.info("api/issued_books accessed by role: %s", session.get("role"))
    try:
        conn = get_db_connection(MAIN_DB)
        rows = conn.execute(
            """SELECT i.id, s.roll_number, s.name as student_name, b.title, b.author,
                      i.issue_date, i.due_date, i.return_date, i.status
               FROM Issued i
               JOIN Books b ON i.book_id = b.id
               JOIN Students s ON i.student_id = s.id
               WHERE i.return_date IS NULL
               ORDER BY i.issue_date DESC LIMIT 500"""
        ).fetchall()
        conn.close()
        return jsonify({"success": True, "data": [dict(r) for r in rows]})
    except Exception as exc:
        logger.error("api/issued_books error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@api_bp.route("/fines")
@require_roles("Librarian", "Faculty", "Administrator")
def fines():
    """Return fines as JSON – Librarian/Administrator only."""
    logger.info("api/fines accessed by role: %s", session.get("role"))
    try:
        conn = get_db_connection(MAIN_DB)
        rows = conn.execute(
            """SELECT f.id, s.roll_number, s.name as student_name,
                      f.fine_amount, f.fine_type, f.status, f.issue_date
               FROM Fines f
               JOIN Students s ON f.student_id = s.id
               ORDER BY f.issue_date DESC LIMIT 500"""
        ).fetchall()
        conn.close()
        return jsonify({"success": True, "data": [dict(r) for r in rows]})
    except Exception as exc:
        logger.error("api/fines error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@api_bp.route("/fines/<int:fine_id>", methods=["PUT"])
@require_roles("Librarian", "Administrator")
def update_fine(fine_id):
    """Update fine status – Librarian/Administrator only."""
    data = request.get_json(silent=True) or {}
    status = data.get("status", "").strip()
    if status not in ("Paid", "Unpaid", "Waived"):
        return jsonify({"success": False, "error": "Invalid status. Use Paid, Unpaid, or Waived"}), 400
    try:
        conn = get_db_connection(MAIN_DB)
        result = conn.execute(
            "UPDATE Fines SET status = ? WHERE id = ?", (status, fine_id)
        )
        conn.commit()
        conn.close()
        if result.rowcount == 0:
            return jsonify({"success": False, "error": "Fine not found"}), 404
        return jsonify({"success": True, "message": f"Fine {fine_id} status updated to {status}"})
    except Exception as exc:
        logger.error("api/fines PUT error: %s", exc)
        return jsonify({"success": False, "error": "Failed to update fine status"}), 500


# ---------------------------------------------------------------------------
# Books CRUD (Librarian / Administrator only)
# ---------------------------------------------------------------------------

@api_bp.route("/books", methods=["GET"])
@require_roles("Librarian", "Faculty", "Administrator")
def books():
    """Return all books as JSON – Librarian/Administrator only."""
    logger.info("api/books accessed by role: %s", session.get("role"))
    try:
        conn = get_db_connection(MAIN_DB)
        rows = conn.execute(
            "SELECT id, title, author, category, total_copies, available_copies "
            "FROM Books ORDER BY title LIMIT 500"
        ).fetchall()
        conn.close()
        return jsonify({"success": True, "data": [dict(r) for r in rows]})
    except Exception as exc:
        logger.error("api/books GET error: %s", exc)
        return jsonify({"success": False, "error": "Failed to retrieve books"}), 500


@api_bp.route("/books", methods=["POST"])
@require_roles("Librarian", "Administrator")
def add_book():
    """Add a new book – Librarian/Administrator only."""
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    author = (data.get("author") or "").strip()
    category = (data.get("category") or "General").strip()
    try:
        total_copies = max(1, int(data.get("total_copies") or 1))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "total_copies must be a positive integer"}), 400
    if not title or not author:
        return jsonify({"success": False, "error": "title and author are required"}), 400
    try:
        conn = get_db_connection(MAIN_DB)
        cursor = conn.execute(
            "INSERT INTO Books (title, author, category, total_copies, available_copies) "
            "VALUES (?, ?, ?, ?, ?)",
            (title, author, category, total_copies, total_copies),
        )
        conn.commit()
        book_id = cursor.lastrowid
        conn.close()
        return jsonify({"success": True, "message": "Book added", "id": book_id}), 201
    except Exception as exc:
        logger.error("api/books POST error: %s", exc)
        return jsonify({"success": False, "error": "Failed to add book"}), 500


@api_bp.route("/books/<int:book_id>", methods=["PUT"])
@require_roles("Librarian", "Administrator")
def update_book(book_id):
    """Update a book – Librarian/Administrator only."""
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    author = (data.get("author") or "").strip()
    category = (data.get("category") or "").strip() or "General"
    total_copies = data.get("total_copies")
    if not title or not author:
        return jsonify({"success": False, "error": "title and author are required"}), 400
    try:
        conn = get_db_connection(MAIN_DB)
        if total_copies is not None:
            try:
                tc = max(1, int(total_copies))
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "total_copies must be a positive integer"}), 400
            result = conn.execute(
                "UPDATE Books SET title = ?, author = ?, category = ?, total_copies = ? WHERE id = ?",
                (title, author, category, tc, book_id),
            )
        else:
            result = conn.execute(
                "UPDATE Books SET title = ?, author = ?, category = ? WHERE id = ?",
                (title, author, category, book_id),
            )
        conn.commit()
        conn.close()
        if result.rowcount == 0:
            return jsonify({"success": False, "error": "Book not found"}), 404
        return jsonify({"success": True, "message": "Book updated"})
    except Exception as exc:
        logger.error("api/books PUT error: %s", exc)
        return jsonify({"success": False, "error": "Failed to update book"}), 500


@api_bp.route("/books/<int:book_id>", methods=["DELETE"])
@require_roles("Librarian", "Administrator")
def delete_book(book_id):
    """Delete a book – Librarian/Administrator only."""
    try:
        conn = get_db_connection(MAIN_DB)
        result = conn.execute("DELETE FROM Books WHERE id = ?", (book_id,))
        conn.commit()
        conn.close()
        if result.rowcount == 0:
            return jsonify({"success": False, "error": "Book not found"}), 404
        return jsonify({"success": True, "message": "Book deleted"})
    except Exception as exc:
        logger.error("api/books DELETE error: %s", exc)
        return jsonify({"success": False, "error": "Failed to delete book"}), 500


# ---------------------------------------------------------------------------
# Issued CRUD (Librarian / Administrator only)
# ---------------------------------------------------------------------------

@api_bp.route("/issued", methods=["GET"])
@require_roles("Librarian", "Faculty", "Administrator")
def issued():
    """Return issued books as JSON – Librarian/Administrator only."""
    logger.info("api/issued accessed by role: %s", session.get("role"))
    try:
        conn = get_db_connection(MAIN_DB)
        rows = conn.execute(
            """SELECT i.id AS issue_id, b.title, b.author,
                      s.name AS student_name, s.roll_number,
                      i.issue_date, i.due_date, i.return_date, i.status
               FROM Issued i
               JOIN Books b ON i.book_id = b.id
               JOIN Students s ON i.student_id = s.id
               ORDER BY i.issue_date DESC LIMIT 500"""
        ).fetchall()
        conn.close()
        return jsonify({"success": True, "data": [dict(r) for r in rows]})
    except Exception as exc:
        logger.error("api/issued GET error: %s", exc)
        return jsonify({"success": False, "error": "Failed to retrieve issued books"}), 500


@api_bp.route("/issued", methods=["POST"])
@require_roles("Librarian", "Administrator")
def issue_book():
    """Issue a book to a student – Librarian/Administrator only."""
    data = request.get_json(silent=True) or {}
    student_id = data.get("student_id")
    book_id = data.get("book_id")
    if not student_id or not book_id:
        return jsonify({"success": False, "error": "student_id and book_id are required"}), 400
    try:
        conn = get_db_connection(MAIN_DB)
        avail = conn.execute(
            "SELECT available_copies FROM Books WHERE id = ?", (book_id,)
        ).fetchone()
        if avail is None:
            conn.close()
            return jsonify({"success": False, "error": "Book not found"}), 404
        if avail["available_copies"] < 1:
            conn.close()
            return jsonify({"success": False, "error": "No copies available"}), 400
        from datetime import date, timedelta
        issue_date = date.today().isoformat()
        due_date = (date.today() + timedelta(days=14)).isoformat()
        cursor = conn.execute(
            "INSERT INTO Issued (student_id, book_id, issue_date, due_date, status) "
            "VALUES (?, ?, ?, ?, 'Issued')",
            (student_id, book_id, issue_date, due_date),
        )
        conn.execute(
            "UPDATE Books SET available_copies = available_copies - 1 WHERE id = ?",
            (book_id,),
        )
        conn.commit()
        issue_id = cursor.lastrowid
        conn.close()
        return jsonify({"success": True, "message": "Book issued", "issue_id": issue_id}), 201
    except Exception as exc:
        logger.error("api/issued POST error: %s", exc)
        return jsonify({"success": False, "error": "Failed to issue book"}), 500


@api_bp.route("/issued/<int:issue_id>/return", methods=["PUT"])
@require_roles("Librarian", "Administrator")
def return_book(issue_id):
    """Mark an issued book as returned – Librarian/Administrator only."""
    try:
        from datetime import date
        return_date = date.today().isoformat()
        conn = get_db_connection(MAIN_DB)
        row = conn.execute(
            "SELECT book_id, return_date FROM Issued WHERE id = ?", (issue_id,)
        ).fetchone()
        if row is None:
            conn.close()
            return jsonify({"success": False, "error": "Issue record not found"}), 404
        if row["return_date"] is not None:
            conn.close()
            return jsonify({"success": False, "error": "Book already returned"}), 400
        conn.execute(
            "UPDATE Issued SET return_date = ?, status = 'Returned' WHERE id = ?",
            (return_date, issue_id),
        )
        conn.execute(
            "UPDATE Books SET available_copies = available_copies + 1 WHERE id = ?",
            (row["book_id"],),
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Book marked as returned"})
    except Exception as exc:
        logger.error("api/issued return error: %s", exc)
        return jsonify({"success": False, "error": "Failed to process book return"}), 500
