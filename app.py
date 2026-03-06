"""
🗃️ SPEAK2DB - NL-to-SQL Query Assistant
Integrated with domain vocabulary, clarification chatbot, RBAC,
SQL safety gate, and security headers (Option 2 – non-breaking).
"""

from flask import Flask, render_template, request, jsonify, session, flash, redirect, url_for
import sqlite3
import os
import jinja2
from ollama_sql import generate_sql
import pandas as pd
import re
from collections import Counter
from datetime import datetime
from typing import Tuple

# ── New pipeline modules ────────────────────────────────────────────────────
from domain_vocabulary import build_vocabulary, preprocess_query, get_vocabulary_sample
from clarification import is_vague_query, get_clarification, apply_clarification_choice

# ── RBAC (row-level + access validation) ────────────────────────────────────
try:
    from rbac_system_fixed import rbac, apply_row_level_filter
    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False

# ── Security headers (Option 2 – safe, non-breaking) ────────────────────────
try:
    from security_layers import apply_security_headers
    SECURITY_HEADERS_AVAILABLE = True
except ImportError:
    SECURITY_HEADERS_AVAILABLE = False

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'

# Database paths
MAIN_DB = "library_main.db"
ARCHIVE_DB = "library_archive.db"

# ── Jinja2 custom filters ────────────────────────────────────────────────────
@app.template_filter('days_overdue')
def days_overdue_filter(due_date_str):
    """Return the number of days a book is overdue (0 if not overdue or invalid)."""
    if not due_date_str:
        return 0
    try:
        due = datetime.strptime(str(due_date_str)[:10], '%Y-%m-%d').date()
        delta = (datetime.now().date() - due).days
        return max(delta, 0)
    except Exception:
        return 0

# ── Option 2: Apply safe security headers to every response ─────────────────
if SECURITY_HEADERS_AVAILABLE:
    @app.after_request
    def add_security_headers(response):
        """Attach HTTP security headers without breaking voice / CSRF-free flow."""
        return apply_security_headers(response)

def get_db_connection(db_path):
    """Get database connection"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _get_library_stats():
    """Fetch common library statistics for librarian/admin dashboard panels."""
    try:
        conn = get_db_connection(MAIN_DB)
        total_books = conn.execute("SELECT COUNT(*) as cnt FROM Books").fetchone()['cnt']
        total_students = conn.execute("SELECT COUNT(*) as cnt FROM Students").fetchone()['cnt']
        active_issues = conn.execute(
            "SELECT COUNT(*) as cnt FROM Issued WHERE return_date IS NULL"
        ).fetchone()['cnt']
        unpaid_fines = conn.execute(
            "SELECT COUNT(*) as cnt FROM Fines WHERE status = 'Unpaid'"
        ).fetchone()['cnt']
        conn.close()
        return {
            'total_books': total_books,
            'total_students': total_students,
            'active_issues': active_issues,
            'unpaid_fines': unpaid_fines,
        }
    except Exception as e:
        print(f"[_get_library_stats] DB error: {e}")
        return {}

# ── SQL safety gate ──────────────────────────────────────────────────────────
# Blocks write / DDL statements and multi-statement SQL to prevent injection.
_BLOCKED_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|REPLACE|MERGE"
    r"|GRANT|REVOKE|EXECUTE|EXEC|CALL|PRAGMA)\b",
    re.IGNORECASE,
)

def _is_safe_sql(sql: str) -> Tuple[bool, str]:
    """
    Return (True, '') if *sql* is a safe single SELECT statement,
    otherwise (False, reason).
    Empty or invalid SQL is automatically replaced with a safe default
    rather than being blocked outright.
    """
    stripped = sql.strip().rstrip(";") if sql else ""

    # Guard: empty SQL (SQL generator failed / Ollama offline) → use default
    if not stripped:
        return True, ""

    # Must start with SELECT
    if not stripped.upper().startswith("SELECT"):
        return False, "Only SELECT queries are permitted."

    # Block dangerous keywords
    match = _BLOCKED_KEYWORDS.search(stripped)
    if match:
        return False, f"Keyword '{match.group()}' is not allowed."

    # Block multiple statements (naive semicolon check)
    if ";" in stripped:
        return False, "Multi-statement SQL is not permitted."

    return True, ""


def _inject_and_condition(sql_query: str, condition: str) -> str:
    """Inject a filter condition into an existing SQL WHERE clause.

    Inserts ``condition AND`` immediately after the WHERE keyword so the
    student-ID restriction comes first without disturbing any trailing
    ORDER BY / GROUP BY / LIMIT clauses.
    """
    match = re.search(r'\bWHERE\b', sql_query, re.IGNORECASE)
    if match:
        pos = match.end()
        return sql_query[:pos] + f" {condition} AND" + sql_query[pos:]
    # Fallback: no WHERE found – append one (shouldn't normally happen here)
    return sql_query + f" WHERE {condition}"


def _apply_student_filters(user_query: str, sql_query: str, student_id: int) -> str:
    """
    Apply student-specific SQL filters.

    Adds WHERE predicates so students only see their own data.
    For personal tables (Fines, Issued, Reservations) the student_id
    restriction is **always** enforced, even when a WHERE clause already
    exists, to prevent data-privacy leaks from generic queries such as
    "show unpaid fines".
    """
    q_lower = user_query.lower()
    sq_lower = sql_query.lower()
    has_where = 'WHERE' in sql_query.upper()

    # Ensure student_id is a plain integer to prevent SQL injection
    sid = int(student_id)

    # Pattern 1: table-level security – always restrict personal tables to the
    # logged-in student, regardless of whether a WHERE clause already exists.
    for tbl in ('fines', 'issued', 'reservations'):
        if tbl in sq_lower:
            # Only inject when the exact student_id filter is not already present
            already_filtered = bool(
                re.search(r'\bstudent_id\s*=\s*' + str(sid) + r'\b', sql_query, re.IGNORECASE)
            )
            if not already_filtered:
                if has_where:
                    return _inject_and_condition(sql_query, f"student_id = {sid}")
                else:
                    return sql_query + f" WHERE student_id = {sid}"
            return sql_query

    if 'students' in sq_lower and not has_where:
        return sql_query + f" WHERE id = {sid}"

    # Pattern 2: "my …" queries – use safe, schema-correct SQL templates
    if 'my' not in q_lower:
        return sql_query

    _fines_base = (
        f"SELECT f.*, s.name as student_name FROM Fines f "
        f"JOIN Students s ON f.student_id = s.id "
        f"WHERE f.student_id = {sid}"
    )
    _books_base = (
        f"SELECT i.*, b.title, b.author FROM Issued i "
        f"JOIN Books b ON i.book_id = b.id "
        f"WHERE i.student_id = {sid}"
    )
    # Departments join uses Students.branch = Departments.id (the PK column)
    _profile_base = (
        f"SELECT s.*, d.name as department_name FROM Students s "
        f"JOIN Departments d ON s.branch = d.id "
        f"WHERE s.id = {sid}"
    )

    # ── fine / payment patterns ────────────────────────────────────────────
    if any(k in q_lower for k in ('my fines', 'my fine', 'my fine records',
                                   'my payment history', 'my payment records')):
        return _fines_base + " ORDER BY f.issue_date DESC"

    if any(k in q_lower for k in ('my current fines', 'my unpaid fines',
                                   'my outstanding fines')):
        return _fines_base + " AND f.status = 'Unpaid' ORDER BY f.issue_date DESC"

    if 'my outstanding balance' in q_lower or 'my library account balance' in q_lower:
        return (
            f"SELECT s.name, SUM(f.fine_amount) as total_balance "
            f"FROM Students s LEFT JOIN Fines f ON s.id = f.student_id "
            f"WHERE s.id = {sid} AND f.status = 'Unpaid' GROUP BY s.id, s.name"
        )
    if 'my total fines' in q_lower:
        return (
            f"SELECT s.name, SUM(f.fine_amount) as total_balance "
            f"FROM Students s LEFT JOIN Fines f ON s.id = f.student_id "
            f"WHERE s.id = {sid} AND f.status = 'Unpaid' GROUP BY s.id, s.name"
        )

    # ── book / borrowing patterns ──────────────────────────────────────────
    if any(k in q_lower for k in ('my current books', 'books due')):
        return _books_base + " AND i.return_date IS NULL ORDER BY i.due_date ASC"

    if 'my overdue' in q_lower:
        return (
            _books_base
            + " AND i.return_date IS NULL AND i.due_date < date('now')"
        )

    if any(k in q_lower for k in ('my books', 'my issued books', 'my borrowed books',
                                   'my borrowing history', 'my reading history',
                                   'my total books')):
        return _books_base + " ORDER BY i.issue_date DESC"

    # ── reservation patterns ───────────────────────────────────────────────
    if any(k in q_lower for k in ('my reservations', 'my reserved books')):
        return (
            f"SELECT r.*, b.title, b.author FROM Reservations r "
            f"JOIN Books b ON r.book_id = b.id "
            f"WHERE r.student_id = {sid} ORDER BY r.reservation_date DESC"
        )

    # ── profile / account patterns ─────────────────────────────────────────
    if any(k in q_lower for k in ('my profile', 'my student info', 'my account details',
                                   'my student record', 'my personal information',
                                   'my personal details', 'my enrollment')):
        return _profile_base

    if any(k in q_lower for k in ('my account', 'my library account', 'my library status',
                                   'my library record', 'my library history',
                                   'my personal data')):
        return _profile_base

    # ── academic patterns ──────────────────────────────────────────────────
    if any(k in q_lower for k in ('my gpa', 'my attendance', 'my academic',
                                   'my semester', 'my course', 'my grades',
                                   'my current status', 'my current semester',
                                   'my current year')):
        return (
            f"SELECT gpa, attendance, role, created_date "
            f"FROM Students WHERE id = {sid}"
        )

    # ── generic "do i have …" / "what are my …" patterns ──────────────────
    if 'do i have' in q_lower or 'what are my' in q_lower or 'am i' in q_lower:
        if 'fine' in q_lower:
            return _fines_base + " AND f.status = 'Unpaid' ORDER BY f.issue_date DESC"
        if 'book' in q_lower:
            return _books_base + " AND i.return_date IS NULL ORDER BY i.due_date ASC"
        if 'reservat' in q_lower:
            return (
                f"SELECT r.*, b.title, b.author FROM Reservations r "
                f"JOIN Books b ON r.book_id = b.id "
                f"WHERE r.student_id = {sid} ORDER BY r.reservation_date DESC"
            )

    if 'how much do i owe' in q_lower:
        return (
            f"SELECT s.name, SUM(f.fine_amount) as total_balance "
            f"FROM Students s LEFT JOIN Fines f ON s.id = f.student_id "
            f"WHERE s.id = {sid} AND f.status = 'Unpaid' GROUP BY s.id, s.name"
        )

    if 'when are my' in q_lower and 'due' in q_lower:
        return _books_base + " AND i.return_date IS NULL ORDER BY i.due_date ASC"

    return sql_query


def _fallback_columns(sql_query: str) -> list:
    """Return a sensible fallback column list when a query returns no rows."""
    sq = sql_query.lower()
    if 'books' in sq:
        return ['id', 'title', 'author', 'category', 'total_copies', 'available_copies']
    if 'students' in sq:
        return ['id', 'roll_number', 'name', 'branch', 'year', 'email', 'gpa']
    if 'faculty' in sq:
        return ['id', 'name', 'department', 'designation', 'email']
    if 'fines' in sq:
        return ['id', 'student_id', 'fine_amount', 'fine_type', 'status', 'issue_date']
    if 'issued' in sq:
        return ['id', 'student_id', 'book_id', 'issue_date', 'due_date', 'return_date']
    return ['id', 'name']


# Authentication
@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    if request.method == 'GET':
        return render_template('login.html')
    
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    
    if not username or not password:
        flash('Please enter username and password', 'error')
        return render_template('login.html')
    
    # Dynamic student authentication for all 100 students
    if username == 'admin' and password == 'pass':
        session['user_id'] = 'admin'
        session['role'] = 'Administrator'
        session['student_id'] = None
    elif username == 'librarian' and password == 'pass':
        session['user_id'] = 'librarian'
        session['role'] = 'Librarian'
        session['student_id'] = None
    elif username == 'faculty_email' and password == 'pass':
        session['user_id'] = 'faculty_email'
        session['role'] = 'Faculty'
        session['student_id'] = None
    else:
        # Check if username is a valid student roll number
        try:
            conn = get_db_connection(MAIN_DB)
            student_query = "SELECT id, roll_number FROM Students WHERE roll_number = ?"
            student = conn.execute(student_query, (username,)).fetchone()
            conn.close()
            
            if student and password == 'pass':
                session['user_id'] = username
                session['role'] = 'Student'
                session['student_id'] = student['id']
            else:
                flash('Invalid username or password', 'error')
                return render_template('login.html')
        except Exception as e:
            flash('Invalid username or password', 'error')
            return render_template('login.html')
    
    flash(f'Welcome, {session["role"]}!', 'success')
    # All roles land on the main query interface; role-specific dashboards are
    # accessible as separate sections from within the query interface.
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    """Logout user"""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/')
def index():
    """Main dashboard – query interface with embedded role-specific widgets."""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    user_role = session.get('role', 'Student')
    student_id = session.get('student_id')

    user_info = {
        'username': user_id,
        'role': user_role,
        'permissions': []
    }

    # ── Fetch role-specific dashboard data to embed as widgets ───────────────
    dashboard_data = {}
    try:
        conn = get_db_connection(MAIN_DB)

        if user_role == 'Student' and student_id:
            student_info = conn.execute(
                "SELECT * FROM Students WHERE id = ?", (student_id,)
            ).fetchone()
            current_books = conn.execute(
                """SELECT i.*, b.title, b.author FROM Issued i
                   JOIN Books b ON i.book_id = b.id
                   WHERE i.student_id = ? AND i.return_date IS NULL
                   ORDER BY i.due_date ASC LIMIT 5""",
                (student_id,)
            ).fetchall()
            overdue_books = conn.execute(
                """SELECT i.*, b.title, b.author FROM Issued i
                   JOIN Books b ON i.book_id = b.id
                   WHERE i.student_id = ? AND i.return_date IS NULL
                   AND i.due_date < date('now')""",
                (student_id,)
            ).fetchall()
            unpaid_fines = conn.execute(
                "SELECT * FROM Fines WHERE student_id = ? AND status = 'Unpaid'",
                (student_id,)
            ).fetchall()
            dashboard_data = {
                'student_info': dict(student_info) if student_info else {},
                'current_books': [dict(r) for r in current_books],
                'overdue_count': len(overdue_books),
                'unpaid_fines': len(unpaid_fines),
            }

        elif user_role in ('Librarian', 'Faculty', 'Administrator'):
            total_books = conn.execute("SELECT COUNT(*) as cnt FROM Books").fetchone()['cnt']
            total_students = conn.execute("SELECT COUNT(*) as cnt FROM Students").fetchone()['cnt']
            active_issues = conn.execute(
                "SELECT COUNT(*) as cnt FROM Issued WHERE return_date IS NULL"
            ).fetchone()['cnt']
            unpaid_fines_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM Fines WHERE status = 'Unpaid'"
            ).fetchone()['cnt']
            dashboard_data = {
                'total_books': total_books,
                'total_students': total_students,
                'active_issues': active_issues,
                'unpaid_fines': unpaid_fines_count,
            }

        conn.close()
    except Exception as e:
        print(f"[index] Dashboard data fetch error: {e}")

    return render_template('index.html',
                           user=user_info.get('username', user_id),
                           role=user_role,
                           user_info=user_info,
                           dashboard_data=dashboard_data)

@app.route('/modern')
def modern_ui():
    """Modern interface"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    return render_template('modern.html')

@app.route('/minimal')
def minimal_ui():
    """Minimal interface"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    return render_template('modern-minimal.html')

@app.route('/student-dashboard')
def student_dashboard():
    """Individual student dashboard"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_role = session.get('role', 'Student')
    student_id = session.get('student_id')
    
    print(f"[DEBUG] Student Dashboard - User: {session.get('user_id')}, Role: {user_role}, Student ID: {student_id}")
    print(f"[DEBUG] Session data: {dict(session)}")
    
    # Get student-specific data
    try:
        conn = get_db_connection(MAIN_DB)
        print(f"[DEBUG] Database connection established")
        
        # Get student info
        student_info = conn.execute("SELECT * FROM Students WHERE id = ?", (student_id,)).fetchone()
        print(f"[DEBUG] Student Info query: SELECT * FROM Students WHERE id = {student_id}")
        print(f"[DEBUG] Student Info result: {student_info}")
        print(f"[DEBUG] Student ID type: {type(student_id)}, value: {student_id}")
        
        # Get borrowing history
        borrowing_history = conn.execute("""
            SELECT i.*, b.title, b.author 
            FROM Issued i 
            JOIN Books b ON i.book_id = b.id 
            WHERE i.student_id = ? 
            ORDER BY i.issue_date DESC
        """, (student_id,)).fetchall()
        print(f"[DEBUG] Borrowing History: {len(borrowing_history)} records")
        
        # Get current borrowed books
        current_books = conn.execute("""
            SELECT i.*, b.title, b.author, i.due_date
            FROM Issued i 
            JOIN Books b ON i.book_id = b.id 
            WHERE i.student_id = ? AND i.return_date IS NULL 
            ORDER BY i.due_date ASC
        """, (student_id,)).fetchall()
        print(f"[DEBUG] Current Books: {len(current_books)} records")
        
        # Get fines
        fines = conn.execute("""
            SELECT f.* 
            FROM Fines f 
            WHERE f.student_id = ? 
            ORDER BY f.issue_date DESC
        """, (student_id,)).fetchall()
        print(f"[DEBUG] Fines: {len(fines)} records")
        
        # Get reservations (book requests)
        reservations = conn.execute("""
            SELECT r.*, b.title, b.author
            FROM Reservations r 
            JOIN Books b ON r.book_id = b.id 
            WHERE r.student_id = ? 
            ORDER BY r.reservation_date DESC
        """, (student_id,)).fetchall()
        print(f"[DEBUG] Reservations: {len(reservations)} records")
        
        # Calculate statistics
        total_borrowed = len(borrowing_history)
        current_borrowed = len(current_books)
        total_fines = len(fines)
        unpaid_fines = len([f for f in fines if f['status'] == 'Unpaid'])
        pending_requests = len(reservations)
        
        stats = {
            'total_borrowed': total_borrowed,
            'current_borrowed': current_borrowed,
            'total_fines': total_fines,
            'unpaid_fines': unpaid_fines,
            'pending_requests': pending_requests
        }
        
        print(f"[DEBUG] Stats: {stats}")
        
    except Exception as e:
        print(f"[DEBUG] Error fetching student data: {e}")
        import traceback
        traceback.print_exc()
        student_info = None
        borrowing_history = []
        current_books = []
        fines = []
        reservations = []
        stats = {}
    finally:
        if 'conn' in locals():
            conn.close()
            print(f"[DEBUG] Database connection closed")
    
    print(f"[DEBUG] Rendering template with data: student={student_info is not None}, history={len(borrowing_history)}, fines={len(fines)}")
    
    return render_template('student-dashboard.html', 
                         student=student_info,
                         borrowing_history=borrowing_history,
                         current_books=current_books,
                         fines=fines,
                         reservations=reservations,
                         stats=stats,
                         role=user_role)

@app.route('/student/dashboard')
def student_dashboard_alt():
    """Alternative route for student dashboard"""
    return redirect(url_for('student_dashboard'))

@app.route('/dashboard')
def dashboard_redirect():
    """Generic dashboard redirect"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_role = session.get('role', 'Student')
    if user_role == 'Student':
        return redirect(url_for('student_dashboard_individual'))
    else:
        return redirect(url_for('index'))

@app.route('/student-dashboard-individual')
def student_dashboard_individual():
    """Individual student dashboard with real data"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_role = session.get('role', 'Student')
    if user_role != 'Student':
        return redirect(url_for('index'))
    
    # Get student roll number from session
    roll_number = session.get('user_id')
    if not roll_number:
        return redirect(url_for('login'))
    
    # Serve individual dashboard template
    template_name = f'student_dashboard_{roll_number.lower()}.html'
    try:
        return render_template(template_name)
    except jinja2.TemplateNotFound:
        print(f"[student_dashboard_individual] Template not found: {template_name}")
        return redirect(url_for('student_dashboard_route'))

# ── Role-specific dashboards ─────────────────────────────────────────────────

@app.route('/student_dashboard')
def student_dashboard_route():
    """Student dashboard (underscore URL as required by RBAC spec)"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'Student':
        return "Access Denied", 403

    user_role = session.get('role', 'Student')

    user_id = session['user_id']
    student_id = session.get('student_id')

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
            (student_id,)
        ).fetchall()
        overdue_books = conn.execute(
            """SELECT i.*, b.title, b.author FROM Issued i
               JOIN Books b ON i.book_id = b.id
               WHERE i.student_id = ? AND i.return_date IS NULL
               AND i.due_date < date('now')
               ORDER BY i.due_date ASC""",
            (student_id,)
        ).fetchall()
        borrowing_history = conn.execute(
            """SELECT i.*, b.title, b.author FROM Issued i
               JOIN Books b ON i.book_id = b.id
               WHERE i.student_id = ? ORDER BY i.issue_date DESC""",
            (student_id,)
        ).fetchall()
        unpaid_fines = conn.execute(
            "SELECT * FROM Fines WHERE student_id = ? AND status = 'Unpaid' ORDER BY issue_date DESC",
            (student_id,)
        ).fetchall()
        all_fines = conn.execute(
            "SELECT * FROM Fines WHERE student_id = ? ORDER BY issue_date DESC",
            (student_id,)
        ).fetchall()
        reservations = conn.execute(
            """SELECT r.*, b.title, b.author FROM Reservations r
               JOIN Books b ON r.book_id = b.id
               WHERE r.student_id = ? ORDER BY r.reservation_date DESC""",
            (student_id,)
        ).fetchall()
        conn.close()
        stats = {
            'total_borrowed': len(borrowing_history),
            'current_borrowed': len(current_books),
            'total_fines': len(all_fines),
            'unpaid_fines': len(unpaid_fines),
            'pending_requests': len(reservations),
        }
    except Exception as e:
        print(f"[student_dashboard] DB error: {e}")
        student_info = None
        current_books = overdue_books = borrowing_history = []
        unpaid_fines = all_fines = reservations = []
        stats = {}

    return render_template(
        'student_dashboard.html',
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


@app.route('/librarian_dashboard')
def librarian_dashboard_route():
    """Librarian / Faculty dashboard"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') != 'Librarian':
        return "Access Denied", 403

    user_role = session.get('role', 'Librarian')

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
        role=user_role,
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
      1. Clarification detection (returns options if vague & no choice given)
      2. Apply clarification choice (if provided)
      3. Vocabulary preprocessing (append schema hints)
      4. SQL generation via Ollama
      5. Student-specific SQL rewriting / row-level filtering
      6. SQL safety gate (SELECT-only, no DDL/write keywords)
      7. RBAC table-access validation
      8. Execute & return results
    """
    print("🔍 Query received - Processing request")

    if 'user_id' not in session:
        print("❌ User not logged in")
        return jsonify({'error': 'Not logged in'}), 401

    try:
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

        # ── Step 1 & 2: Clarification chatbot ────────────────────────────
        if clarification_choice:
            # User selected an option – expand into specific NL query
            user_query = apply_clarification_choice(user_query, clarification_choice)
            print(f"🗣️ Clarification applied: {user_query}")
        else:
            clarif = get_clarification(user_query)
            if clarif is not None:
                print(f"❓ Ambiguous query – returning clarification options")
                return jsonify({
                    'needs_clarification': True,
                    'clarification': clarif
                })

        # ── Step 3: Vocabulary preprocessing ─────────────────────────────
        augmented_query = preprocess_query(user_query, MAIN_DB)
        if augmented_query != user_query:
            print(f"📚 Vocabulary hints added: {augmented_query}")

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

        # ── Step 4: Student-specific SQL rewriting ────────────────────────
        print("Role:", session.get("role"))
        print("Student Filter Applied:", session.get("student_id"))
        if user_role == 'Student' and student_id:
            sql_query = _apply_student_filters(user_query, sql_query, student_id)

        # ── Step 5: SQL safety gate ───────────────────────────────────────
        safe, reason = _is_safe_sql(sql_query)
        if not safe:
            print(f"🚫 SQL blocked by safety gate: {reason}")
            return jsonify({'error': f'Query not permitted: {reason}'}), 400

        # ── Step 6: RBAC table-access validation ──────────────────────────
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

        # Extract columns dynamically
        if rows:
            columns = list(rows[0].keys())
        else:
            columns = _fallback_columns(sql_query)

        print(f"📊 Returning {len(rows)} rows with columns: {columns}")

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


@app.route('/librarian-dashboard')
def librarian_dashboard():
    """Librarian / Faculty dashboard."""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id   = session['user_id']
    user_role = session.get('role', 'Student')

    # Gather library stats
    try:
        conn = get_db_connection(MAIN_DB)
        total_books     = conn.execute("SELECT COUNT(*) FROM Books").fetchone()[0]
        available_books = conn.execute(
            "SELECT COUNT(*) FROM Books WHERE available_copies > 0").fetchone()[0]
        issued_books    = conn.execute(
            "SELECT COUNT(*) FROM Issued WHERE return_date IS NULL").fetchone()[0]
        overdue_books   = conn.execute(
            "SELECT COUNT(*) FROM Issued WHERE return_date IS NULL "
            "AND date(due_date) < date('now')").fetchone()[0]
        conn.close()
    except Exception as e:
        print(f"⚠️ Librarian dashboard stats error: {e}")
        total_books = available_books = issued_books = overdue_books = 0

    return render_template(
        'dashboard_rbac.html',
        user_info={'user_id': user_id, 'role': user_role},
        role_badge_class='role-librarian',
        menu_items=[
            {'icon': '📚', 'label': 'Dashboard',     'url': '/librarian-dashboard'},
            {'icon': '🔍', 'label': 'Query Console', 'url': '/'},
            {'icon': '📈', 'label': 'Analytics',     'url': '/analytics'},
            {'icon': '💡', 'label': 'Recommendations','url': '/recommendations'},
            {'icon': '⏻', 'label': 'Logout',        'url': '/logout'},
        ],
        permissions_summary={'permission_count': 30, 'table_count': 8, 'role_level': 2},
        search_config={
            'enabled': True,
            'placeholder': 'Search books, students, fines...',
            'suggestions': [
                'Show overdue books', 'List all students',
                'Unpaid fines', 'Available books',
            ],
        },
        dashboard_widgets=[
            {'type': 'library_stats', 'title': 'Library Statistics', 'icon': '📚'},
        ],
        data={
            'library_stats': {
                'total_books':     total_books,
                'available_books': available_books,
                'issued_books':    issued_books,
                'overdue_books':   overdue_books,
            }
        },
        theme_css='',
    )


# Error handlers
@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

@app.errorhandler(403)
def forbidden(error):
    return render_template('403.html'), 403

# Context processor
@app.context_processor
def inject_user():
    """Inject user information"""
    if 'user_id' in session:
        return {
            'current_user': {
                'username': session['user_id'],
                'role': session.get('role', 'Student')
            },
            'user_role': session.get('role', 'Student')
        }
    return {}

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
