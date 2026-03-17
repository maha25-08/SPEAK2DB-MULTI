"""
🗃️ SPEAK2DB - NL-to-SQL Query Assistant
Integrated with domain vocabulary, clarification chatbot, RBAC,
SQL safety gate, and security headers.
"""

import logging
import os
from datetime import datetime

# ── New pipeline modules ────────────────────────────────────────────────────
from domain_vocabulary import build_vocabulary, preprocess_query, get_vocabulary_sample
from clarification import is_ambiguous_query, get_clarification, apply_clarification_choice
from query_correction import correct_query
from query_context import save_context, is_followup, rewrite_followup, get_last_query

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
_secret_key_env = os.environ.get("SECRET_KEY")
if _secret_key_env:
    app.secret_key = _secret_key_env
else:
    app.secret_key = os.urandom(24)
    logger.warning(
        "SECRET_KEY environment variable is not set. "
        "A random key has been generated — all sessions will be lost on restart. "
        "Set SECRET_KEY in production."
    )

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
        user=user_id,
    )


@app.route('/faculty_dashboard')
def faculty_dashboard_route():
    """Faculty dashboard – Faculty and Librarian roles."""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    role = session.get('role')
    print("Route accessed:", request.path)
    print("User role:", role)

    if role not in ('Faculty', 'Librarian', 'Administrator'):
        return "Access Denied", 403

    user_id = session['user_id']

    # Try to look up faculty info (match by email == user_id or first faculty)
    faculty_info = None
    try:
        conn = get_db_connection(MAIN_DB)
        faculty_info = conn.execute(
            "SELECT * FROM Faculty WHERE email = ? OR name = ? LIMIT 1",
            (user_id, user_id)
        ).fetchone()
        if faculty_info is None:
            faculty_info = conn.execute("SELECT * FROM Faculty LIMIT 1").fetchone()

        total_books = conn.execute("SELECT COUNT(*) as cnt FROM Books").fetchone()['cnt']
        total_students = conn.execute("SELECT COUNT(*) as cnt FROM Students").fetchone()['cnt']
        active_issues = conn.execute(
            "SELECT COUNT(*) as cnt FROM Issued WHERE return_date IS NULL"
        ).fetchone()['cnt']
        unpaid_fines_cnt = conn.execute(
            "SELECT COUNT(*) as cnt FROM Fines WHERE status = 'Unpaid'"
        ).fetchone()['cnt']
        recent_issues = conn.execute(
            """SELECT i.*, b.title, b.author, s.name as student_name
               FROM Issued i
               JOIN Books b ON i.book_id = b.id
               JOIN Students s ON i.student_id = s.id
               ORDER BY i.issue_date DESC LIMIT 10"""
        ).fetchall()
        conn.close()
        stats = {
            'total_books': total_books,
            'total_students': total_students,
            'active_issues': active_issues,
            'unpaid_fines': unpaid_fines_cnt,
        }
    except Exception as e:
        print(f"[faculty_dashboard] DB error: {e}")
        recent_issues = []
        stats = {}

    return render_template(
        'faculty_dashboard.html',
        role=role,
        user=user_id,
        faculty_info=faculty_info,
        stats=stats,
        recent_issues=recent_issues,
    )


@app.route('/librarian_dashboard')
def librarian_dashboard_route():
    """Librarian / Faculty dashboard"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    role = session.get('role')
    print("Route accessed:", request.path)
    print("User role:", role)

    if role not in ('Librarian', 'Faculty', 'Administrator'):
        return "Access Denied", 403

    user_id = session['user_id']

    try:
        conn = get_db_connection(MAIN_DB)
        total_books = conn.execute(
            "SELECT COUNT(*) as cnt FROM Books"
        ).fetchone()['cnt']
        total_students = conn.execute(
            "SELECT COUNT(*) as cnt FROM Students"
        ).fetchone()['cnt']
        active_issues = conn.execute(
            "SELECT COUNT(*) as cnt FROM Issued WHERE return_date IS NULL"
        ).fetchone()['cnt']
        unpaid_fines = conn.execute(
            "SELECT COUNT(*) as cnt FROM Fines WHERE status = 'Unpaid'"
        ).fetchone()['cnt']
        recent_issues = conn.execute(
            """SELECT i.*, b.title, b.author, s.name as student_name
               FROM Issued i
               JOIN Books b ON i.book_id = b.id
               JOIN Students s ON i.student_id = s.id
               ORDER BY i.issue_date DESC LIMIT 10"""
        ).fetchall()
        conn.close()
        stats = {
            'total_books': total_books,
            'total_students': total_students,
            'active_issues': active_issues,
            'unpaid_fines': unpaid_fines,
        }
    except Exception as e:
        print(f"[librarian_dashboard] DB error: {e}")
        recent_issues = []
        stats = {}

    return render_template(
        'librarian_dashboard.html',
        role=role,
        user=user_id,
        stats=stats,
        recent_issues=recent_issues,
    )


@app.route('/admin_dashboard')
def admin_dashboard_route():
    """Administrator dashboard"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'Administrator':
        return "Access Denied", 403

    user_role = session.get('role', 'Administrator')

    user_id = session['user_id']

    try:
        conn = get_db_connection(MAIN_DB)
        total_books = conn.execute(
            "SELECT COUNT(*) as cnt FROM Books"
        ).fetchone()['cnt']
        total_students = conn.execute(
            "SELECT COUNT(*) as cnt FROM Students"
        ).fetchone()['cnt']
        active_issues = conn.execute(
            "SELECT COUNT(*) as cnt FROM Issued WHERE return_date IS NULL"
        ).fetchone()['cnt']
        unpaid_fines_amount = conn.execute(
            "SELECT COALESCE(SUM(fine_amount), 0) as total FROM Fines WHERE status = 'Unpaid'"
        ).fetchone()['total']
        recent_activity = conn.execute(
            """SELECT i.issue_date as date, s.name as user, b.title as detail
               FROM Issued i
               JOIN Books b ON i.book_id = b.id
               JOIN Students s ON i.student_id = s.id
               ORDER BY i.issue_date DESC LIMIT 10"""
        ).fetchall()
        conn.close()
        stats = {
            'total_books': total_books,
            'total_students': total_students,
            'active_issues': active_issues,
            'unpaid_fines_amount': unpaid_fines_amount,
        }
    except Exception as e:
        print(f"[admin_dashboard] DB error: {e}")
        recent_activity = []
        stats = {}

    return render_template(
        'admin_dashboard.html',
        role=user_role,
        user=user_id,
        stats=stats,
        recent_activity=recent_activity,
    )

@app.route('/query', methods=['POST'])
def query():
    """
    NL-to-SQL query pipeline:
      1. Spell correction
      2. Context follow-up detection & query rewrite
      3. Clarification detection (returns options if vague & no choice given)
      4. Apply clarification choice (if provided)
      5. Vocabulary preprocessing (append schema hints)
      6. SQL generation via Ollama
      7. Student-specific SQL rewriting / row-level filtering
      8. SQL safety gate (SELECT-only, no DDL/write keywords)
      9. RBAC table-access validation
      10. Execute & return results
    """
    print("🔍 Query received - Processing request")

    if 'user_id' not in session:
        print("❌ User not logged in")
        return jsonify({'error': 'Not logged in'}), 401

    try:
        _query_start = time.time()

        data = request.get_json()
        user_query = data.get('query', '').strip()
        # Optional: clarification choice sent back from the frontend
        clarification_choice = data.get('clarification_choice', '').strip()
        print(f"📝 Query text: {user_query}")

        user_role = session.get('role', 'Student')
        student_id = session.get('student_id')
        print(f"👤 User role: {user_role}, Student ID: {student_id}")

        if not user_query:
            print("❌ No query provided")
            return jsonify({'error': 'No query provided'}), 400

        # ── Step 1: Spell correction ──────────────────────────────────────
        corrected_query = correct_query(user_query)
        if corrected_query != user_query:
            print("[SPELL FIX]", corrected_query)
        user_query = corrected_query

        # ── Step 2: Context follow-up detection & rewrite ─────────────────
        print("[CONTEXT] previous query:", session.get("last_query"))
        if is_followup(user_query):
            last_q = get_last_query(session)
            if last_q:
                rewritten_query = rewrite_followup(user_query, last_q)
                print("[CONTEXT REWRITE]", rewritten_query)
                user_query = rewritten_query

        # ── Step 3 & 4: Clarification chatbot ────────────────────────────
        if clarification_choice:
            # User selected an option – expand into specific NL query
            user_query = apply_clarification_choice(user_query, clarification_choice)
            print(f"🗣️ Clarification applied: {user_query}")
        else:
            if is_ambiguous_query(user_query):
                clarif = get_clarification(user_query)
                print(f"❓ Ambiguous query – returning clarification options")
                return jsonify({
                    'needs_clarification': True,
                    'clarification': clarif
                })

        # ── Step 5: Vocabulary preprocessing ─────────────────────────────
        augmented_query = preprocess_query(user_query, MAIN_DB)
        if augmented_query != user_query:
            print("[VOCABULARY HINTS]", augmented_query)

        print("🔗 Connecting to database...")
        conn = get_db_connection(MAIN_DB)

        print("🤖 Generating SQL query...")
        sql_query = generate_sql(augmented_query)
        # Defensive guard: generate_sql should always return non-empty, but
        # fall back to a safe default if it somehow doesn't.
        if not sql_query or not sql_query.strip():
            print("[FALLBACK SQL] generate_sql returned empty, using default")
            sql_query = "SELECT * FROM Books LIMIT 10"
        print(f"⚙️ Generated SQL: {sql_query}")

        # Replace student ID placeholders emitted by the SQL generator
        if user_role == 'Student' and student_id:
            sql_query = sql_query.replace('[CURRENT_STUDENT_ID]', str(student_id))

        # ── Step 7: Student-specific SQL rewriting ────────────────────────
        print("Role:", session.get("role"))
        print("Student Filter Applied:", session.get("student_id"))
        if user_role == 'Student' and student_id:
            sql_query = _apply_student_filters(user_query, sql_query, student_id)

        # ── Step 8: Security layer (injection check + table access + isolation)
        if SECURITY_LAYER_AVAILABLE:
            allowed, sql_query, sec_error = security_validate_sql(
                sql_query, user_role, student_id
            )
            if not allowed:
                print(f"🚫 Security layer blocked query: {sec_error}")
                return jsonify({
                    'success': False,
                    'error': 'Query blocked by security layer',
                }), 400

        # ── Step 9: SQL safety gate ───────────────────────────────────────
        safe, reason = _is_safe_sql(sql_query)
        if not safe:
            print(f"🚫 SQL blocked by safety gate: {reason}")
            return jsonify({'error': f'Query not permitted: {reason}'}), 400

        # ── Step 10: RBAC table-access validation ─────────────────────────
        if RBAC_AVAILABLE:
            user_id_for_rbac = session.get('user_id', '')
            ok, msg = rbac.validate_query_access(user_id_for_rbac, sql_query)
            if not ok:
                print(f"🚫 RBAC denied: {msg}")
                return jsonify({'error': f'Access denied: {msg}'}), 403

            # Apply additional row-level filter for students via RBAC helper
            if user_role == 'Student' and student_id:
                sql_query = apply_row_level_filter(str(student_id), sql_query)

        print(f"[EXECUTING SQL] {sql_query}")
        results = conn.execute(sql_query).fetchall()
        conn.close()

        rows = [dict(row) for row in results]

        # Store context for follow-up queries.
        # We store the (possibly rewritten) query so that chained follow-ups
        # continue to reference the correct subject (e.g. "books").
        session["last_query"] = user_query
        session["last_sql"] = sql_query

        # Extract columns dynamically
        if rows:
            columns = list(rows[0].keys())
        else:
            columns = _fallback_columns(sql_query)

        print(f"📊 Returning {len(rows)} rows with columns: {columns}")

        # ── Save context for follow-up queries ────────────────────────────
        save_context(session, user_query, sql_query)

        return jsonify({
            'success':    True,
            'data':       rows,
            'columns':    columns,
            'sql':        sql_query,
            'database':   MAIN_DB,
            'user_role':  user_role,
            'student_id': student_id,
        })

    except Exception as e:
        print(f"❌ Query execution failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Query execution failed: {str(e)}'}), 500

# API endpoints
@app.route('/api/user-info')
def api_user_info():
    """Get user information – fixed to read from session (no NameError)."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    user_id_val = session.get('user_id', '')
    user_role_val = session.get('role', 'Student')
    permissions = []

    if RBAC_AVAILABLE:
        try:
            perms = rbac.get_user_permissions(user_id_val)
            permissions = list(perms)[:20]  # cap for JSON size
        except Exception:
            pass

    return jsonify({
        'username':   user_id_val,
        'role':       user_role_val,
        'student_id': session.get('student_id'),
        'permissions': permissions,
    })

@app.route('/api/ui-config')
def api_ui_config():
    """Get UI configuration"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    return jsonify({
        'role': session.get('role', 'Student'),
        'features': ['text_to_sql', 'voice_input', 'multi_db']
    })

@app.route('/api/dashboard-data')
def api_dashboard_data():
    """Get dashboard data"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    return jsonify({
        'stats': {
            'queries_today': 12,
            'active_users': 3,
            'database_size': '2.4GB',
            'last_update': '2024-02-27 19:30:00'
        },
        'recent_queries': [
            'show all books',
            'list students',
            'check fines'
        ]
    })


@app.route('/api/vocabulary')
def api_vocabulary():
    """
    Debug endpoint – returns vocabulary metadata and a sample.
    GET /api/vocabulary?db=main|archive&rebuild=1
    """
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401

    db_key = request.args.get('db', 'main')
    db_path = ARCHIVE_DB if db_key == 'archive' else MAIN_DB
    force = request.args.get('rebuild', '0') == '1'

    try:
        from domain_vocabulary import get_vocabulary_sample, invalidate_cache
        if force:
            invalidate_cache(db_path)
        sample = get_vocabulary_sample(db_path)
        return jsonify({'success': True, 'vocabulary': sample})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/query_analytics')
def api_query_analytics():
    """Query analytics – Administrator only.

    Returns JSON with:
      - queries_today      int
      - most_common        list of {query, count}
      - top_users          list of {user_id, count}
      - avg_execution_time float (seconds)
      - queries_per_day    list of {date, count}
    """
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if session.get('role') != 'Administrator':
        return jsonify({'error': 'Access denied'}), 403

    try:
        conn = get_db_connection(MAIN_DB)
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        queries_today = conn.execute(
            "SELECT COUNT(*) as cnt FROM QueryHistory WHERE timestamp LIKE ?",
            (today + '%',),
        ).fetchone()['cnt']

        most_common = [
            dict(r) for r in conn.execute(
                "SELECT query, COUNT(*) as count FROM QueryHistory "
                "GROUP BY query ORDER BY count DESC LIMIT 10"
            ).fetchall()
        ]

        top_users = [
            dict(r) for r in conn.execute(
                "SELECT user_id, COUNT(*) as count FROM QueryHistory "
                "GROUP BY user_id ORDER BY count DESC LIMIT 10"
            ).fetchall()
        ]

        avg_row = conn.execute(
            "SELECT AVG(response_time) as avg_time FROM QueryHistory "
            "WHERE response_time IS NOT NULL"
        ).fetchone()
        avg_execution_time = round(avg_row['avg_time'] or 0, 4)

        queries_per_day = [
            dict(r) for r in conn.execute(
                "SELECT substr(timestamp, 1, 10) as date, COUNT(*) as count "
                "FROM QueryHistory GROUP BY date ORDER BY date DESC LIMIT 30"
            ).fetchall()
        ]

        conn.close()
        return jsonify({
            'success': True,
            'queries_today': queries_today,
            'most_common': most_common,
            'top_users': top_users,
            'avg_execution_time': avg_execution_time,
            'queries_per_day': queries_per_day,
        })
    except Exception as e:
        print(f"[api_query_analytics] error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/query', methods=['GET'])
def query_page():
    """Redirect GET /query to main dashboard (query console is on the main page)."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('index'))


@app.route('/analytics')
def analytics():
    """Analytics view – admin only."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'Administrator':
        return "Access Denied", 403
    user_role = session.get('role', 'Student')
    user_id = session['user_id']

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
    except Exception as e:
        print(f"[analytics] DB error: {e}")
        books_per_category = []
        issues_per_month = []

    return render_template('analytics.html',
                           user=user_id,
                           role=user_role,
                           books_per_category=[dict(r) for r in books_per_category],
                           issues_per_month=[dict(r) for r in issues_per_month])


@app.route('/recommendations')
def recommendations():
    """Recommendations view – renders the main dashboard with query console."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'Administrator':
        return "Access Denied", 403
    user_role = session.get('role', 'Student')
    user_id = session['user_id']
    try:
        conn = get_db_connection(MAIN_DB)
        users = conn.execute("SELECT * FROM Users").fetchall()
        students = conn.execute("SELECT id, roll_number, name, branch, year FROM Students ORDER BY name").fetchall()
        conn.close()
    except Exception as e:
        print(f"[user_management] DB error: {e}")
        users = []
        students = []
    return render_template('admin_dashboard.html',
                           role=user_role,
                           user=user_id,
                           stats={},
                           recent_activity=[],
                           users=users,
                           students=students,
                           page='user_management')


# ── Role-protected routes ────────────────────────────────────────────────────

def _require_librarian_or_admin():
    """Return a 403 response when the logged-in user is not at least Librarian."""
    role = session.get('role', 'Student')
    if role not in ('Librarian', 'Faculty', 'Administrator'):
        return "Access Denied", 403
    return None


def _require_admin():
    """Return a 403 response when the logged-in user is not an Administrator."""
    if session.get('role') != 'Administrator':
        return "Access Denied", 403
    return None


@app.route('/students')
def students_view():
    """All students – librarian/admin only."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_librarian_or_admin()
    if redir:
        return redir

    user_id = session['user_id']
    user_role = session.get('role')

    try:
        conn = get_db_connection(MAIN_DB)
        students = conn.execute(
            "SELECT id, roll_number, name, branch, year, email, gpa FROM Students ORDER BY name"
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"[students_view] DB error: {e}")
        students = []

    return render_template('index.html',
                           user=user_id,
                           role=user_role,
                           user_info={'username': user_id, 'role': user_role, 'permissions': []},
                           page_title='All Students',
                           dashboard_data=_get_library_stats(),
                           prefill_query='show all students')


@app.route('/issued_books')
def issued_books_view():
    """Issued books overview – librarian/admin only."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_librarian_or_admin()
    if redir:
        return redir

    user_id = session['user_id']
    user_role = session.get('role')

    return render_template('index.html',
                           user=user_id,
                           role=user_role,
                           user_info={'username': user_id, 'role': user_role, 'permissions': []},
                           page_title='Issued Books',
                           dashboard_data=_get_library_stats(),
                           prefill_query='show all currently issued books')


@app.route('/fine_management')
def fine_management_view():
    """Fine management – librarian/admin only."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_librarian_or_admin()
    if redir:
        return redir

    user_id = session['user_id']
    user_role = session.get('role')

    return render_template('index.html',
                           user=user_id,
                           role=user_role,
                           user_info={'username': user_id, 'role': user_role, 'permissions': []},
                           page_title='Fine Management',
                           dashboard_data=_get_library_stats(),
                           prefill_query='show all unpaid fines')


@app.route('/fines')
def fines_view():
    """Fines – alias for fine_management, librarian/admin only."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_librarian_or_admin()
    if redir:
        return redir
    print("Route accessed:", request.path)
    print("User role:", session.get("role"))
    return redirect(url_for('fine_management_view'))


# ── JSON API endpoints ───────────────────────────────────────────────────────

@app.route('/api/students')
def api_students():
    """Return all students as JSON – librarian/admin only."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if session.get('role') not in ('Librarian', 'Faculty', 'Administrator'):
        return jsonify({'error': 'Access denied'}), 403
    print("Route accessed:", request.path)
    print("User role:", session.get("role"))
    try:
        conn = get_db_connection(MAIN_DB)
        rows = conn.execute(
            "SELECT id, roll_number, name, branch, year, email, gpa FROM Students ORDER BY name"
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        print(f"[api_students] error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/issued_books')
def api_issued_books():
    """Return currently issued books as JSON – librarian/admin only."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if session.get('role') not in ('Librarian', 'Faculty', 'Administrator'):
        return jsonify({'error': 'Access denied'}), 403
    print("Route accessed:", request.path)
    print("User role:", session.get("role"))
    try:
        conn = get_db_connection(MAIN_DB)
        rows = conn.execute(
            """SELECT i.id, s.roll_number, s.name as student_name, b.title, b.author,
                      i.issue_date, i.due_date, i.return_date, i.status
               FROM Issued i
               JOIN Books b ON i.book_id = b.id
               JOIN Students s ON i.student_id = s.id
               WHERE i.return_date IS NULL
               ORDER BY i.issue_date DESC"""
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        print(f"[api_issued_books] error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/fines')
def api_fines():
    """Return fines as JSON – librarian/admin only."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    if session.get('role') not in ('Librarian', 'Faculty', 'Administrator'):
        return jsonify({'error': 'Access denied'}), 403
    print("Route accessed:", request.path)
    print("User role:", session.get("role"))
    try:
        conn = get_db_connection(MAIN_DB)
        rows = conn.execute(
            """SELECT f.id, s.roll_number, s.name as student_name,
                      f.fine_amount, f.fine_type, f.status, f.issue_date
               FROM Fines f
               JOIN Students s ON f.student_id = s.id
               ORDER BY f.issue_date DESC"""
        ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        print(f"[api_fines] error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/user_management')
def user_management_view():
    """User management – admin only."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_admin()
    if redir:
        return redir

    user_id = session['user_id']
    user_role = session.get('role')

    try:
        conn = get_db_connection(MAIN_DB)
        student_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM Students"
        ).fetchone()['cnt']
        faculty_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM Faculty"
        ).fetchone()['cnt']
        students = conn.execute(
            "SELECT id, roll_number, name, branch, year, email, gpa FROM Students ORDER BY name"
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"[user_management] DB error: {e}")
        student_count = faculty_count = 0
        students = []

    return render_template('user_management.html',
                           user=user_id,
                           role=user_role,
                           student_count=student_count,
                           faculty_count=faculty_count,
                           students=students)


@app.route('/system_statistics')
def system_statistics_view():
    """System statistics – admin only."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    redir = _require_admin()
    if redir:
        return redir

    user_id = session['user_id']
    user_role = session.get('role')

    try:
        conn = get_db_connection(MAIN_DB)
        total_books = conn.execute("SELECT COUNT(*) as cnt FROM Books").fetchone()['cnt']
        total_students = conn.execute("SELECT COUNT(*) as cnt FROM Students").fetchone()['cnt']
        active_issues = conn.execute(
            "SELECT COUNT(*) as cnt FROM Issued WHERE return_date IS NULL"
        ).fetchone()['cnt']
        total_fines = conn.execute(
            "SELECT COALESCE(SUM(fine_amount), 0) as total FROM Fines WHERE status='Unpaid'"
        ).fetchone()['total']
        conn.close()
        sys_stats = {
            'total_books': total_books,
            'total_students': total_students,
            'active_issues': active_issues,
            'total_unpaid_fines': total_fines,
        }
    except Exception as e:
        print(f"[system_statistics] DB error: {e}")
        sys_stats = {}

    return render_template('system_statistics.html',
                           user=user_id,
                           role=user_role,
                           sys_stats=sys_stats)


@app.route('/admin-dashboard')
def admin_dashboard():
    """Administrator dashboard."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session.get('role') != 'Administrator':
        return "Access Denied", 403
    user_role = session.get('role', 'Student')

    user_id = session['user_id']

    # Gather system stats for the admin view
    try:
        conn = get_db_connection(MAIN_DB)
        total_users     = conn.execute("SELECT COUNT(*) FROM Users").fetchone()[0]
        total_students  = conn.execute("SELECT COUNT(*) FROM Students").fetchone()[0]
        total_faculty   = conn.execute("SELECT COUNT(*) FROM Faculty").fetchone()[0]
        total_depts     = conn.execute("SELECT COUNT(*) FROM Departments").fetchone()[0]
        conn.close()
    except Exception as e:
        print(f"⚠️ Admin dashboard stats error: {e}")
        total_users = total_students = total_faculty = total_depts = 0

    return render_template(
        'dashboard_rbac.html',
        user_info={'user_id': user_id, 'role': user_role},
        role_badge_class='role-administrator',
        menu_items=[
            {'icon': '📊', 'label': 'Dashboard',     'url': '/admin-dashboard'},
            {'icon': '🔍', 'label': 'Query Console', 'url': '/'},
            {'icon': '📈', 'label': 'Analytics',     'url': '/analytics'},
            {'icon': '💡', 'label': 'Recommendations','url': '/recommendations'},
            {'icon': '⏻', 'label': 'Logout',        'url': '/logout'},
        ],
        permissions_summary={'permission_count': 50, 'table_count': 10, 'role_level': 3},
        search_config={
            'enabled': True,
            'placeholder': 'Search users, reports...',
            'suggestions': [
                'List all students', 'Show overdue books',
                'Faculty list', 'Show all fines',
            ],
        },
        dashboard_widgets=[
            {'type': 'system_overview', 'title': 'System Overview', 'icon': '🖥️'},
        ],
        data={
            'system_stats': {
                'total_users':       total_users,
                'total_students':    total_students,
                'total_faculty':     total_faculty,
                'total_departments': total_depts,
            }
        },
        theme_css='',
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
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    app.run(debug=debug_mode, host="0.0.0.0", port=5000)
