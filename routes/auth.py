"""
Authentication routes for SPEAK2DB (login / logout).
"""
import logging
from flask import Blueprint, render_template, request, session, flash, redirect, url_for

from db.connection import get_db_connection, MAIN_DB
from security.auth_utils import verify_password

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


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

    # ── Static accounts ──────────────────────────────────────────────────────
    if username == "admin" and verify_password(password):
        session["user_id"] = "admin"
        session["role"] = "Administrator"
        session["student_id"] = None
    elif username == "librarian" and verify_password(password):
        session["user_id"] = "librarian"
        session["role"] = "Librarian"
        session["student_id"] = None
    elif username == "faculty_email" and verify_password(password):
        session["user_id"] = "faculty_email"
        session["role"] = "Faculty"
        session["student_id"] = None
    else:
        # ── Dynamic student authentication ───────────────────────────────────
        try:
            conn = get_db_connection(MAIN_DB)
            student = conn.execute(
                "SELECT id, roll_number FROM Students WHERE roll_number = ?",
                (username,),
            ).fetchone()
            conn.close()

            if student and verify_password(password):
                session["user_id"] = username
                session["role"] = "Student"
                session["student_id"] = student["id"]
            else:
                logger.warning("Failed login attempt for username: %s", username)
                flash("Invalid username or password", "error")
                return render_template("login.html")
        except Exception as exc:
            logger.error("Login DB error: %s", exc)
            flash("Invalid username or password", "error")
            return render_template("login.html")

    logger.info("User '%s' logged in with role '%s'", session["user_id"], session["role"])
    flash(f"Welcome, {session['role']}!", "success")
    return redirect(url_for("index"))


@auth_bp.route("/logout")
def logout():
    """Logout the current user."""
    user_id = session.get("user_id", "unknown")
    session.clear()
    logger.info("User '%s' logged out", user_id)
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
