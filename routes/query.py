"""
NL-to-SQL query pipeline route for SPEAK2DB.
"""
import logging
import time
from flask import Blueprint, request, jsonify, session, redirect, url_for

from db.connection import get_db_connection, MAIN_DB
from utils.constants import DEFAULT_QUERY_LIMIT
from utils.sql_safety import (
    is_safe_sql,
    apply_student_filters,
    enforce_student_filter,
    validate_sql_query,
    fallback_columns,
    ensure_limit,
)

try:
    from domain_vocabulary import preprocess_query
    _VOCAB_AVAILABLE = True
except ImportError:
    _VOCAB_AVAILABLE = False

try:
    from clarification import is_vague_query, get_clarification, apply_clarification_choice
    _CLARIF_AVAILABLE = True
except ImportError:
    _CLARIF_AVAILABLE = False

try:
    from query_correction import correct_query
    _CORRECT_AVAILABLE = True
except ImportError:
    _CORRECT_AVAILABLE = False

try:
    from query_context import save_context, is_followup, rewrite_followup, get_last_query
    _CONTEXT_AVAILABLE = True
except ImportError:
    _CONTEXT_AVAILABLE = False

try:
    from rbac_system_fixed import rbac, apply_row_level_filter
    _RBAC_AVAILABLE = True
except ImportError:
    _RBAC_AVAILABLE = False

try:
    from security_layer import validate_sql as security_validate_sql
    _SECURITY_LAYER_AVAILABLE = True
except ImportError:
    _SECURITY_LAYER_AVAILABLE = False

try:
    from ollama_sql import generate_sql
    _OLLAMA_AVAILABLE = True
except ImportError:
    _OLLAMA_AVAILABLE = False

logger = logging.getLogger(__name__)

query_bp = Blueprint("query", __name__)


@query_bp.route("/query", methods=["POST"])
def query():
    """NL-to-SQL query pipeline (10 steps).

    1.  Spell correction
    2.  Context follow-up detection & rewrite
    3.  Clarification detection (vague query → ask user)
    4.  Apply clarification choice when provided
    5.  Vocabulary preprocessing (schema hints)
    6.  SQL generation via Ollama (with fallback on failure)
    7.  Student-specific SQL rewriting / row-level filtering
    8.  SQL safety gate (SELECT-only, no DDL/write keywords)
    9.  RBAC table-access validation
    10. Execute & return results
    """
    logger.info("Query received – processing request")

    if "user_id" not in session:
        logger.warning("Query attempted without active session")
        return jsonify({"success": False, "error": "Not logged in"}), 401

    try:
        _query_start = time.time()

        data = request.get_json()
        user_query = data.get("query", "").strip()
        clarification_choice = data.get("clarification_choice", "").strip()
        logger.info("Query text: %s", user_query)

        user_role = session.get("role", "Student")
        student_id = session.get("student_id")
        logger.info("User role: %s, Student ID: %s", user_role, student_id)

        if not user_query:
            return jsonify({"success": False, "error": "No query provided"}), 400

        # ── Step 1: Spell correction ─────────────────────────────────────────
        if _CORRECT_AVAILABLE:
            corrected = correct_query(user_query)
            if corrected != user_query:
                logger.info("[SPELL FIX] %s", corrected)
            user_query = corrected

        # ── Step 2: Context follow-up detection & rewrite ────────────────────
        logger.debug("[CONTEXT] previous query: %s", session.get("last_query"))
        if _CONTEXT_AVAILABLE and is_followup(user_query):
            last_q = get_last_query(session)
            if last_q:
                user_query = rewrite_followup(user_query, last_q)
                logger.info("[CONTEXT REWRITE] %s", user_query)

        # ── Steps 3 & 4: Clarification chatbot ──────────────────────────────
        if clarification_choice:
            if _CLARIF_AVAILABLE:
                user_query = apply_clarification_choice(user_query, clarification_choice)
            logger.info("Clarification applied: %s", user_query)
        else:
            if _CLARIF_AVAILABLE:
                clarif = get_clarification(user_query)
                if clarif is not None:
                    logger.info("Ambiguous query – returning clarification options")
                    return jsonify({"needs_clarification": True, "clarification": clarif})

        # ── Step 5: Vocabulary preprocessing ────────────────────────────────
        augmented_query = user_query
        if _VOCAB_AVAILABLE:
            augmented_query = preprocess_query(user_query, MAIN_DB)
            if augmented_query != user_query:
                logger.info("[VOCABULARY HINTS] %s", augmented_query)

        logger.debug("Connecting to database")
        conn = get_db_connection(MAIN_DB)

        # ── Step 6: SQL generation via Ollama ────────────────────────────────
        sql_query = ""
        if _OLLAMA_AVAILABLE:
            try:
                sql_query = generate_sql(augmented_query)
            except Exception as ollama_exc:
                logger.error("LLM (Ollama) service error: %s", ollama_exc)
                conn.close()
                return jsonify({"success": False, "error": "LLM service not available"}), 500

        if not sql_query or not sql_query.strip():
            logger.warning("[FALLBACK SQL] generate_sql returned empty; using default")
            # This fallback is intentionally safe: student-specific filters
            # (Step 7) are applied below, so student users will not see
            # unrestricted data even via this default query.
            sql_query = f"SELECT * FROM Books LIMIT {DEFAULT_QUERY_LIMIT}"
        logger.info("Generated SQL: %s", sql_query)

        # Replace student ID placeholders emitted by the SQL generator.
        # Convert to int first to prevent injection via malformed session data.
        if user_role == "Student" and student_id:
            try:
                sql_query = sql_query.replace("[CURRENT_STUDENT_ID]", str(int(student_id)))
            except (TypeError, ValueError):
                logger.error("Invalid student_id in session: %r", student_id)

        # ── Step 7: Student-specific SQL rewriting ───────────────────────────
        logger.debug("Role: %s | Student filter applied: %s", user_role, student_id)
        if user_role == "Student" and student_id:
            sql_query = enforce_student_filter(user_query, sql_query, session)

        # ── Step 8: Security layer (injection check + isolation) ─────────────
        if _SECURITY_LAYER_AVAILABLE:
            allowed, sql_query, sec_error = security_validate_sql(
                sql_query, user_role, student_id
            )
            if not allowed:
                logger.warning("Security layer blocked query: %s", sec_error)
                conn.close()
                return jsonify({"success": False, "error": "Query blocked by security layer"}), 400

        # ── Step 9: Role-based SQL validation ────────────────────────────────
        if not validate_sql_query(sql_query, user_role):
            logger.warning("validate_sql_query blocked query for role=%s: %s", user_role, sql_query)
            conn.close()
            return jsonify({"success": False, "error": "Access Denied"}), 403

        # ── Enforce LIMIT to cap result sets ─────────────────────────────────
        sql_query = ensure_limit(sql_query, DEFAULT_QUERY_LIMIT)

        # ── Step 10: RBAC table-access validation ────────────────────────────
        if _RBAC_AVAILABLE:
            user_id_for_rbac = session.get("user_id", "")
            ok, msg = rbac.validate_query_access(user_id_for_rbac, sql_query)
            if not ok:
                logger.warning("RBAC denied: %s", msg)
                conn.close()
                return jsonify({"success": False, "error": f"Access denied: {msg}"}), 403

            if user_role == "Student" and student_id:
                sql_query = apply_row_level_filter(str(student_id), sql_query)

        logger.info("[EXECUTING SQL] %s", sql_query)
        results = conn.execute(sql_query).fetchall()
        conn.close()

        rows = [dict(row) for row in results]

        session["last_query"] = user_query
        session["last_sql"] = sql_query

        columns = list(rows[0].keys()) if rows else fallback_columns(sql_query)

        logger.info("Returning %d rows with columns: %s", len(rows), columns)

        if _CONTEXT_AVAILABLE:
            save_context(session, user_query, sql_query)

        elapsed = round(time.time() - _query_start, 4)
        return jsonify(
            {
                "success": True,
                "data": rows,
                "columns": columns,
                "sql": sql_query,
                "database": MAIN_DB,
                "user_role": user_role,
                "student_id": student_id,
                "elapsed_seconds": elapsed,
            }
        )

    except Exception as exc:
        logger.error("Query execution failed: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": f"Query execution failed: {str(exc)}"}), 500


@query_bp.route("/query", methods=["GET"])
def query_page():
    """Redirect GET /query to main dashboard (query console is on the main page)."""
    if "user_id" not in session:
        return redirect(url_for("login"))
    return redirect(url_for("index"))
