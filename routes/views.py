"""
Miscellaneous view routes for SPEAK2DB
(analytics, recommendations, students, issued books, fines, user management, system stats).
"""
import logging
from flask import Blueprint, render_template, session, redirect, url_for

from db.connection import get_db_connection, MAIN_DB
from utils.decorators import require_roles
from utils.helpers import get_library_stats

logger = logging.getLogger(__name__)

views_bp = Blueprint("views", __name__)


# ---------------------------------------------------------------------------
# Generic dashboard redirect
# ---------------------------------------------------------------------------

@views_bp.route("/dashboard")
def dashboard_redirect():
    """Redirect to the appropriate role-specific dashboard."""
    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") == "Student":
        return redirect(url_for("dashboard.student_dashboard"))
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Analytics (Admin only)
# ---------------------------------------------------------------------------

@views_bp.route("/analytics")
@require_roles("Administrator")
def analytics():
    """Analytics view – Administrator only."""
    user_role = session.get("role", "Student")
    user_id = session["user_id"]

    books_per_category = []
    issues_per_month = []
    try:
        conn = get_db_connection(MAIN_DB)
        books_per_category = conn.execute(
            "SELECT category, COUNT(*) as count FROM Books GROUP BY category ORDER BY count DESC"
        ).fetchall()
        issues_per_month = conn.execute(
            "SELECT strftime('%Y-%m', issue_date) as month, COUNT(*) as count "
            "FROM Issued GROUP BY month ORDER BY month DESC LIMIT 12"
        ).fetchall()
        conn.close()
    except Exception as exc:
        logger.error("analytics DB error: %s", exc)

    return render_template(
        "analytics.html",
        user=user_id,
        role=user_role,
        books_per_category=[dict(r) for r in books_per_category],
        issues_per_month=[dict(r) for r in issues_per_month],
    )


# ---------------------------------------------------------------------------
# Recommendations (Admin only)
# ---------------------------------------------------------------------------

@views_bp.route("/recommendations")
@require_roles("Administrator")
def recommendations():
    """Recommendations view – Administrator only."""
    user_role = session.get("role", "Student")
    user_id = session["user_id"]
    users = []
    students = []
    try:
        conn = get_db_connection(MAIN_DB)
        users = conn.execute("SELECT * FROM Users LIMIT 500").fetchall()
        students = conn.execute(
            "SELECT id, roll_number, name, branch, year FROM Students ORDER BY name LIMIT 500"
        ).fetchall()
        conn.close()
    except Exception as exc:
        logger.error("recommendations DB error: %s", exc)

    return render_template(
        "admin_dashboard.html",
        role=user_role,
        user=user_id,
        stats={},
        recent_activity=[],
        users=users,
        students=students,
        page="user_management",
    )


# ---------------------------------------------------------------------------
# Students view (Librarian / Admin)
# ---------------------------------------------------------------------------

@views_bp.route("/students")
@require_roles("Librarian", "Faculty", "Administrator")
def students_view():
    """All students – Librarian/Administrator only."""
    user_id = session["user_id"]
    user_role = session.get("role")

    return render_template(
        "index.html",
        user=user_id,
        role=user_role,
        user_info={"username": user_id, "role": user_role, "permissions": []},
        page_title="All Students",
        dashboard_data=get_library_stats(),
        prefill_query="show all students",
    )


# ---------------------------------------------------------------------------
# Issued books view (Librarian / Admin)
# ---------------------------------------------------------------------------

@views_bp.route("/issued_books")
@require_roles("Librarian", "Faculty", "Administrator")
def issued_books_view():
    """Issued books overview – Librarian/Administrator only."""
    user_id = session["user_id"]
    user_role = session.get("role")

    return render_template(
        "index.html",
        user=user_id,
        role=user_role,
        user_info={"username": user_id, "role": user_role, "permissions": []},
        page_title="Issued Books",
        dashboard_data=get_library_stats(),
        prefill_query="show all currently issued books",
    )


# ---------------------------------------------------------------------------
# Fine management (Librarian / Admin)
# ---------------------------------------------------------------------------

@views_bp.route("/fine_management")
@require_roles("Librarian", "Faculty", "Administrator")
def fine_management_view():
    """Fine management – Librarian/Administrator only."""
    user_id = session["user_id"]
    user_role = session.get("role")

    return render_template(
        "index.html",
        user=user_id,
        role=user_role,
        user_info={"username": user_id, "role": user_role, "permissions": []},
        page_title="Fine Management",
        dashboard_data=get_library_stats(),
        prefill_query="show all unpaid fines",
    )


@views_bp.route("/fines")
@require_roles("Librarian", "Faculty", "Administrator")
def fines_view():
    """Fines alias – redirects to fine_management."""
    logger.info("fines_view accessed by role: %s", session.get("role"))
    return redirect(url_for("views.fine_management_view"))


# ---------------------------------------------------------------------------
# User management (Admin only)
# ---------------------------------------------------------------------------

@views_bp.route("/user_management")
@require_roles("Administrator")
def user_management_view():
    """User management – Administrator only."""
    user_id = session["user_id"]
    user_role = session.get("role")
    student_count = faculty_count = 0
    students = []
    try:
        conn = get_db_connection(MAIN_DB)
        student_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM Students"
        ).fetchone()["cnt"]
        faculty_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM Faculty"
        ).fetchone()["cnt"]
        students = conn.execute(
            "SELECT id, roll_number, name, branch, year, email, gpa FROM Students ORDER BY name"
        ).fetchall()
        conn.close()
    except Exception as exc:
        logger.error("user_management DB error: %s", exc)

    return render_template(
        "user_management.html",
        user=user_id,
        role=user_role,
        student_count=student_count,
        faculty_count=faculty_count,
        students=students,
    )


# ---------------------------------------------------------------------------
# System statistics (Admin only)
# ---------------------------------------------------------------------------

@views_bp.route("/system_statistics")
def system_statistics_view():
    """System statistics – Administrator only."""
    if "user_id" not in session:
        return redirect(url_for("login"))
    guard = _require_admin()
    if guard:
        return guard

    user_id = session["user_id"]
    user_role = session.get("role")
    sys_stats = {}
    try:
        conn = get_db_connection(MAIN_DB)
        total_books = conn.execute("SELECT COUNT(*) as cnt FROM Books").fetchone()["cnt"]
        total_students = conn.execute(
            "SELECT COUNT(*) as cnt FROM Students"
        ).fetchone()["cnt"]
        active_issues = conn.execute(
            "SELECT COUNT(*) as cnt FROM Issued WHERE return_date IS NULL"
        ).fetchone()["cnt"]
        total_fines = conn.execute(
            "SELECT COALESCE(SUM(fine_amount), 0) as total FROM Fines WHERE status='Unpaid'"
        ).fetchone()["total"]
        conn.close()
        sys_stats = {
            "total_books": total_books,
            "total_students": total_students,
            "active_issues": active_issues,
            "total_unpaid_fines": total_fines,
        }
    except Exception as exc:
        logger.error("system_statistics DB error: %s", exc)

    return render_template(
        "system_statistics.html",
        user=user_id,
        role=user_role,
        sys_stats=sys_stats,
    )
