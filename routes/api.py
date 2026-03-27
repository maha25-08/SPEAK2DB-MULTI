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
