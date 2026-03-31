"""
Authentication routes for SPEAK2DB (login / logout).
"""
import logging
from flask import Blueprint, render_template, request, session, flash, redirect, url_for

from db.connection import get_db_connection, MAIN_DB
from security.auth_utils import verify_stored_password

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

# Map role values stored in the database to dashboard endpoint names.
_ROLE_DASHBOARD = {
    "administrator": "dashboard.admin_dashboard",
    "librarian": "dashboard.librarian_dashboard",
    "faculty": "dashboard.faculty_dashboard",
    "student": "dashboard.student_dashboard",
}


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Login page."""
    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        flash("Please enter username and password", "error")
        return render_template("login.html")

    try:
        conn = get_db_connection(MAIN_DB)
        user = conn.execute(
            "SELECT id, username, password, role FROM Users WHERE username = ?",
            (username,),
        ).fetchone()
        conn.close()
    except Exception as exc:
        logger.error("Login DB error: %s", exc)
        flash("Invalid username or password", "error")
        return render_template("login.html")

    if not user or not verify_stored_password(user["password"], password):
        logger.warning("Failed login attempt for username: %s", username)
        flash("Invalid username or password", "error")
        return render_template("login.html")

    role = user["role"]
    session["user_id"] = user["username"]
    session["username"] = user["username"]  # explicit username key for per-user routing
    session["user_role"] = role
    session["role"] = role  # kept for backward-compatibility with existing code

    # Populate student_id for Student accounts.
    # Student usernames are their roll numbers, which are also stored in
    # the Students table, so we can look them up directly.
    session["student_id"] = None
    if role == "Student":
        try:
            conn = get_db_connection(MAIN_DB)
            student = conn.execute(
                "SELECT id FROM Students WHERE roll_number = ?",
                (username,),
            ).fetchone()
            conn.close()
            if student:
                session["student_id"] = student["id"]
        except Exception as exc:
            logger.warning("Could not look up student_id for %s: %s", username, exc)

    logger.info("User '%s' logged in with role '%s'", session["user_id"], role)
    flash(f"Welcome, {role}!", "success")

    dashboard_endpoint = _ROLE_DASHBOARD.get(role.lower())
    if dashboard_endpoint:
        return redirect(url_for(dashboard_endpoint))
    return redirect(url_for("index"))


@auth_bp.route("/logout")
def logout():
    """Logout the current user."""
    user_id = session.get("user_id", "unknown")
    session.clear()
    logger.info("User '%s' logged out", user_id)
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))
