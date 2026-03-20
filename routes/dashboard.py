"""
Dashboard routes for SPEAK2DB.

Canonical URL scheme (snake_case):
  /student_dashboard      – student personal dashboard
  /faculty_dashboard      – faculty view
  /librarian_dashboard    – librarian view
  /admin_dashboard        – administrator view

Kebab-case aliases redirect to the canonical form for backward compatibility.
"""
import logging
import jinja2
from flask import Blueprint, render_template, session, redirect, url_for

from db.connection import get_db_connection, MAIN_DB
from utils.helpers import get_library_stats

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__)


# ---------------------------------------------------------------------------
# Student dashboard (canonical)
# ---------------------------------------------------------------------------

@dashboard_bp.route("/student_dashboard")
def student_dashboard():
    """Student dashboard (canonical snake_case route)."""
    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "Student":
        return "Access Denied", 403

    user_role = session.get("role", "Student")
    user_id = session["user_id"]
    student_id = session.get("student_id")

    try:
        conn = get_db_connection(MAIN_DB)
        student_info = conn.execute(
            "SELECT * FROM Students WHERE id = ?", (student_id,)
        ).fetchone()
        current_books = conn.execute(
            """SELECT i.*, b.title, b.author FROM Issued i
               JOIN Books b ON i.book_id = b.id
               WHERE i.student_id = ? AND i.return_date IS NULL
               ORDER BY i.due_date ASC""",
            (student_id,),
        ).fetchall()
        overdue_books = conn.execute(
            """SELECT i.*, b.title, b.author FROM Issued i
               JOIN Books b ON i.book_id = b.id
               WHERE i.student_id = ? AND i.return_date IS NULL
               AND i.due_date < date('now')
               ORDER BY i.due_date ASC""",
            (student_id,),
        ).fetchall()
        borrowing_history = conn.execute(
            """SELECT i.*, b.title, b.author FROM Issued i
               JOIN Books b ON i.book_id = b.id
               WHERE i.student_id = ? ORDER BY i.issue_date DESC""",
            (student_id,),
        ).fetchall()
        unpaid_fines = conn.execute(
            "SELECT * FROM Fines WHERE student_id = ? AND status = 'Unpaid' ORDER BY issue_date DESC",
            (student_id,),
        ).fetchall()
        all_fines = conn.execute(
            "SELECT * FROM Fines WHERE student_id = ? ORDER BY issue_date DESC",
            (student_id,),
        ).fetchall()
        reservations = conn.execute(
            """SELECT r.*, b.title, b.author FROM Reservations r
               JOIN Books b ON r.book_id = b.id
               WHERE r.student_id = ? ORDER BY r.reservation_date DESC""",
            (student_id,),
        ).fetchall()
        conn.close()
        stats = {
            "total_borrowed": len(borrowing_history),
            "current_borrowed": len(current_books),
            "total_fines": len(all_fines),
            "unpaid_fines": len(unpaid_fines),
            "pending_requests": len(reservations),
        }
    except Exception as exc:
        logger.error("student_dashboard DB error: %s", exc)
        student_info = None
        current_books = overdue_books = borrowing_history = []
        unpaid_fines = all_fines = reservations = []
        stats = {}

    return render_template(
        "student_dashboard.html",
        student_info=student_info,
        borrowing_history=borrowing_history,
        current_books=current_books,
        overdue_books=overdue_books,
        unpaid_fines=unpaid_fines,
        reservations=reservations,
        stats=stats,
        role=user_role,
        user=user_id,
    )


# ---------------------------------------------------------------------------
# Kebab-case aliases → redirect to canonical routes
# ---------------------------------------------------------------------------

@dashboard_bp.route("/student-dashboard")
def student_dashboard_kebab():
    """Redirect legacy kebab-case URL to canonical student dashboard."""
    return redirect(url_for("dashboard.student_dashboard"), code=301)


@dashboard_bp.route("/student/dashboard")
def student_dashboard_alt():
    """Redirect legacy alternative URL to canonical student dashboard."""
    return redirect(url_for("dashboard.student_dashboard"), code=301)


@dashboard_bp.route("/student-dashboard-individual")
def student_dashboard_individual():
    """Individual per-student template (roll-number-specific HTML file)."""
    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "Student":
        return redirect(url_for("index"))

    roll_number = session.get("user_id")
    if not roll_number:
        return redirect(url_for("login"))

    template_name = f"student_dashboard_{roll_number.lower()}.html"
    try:
        return render_template(template_name)
    except jinja2.TemplateNotFound:
        logger.warning("Individual template not found: %s", template_name)
        return redirect(url_for("dashboard.student_dashboard"))


# ---------------------------------------------------------------------------
# Faculty dashboard
# ---------------------------------------------------------------------------

@dashboard_bp.route("/faculty_dashboard")
def faculty_dashboard():
    """Faculty dashboard – Faculty, Librarian, and Administrator roles."""
    if "user_id" not in session:
        return redirect(url_for("login"))

    role = session.get("role")
    logger.debug("faculty_dashboard accessed by role: %s", role)

    if role not in ("Faculty", "Librarian", "Administrator"):
        return "Access Denied", 403

    user_id = session["user_id"]
    faculty_info = None
    recent_issues = []

    try:
        conn = get_db_connection(MAIN_DB)
        faculty_info = conn.execute(
            "SELECT * FROM Faculty WHERE email = ? OR name = ? LIMIT 1",
            (user_id, user_id),
        ).fetchone()
        if faculty_info is None:
            faculty_info = conn.execute("SELECT * FROM Faculty LIMIT 1").fetchone()
        recent_issues = conn.execute(
            """SELECT i.*, b.title, b.author, s.name as student_name
               FROM Issued i
               JOIN Books b ON i.book_id = b.id
               JOIN Students s ON i.student_id = s.id
               ORDER BY i.issue_date DESC LIMIT 10"""
        ).fetchall()
        conn.close()
    except Exception as exc:
        logger.error("faculty_dashboard DB error: %s", exc)

    stats = get_library_stats()

    return render_template(
        "faculty_dashboard.html",
        role=role,
        user=user_id,
        faculty_info=faculty_info,
        stats=stats,
        recent_issues=recent_issues,
    )


# ---------------------------------------------------------------------------
# Librarian dashboard
# ---------------------------------------------------------------------------

@dashboard_bp.route("/librarian_dashboard")
def librarian_dashboard():
    """Librarian dashboard."""
    if "user_id" not in session:
        return redirect(url_for("login"))

    role = session.get("role")
    logger.debug("librarian_dashboard accessed by role: %s", role)

    if role not in ("Librarian", "Faculty", "Administrator"):
        return "Access Denied", 403

    user_id = session["user_id"]
    recent_issues = []

    try:
        conn = get_db_connection(MAIN_DB)
        recent_issues = conn.execute(
            """SELECT i.*, b.title, b.author, s.name as student_name
               FROM Issued i
               JOIN Books b ON i.book_id = b.id
               JOIN Students s ON i.student_id = s.id
               ORDER BY i.issue_date DESC LIMIT 10"""
        ).fetchall()
        conn.close()
    except Exception as exc:
        logger.error("librarian_dashboard DB error: %s", exc)

    stats = get_library_stats()

    return render_template(
        "librarian_dashboard.html",
        role=role,
        user=user_id,
        stats=stats,
        recent_issues=recent_issues,
    )


@dashboard_bp.route("/librarian-dashboard")
def librarian_dashboard_kebab():
    """Redirect legacy kebab-case URL to canonical librarian dashboard."""
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    user_role = session.get("role", "Student")

    # Gather library stats for the RBAC dashboard template
    try:
        conn = get_db_connection(MAIN_DB)
        total_books = conn.execute("SELECT COUNT(*) as cnt FROM Books").fetchone()["cnt"]
        available_books = conn.execute(
            "SELECT COUNT(*) as cnt FROM Books WHERE available_copies > 0"
        ).fetchone()["cnt"]
        issued_books = conn.execute(
            "SELECT COUNT(*) as cnt FROM Issued WHERE return_date IS NULL"
        ).fetchone()["cnt"]
        overdue_books = conn.execute(
            "SELECT COUNT(*) as cnt FROM Issued WHERE return_date IS NULL "
            "AND date(due_date) < date('now')"
        ).fetchone()["cnt"]
        conn.close()
    except Exception as exc:
        logger.error("librarian_dashboard_kebab stats error: %s", exc)
        total_books = available_books = issued_books = overdue_books = 0

    return render_template(
        "dashboard_rbac.html",
        user_info={"user_id": user_id, "role": user_role},
        role_badge_class="role-librarian",
        menu_items=[
            {"icon": "📚", "label": "Dashboard", "url": "/librarian-dashboard"},
            {"icon": "🔍", "label": "Query Console", "url": "/"},
            {"icon": "📈", "label": "Analytics", "url": "/analytics"},
            {"icon": "💡", "label": "Recommendations", "url": "/recommendations"},
            {"icon": "⏻", "label": "Logout", "url": "/logout"},
        ],
        permissions_summary={"permission_count": 30, "table_count": 8, "role_level": 2},
        search_config={
            "enabled": True,
            "placeholder": "Search books, students, fines...",
            "suggestions": [
                "Show overdue books",
                "List all students",
                "Unpaid fines",
                "Available books",
            ],
        },
        dashboard_widgets=[
            {"type": "library_stats", "title": "Library Statistics", "icon": "📚"}
        ],
        data={
            "library_stats": {
                "total_books": total_books,
                "available_books": available_books,
                "issued_books": issued_books,
                "overdue_books": overdue_books,
            }
        },
        theme_css="",
    )


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------

@dashboard_bp.route("/admin_dashboard")
def admin_dashboard():
    """Administrator dashboard."""
    if "user_id" not in session:
        return redirect(url_for("login"))

    if session.get("role") != "Administrator":
        return "Access Denied", 403

    user_role = session.get("role", "Administrator")
    user_id = session["user_id"]
    recent_activity = []
    stats = {}

    try:
        conn = get_db_connection(MAIN_DB)
        total_books = conn.execute("SELECT COUNT(*) as cnt FROM Books").fetchone()["cnt"]
        total_students = conn.execute(
            "SELECT COUNT(*) as cnt FROM Students"
        ).fetchone()["cnt"]
        active_issues = conn.execute(
            "SELECT COUNT(*) as cnt FROM Issued WHERE return_date IS NULL"
        ).fetchone()["cnt"]
        unpaid_fines_amount = conn.execute(
            "SELECT COALESCE(SUM(fine_amount), 0) as total FROM Fines WHERE status = 'Unpaid'"
        ).fetchone()["total"]
        recent_activity = conn.execute(
            """SELECT i.issue_date as date, s.name as user, b.title as detail
               FROM Issued i
               JOIN Books b ON i.book_id = b.id
               JOIN Students s ON i.student_id = s.id
               ORDER BY i.issue_date DESC LIMIT 10"""
        ).fetchall()
        conn.close()
        stats = {
            "total_books": total_books,
            "total_students": total_students,
            "active_issues": active_issues,
            "unpaid_fines_amount": unpaid_fines_amount,
        }
    except Exception as exc:
        logger.error("admin_dashboard DB error: %s", exc)

    return render_template(
        "admin_dashboard.html",
        role=user_role,
        user=user_id,
        stats=stats,
        recent_activity=recent_activity,
    )


@dashboard_bp.route("/admin-dashboard")
def admin_dashboard_kebab():
    """Administrator dashboard (RBAC template view)."""
    if "user_id" not in session:
        return redirect(url_for("login"))
    if session.get("role") != "Administrator":
        return "Access Denied", 403

    user_role = session.get("role", "Student")
    user_id = session["user_id"]

    try:
        conn = get_db_connection(MAIN_DB)
        total_users = conn.execute("SELECT COUNT(*) as cnt FROM Users").fetchone()["cnt"]
        total_students = conn.execute("SELECT COUNT(*) as cnt FROM Students").fetchone()["cnt"]
        total_faculty = conn.execute("SELECT COUNT(*) as cnt FROM Faculty").fetchone()["cnt"]
        total_depts = conn.execute("SELECT COUNT(*) as cnt FROM Departments").fetchone()["cnt"]
        conn.close()
    except Exception as exc:
        logger.error("admin_dashboard_kebab stats error: %s", exc)
        total_users = total_students = total_faculty = total_depts = 0

    return render_template(
        "dashboard_rbac.html",
        user_info={"user_id": user_id, "role": user_role},
        role_badge_class="role-administrator",
        menu_items=[
            {"icon": "📊", "label": "Dashboard", "url": "/admin-dashboard"},
            {"icon": "🔍", "label": "Query Console", "url": "/"},
            {"icon": "📈", "label": "Analytics", "url": "/analytics"},
            {"icon": "💡", "label": "Recommendations", "url": "/recommendations"},
            {"icon": "⏻", "label": "Logout", "url": "/logout"},
        ],
        permissions_summary={"permission_count": 50, "table_count": 10, "role_level": 3},
        search_config={
            "enabled": True,
            "placeholder": "Search users, reports...",
            "suggestions": [
                "List all students",
                "Show overdue books",
                "Faculty list",
                "Show all fines",
            ],
        },
        dashboard_widgets=[
            {"type": "system_overview", "title": "System Overview", "icon": "🖥️"}
        ],
        data={
            "system_stats": {
                "total_users": total_users,
                "total_students": total_students,
                "total_faculty": total_faculty,
                "total_departments": total_depts,
            }
        },
        theme_css="",
    )
