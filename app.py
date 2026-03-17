"""
🗃️ SPEAK2DB - NL-to-SQL Query Assistant
Integrated with domain vocabulary, clarification chatbot, RBAC,
SQL safety gate, and security headers.
"""

import logging
import os
from datetime import datetime

from flask import Flask, render_template, session, redirect, url_for

# ── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Database package ─────────────────────────────────────────────────────────
from db.connection import get_db_connection, MAIN_DB, ARCHIVE_DB, ensure_query_history_schema

# ── Security headers (Option 2 – safe, non-breaking) ────────────────────────
try:
    from security_layers import apply_security_headers
    _SECURITY_HEADERS_AVAILABLE = True
except ImportError:
    _SECURITY_HEADERS_AVAILABLE = False

# ── Route Blueprints ─────────────────────────────────────────────────────────
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.query import query_bp
from routes.api import api_bp
from routes.views import views_bp

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = Flask(__name__)
# Secret key: read from environment for production; fall back to a random key
# for development (note: random key means sessions are lost on restart).
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

# ── Register Blueprints ──────────────────────────────────────────────────────
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(query_bp)
app.register_blueprint(api_bp)
app.register_blueprint(views_bp)

# ── Run DB schema migrations at startup ─────────────────────────────────────
ensure_query_history_schema()

# ── Jinja2 custom filters ────────────────────────────────────────────────────
@app.template_filter("days_overdue")
def days_overdue_filter(due_date_str):
    """Return the number of days a book is overdue (0 if not overdue or invalid)."""
    if not due_date_str:
        return 0
    try:
        due = datetime.strptime(str(due_date_str)[:10], "%Y-%m-%d").date()
        delta = (datetime.now().date() - due).days
        return max(delta, 0)
    except Exception:
        return 0


# ── Security headers on every response ──────────────────────────────────────
if _SECURITY_HEADERS_AVAILABLE:
    @app.after_request
    def add_security_headers(response):
        """Attach HTTP security headers without breaking voice / CSRF-free flow."""
        return apply_security_headers(response)


# ---------------------------------------------------------------------------
# Main dashboard (index) – kept here so url_for('index') resolves correctly
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Main query interface with embedded role-specific dashboard widgets."""
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    user_id = session["user_id"]
    user_role = session.get("role", "Student")
    student_id = session.get("student_id")

    user_info = {"username": user_id, "role": user_role, "permissions": []}

    dashboard_data = {}
    try:
        conn = get_db_connection(MAIN_DB)

        if user_role == "Student" and student_id:
            student_info = conn.execute(
                "SELECT * FROM Students WHERE id = ?", (student_id,)
            ).fetchone()
            current_books = conn.execute(
                """SELECT i.*, b.title, b.author FROM Issued i
                   JOIN Books b ON i.book_id = b.id
                   WHERE i.student_id = ? AND i.return_date IS NULL
                   ORDER BY i.due_date ASC LIMIT 5""",
                (student_id,),
            ).fetchall()
            overdue_books = conn.execute(
                """SELECT i.*, b.title, b.author FROM Issued i
                   JOIN Books b ON i.book_id = b.id
                   WHERE i.student_id = ? AND i.return_date IS NULL
                   AND i.due_date < date('now')""",
                (student_id,),
            ).fetchall()
            unpaid_fines = conn.execute(
                "SELECT * FROM Fines WHERE student_id = ? AND status = 'Unpaid'",
                (student_id,),
            ).fetchall()
            dashboard_data = {
                "student_info": dict(student_info) if student_info else {},
                "current_books": [dict(r) for r in current_books],
                "overdue_count": len(overdue_books),
                "unpaid_fines": len(unpaid_fines),
            }

        elif user_role in ("Librarian", "Faculty", "Administrator"):
            total_books = conn.execute(
                "SELECT COUNT(*) as cnt FROM Books"
            ).fetchone()["cnt"]
            total_students = conn.execute(
                "SELECT COUNT(*) as cnt FROM Students"
            ).fetchone()["cnt"]
            active_issues = conn.execute(
                "SELECT COUNT(*) as cnt FROM Issued WHERE return_date IS NULL"
            ).fetchone()["cnt"]
            unpaid_fines_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM Fines WHERE status = 'Unpaid'"
            ).fetchone()["cnt"]
            dashboard_data = {
                "total_books": total_books,
                "total_students": total_students,
                "active_issues": active_issues,
                "unpaid_fines": unpaid_fines_count,
            }

        conn.close()
    except Exception as exc:
        logger.error("index dashboard data fetch error: %s", exc)

    return render_template(
        "index.html",
        user=user_info.get("username", user_id),
        role=user_role,
        user_info=user_info,
        dashboard_data=dashboard_data,
    )


# ── Alternative UI views ─────────────────────────────────────────────────────

@app.route("/modern")
def modern_ui():
    """Modern interface."""
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    return render_template("modern.html")


@app.route("/minimal")
def minimal_ui():
    """Minimal interface."""
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    return render_template("modern-minimal.html")


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404


@app.errorhandler(500)
def internal_error(error):
    return render_template("500.html"), 500


@app.errorhandler(403)
def forbidden(error):
    return render_template("403.html"), 403


# ---------------------------------------------------------------------------
# Context processor – inject current user into all templates
# ---------------------------------------------------------------------------

@app.context_processor
def inject_user():
    """Make ``current_user`` and ``user_role`` available in every template."""
    if "user_id" in session:
        return {
            "current_user": {
                "username": session["user_id"],
                "role": session.get("role", "Student"),
            },
            "user_role": session.get("role", "Student"),
        }
    return {}


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
