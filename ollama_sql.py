import requests
import re
import socket

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "sqlcoder:latest"

# Schema context injected into LLM prompts for accurate SQL generation
SCHEMA_CONTEXT = (
    "Books(id,title,author,category,publisher_id,total_copies,available_copies)\n"
    "Students(id,name,roll_number,branch,year,email)\n"
    "Issued(id,student_id,book_id,issue_date,due_date,return_date,status)\n"
    "Fines(id,student_id,fine_amount,fine_type,status,issue_date)\n"
    "Faculty(id,name,email,department,designation)\n"
    "Reservations(id,student_id,book_id,reservation_date,status)\n"
    "Departments(id,name)"
)

# Default fallback SQL returned when all generation layers fail
FALLBACK_SQL = "SELECT * FROM Books LIMIT 10"

# Blocked SQL keywords – non-SELECT operations must never appear in generated SQL
_BLOCKED_SQL_RE = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|CREATE|ALTER|TRUNCATE|REPLACE|MERGE"
    r"|GRANT|REVOKE|EXECUTE|EXEC|CALL|PRAGMA)\b",
    re.IGNORECASE,
)

# ── Layer 1: REGEX pattern-matching rules ─────────────────────────────────────
# Evaluated in order; first match wins.  Handles simple / generic queries that
# previously fell through to the LLM and produced bad SQL.
_REGEX_RULES = [
    # Books – simple/generic
    (re.compile(r"^(show|list|display)\s+(all\s+)?books?\s*$", re.IGNORECASE),
     "SELECT id,title,author FROM Books"),
    (re.compile(r"^(show|list|display)\s+all\s+books\b", re.IGNORECASE),
     "SELECT id,title,author FROM Books"),
    # Students – simple/generic
    (re.compile(r"^(show|list|display)\s+(all\s+)?students?\s*$", re.IGNORECASE),
     "SELECT id,name,roll_number FROM Students"),
    (re.compile(r"^(show|list|display)\s+all\s+students\b", re.IGNORECASE),
     "SELECT id,name,roll_number FROM Students"),
    # Fines – simple/generic
    (re.compile(r"^(show|list|display)\s+(all\s+)?fines?\s*$", re.IGNORECASE),
     "SELECT * FROM Fines"),
    # Issued books
    (re.compile(r"^(show|list|display)\s+(all\s+)?issued\s+books?\s*$", re.IGNORECASE),
     "SELECT * FROM Issued"),
    (re.compile(r"\bissued\s+books?\b", re.IGNORECASE),
     "SELECT * FROM Issued"),
    # Overdue books
    (re.compile(r"\boverdue\s+books?\b", re.IGNORECASE),
     "SELECT * FROM Issued WHERE return_date IS NULL AND due_date < date('now')"),
    # Faculty – simple/generic
    (re.compile(r"^(show|list|display)\s+(all\s+)?faculty\s*$", re.IGNORECASE),
     "SELECT id,name,email FROM Faculty"),
    # Reservations – simple/generic
    (re.compile(r"^(show|list|display)\s+(all\s+)?reservations?\s*$", re.IGNORECASE),
     "SELECT * FROM Reservations"),
    # Library / database statistics
    (re.compile(r"(library|database)\s+(statistics?|stats?|summary|info)", re.IGNORECASE),
     ("SELECT 'Total Students' as metric, COUNT(*) as count FROM Students "
      "UNION ALL SELECT 'Total Books', COUNT(*) FROM Books "
      "UNION ALL SELECT 'Total Fines', COUNT(*) FROM Fines "
      "UNION ALL SELECT 'Total Issued', COUNT(*) FROM Issued")),
]

# ── Layer 2: Rule-based dictionary (50+ rules) ────────────────────────────────
# Each entry is a (substring, sql) tuple.  The substring is matched
# (case-insensitively) against the cleaned query; first match wins.
_RULE_DICT = [
    # ── Books ──────────────────────────────────────────────────────────────
    ("show all books with title and author",
     "SELECT id,title,author FROM Books"),
    ("list all books with title and author",
     "SELECT id,title,author FROM Books"),
    ("books with title and author",
     "SELECT id,title,author FROM Books"),
    ("show books that are available for borrowing",
     "SELECT id,title,author FROM Books WHERE id NOT IN "
     "(SELECT book_id FROM Issued WHERE return_date IS NULL)"),
    ("show available books",
     "SELECT id,title,author FROM Books WHERE id NOT IN "
     "(SELECT book_id FROM Issued WHERE return_date IS NULL)"),
    ("available books",
     "SELECT id,title,author FROM Books WHERE id NOT IN "
     "(SELECT book_id FROM Issued WHERE return_date IS NULL)"),
    ("show books grouped by category",
     "SELECT category, COUNT(*) as book_count FROM Books GROUP BY category ORDER BY book_count DESC"),
    ("books grouped by category",
     "SELECT category, COUNT(*) as book_count FROM Books GROUP BY category ORDER BY book_count DESC"),
    ("books ordered by number of times",
     "SELECT b.id,b.title,b.author,COUNT(i.id) as issue_count FROM Books b "
     "LEFT JOIN Issued i ON b.id=i.book_id GROUP BY b.id,b.title,b.author "
     "ORDER BY issue_count DESC"),
    ("most borrowed books",
     "SELECT b.id,b.title,b.author,COUNT(i.id) as issue_count FROM Books b "
     "LEFT JOIN Issued i ON b.id=i.book_id GROUP BY b.id,b.title,b.author "
     "ORDER BY issue_count DESC"),
    # ── Students ────────────────────────────────────────────────────────────
    ("show all students with name and roll number",
     "SELECT id,name,roll_number FROM Students"),
    ("list all students with name and roll number",
     "SELECT id,name,roll_number FROM Students"),
    ("students with name and roll number",
     "SELECT id,name,roll_number FROM Students"),
    ("show students who have unpaid fines",
     "SELECT s.id,s.name,s.roll_number,SUM(f.fine_amount) as total_fines "
     "FROM Students s JOIN Fines f ON s.id=f.student_id WHERE f.status='Unpaid' "
     "GROUP BY s.id,s.name,s.roll_number ORDER BY total_fines DESC"),
    ("students who have unpaid fines",
     "SELECT s.id,s.name,s.roll_number,SUM(f.fine_amount) as total_fines "
     "FROM Students s JOIN Fines f ON s.id=f.student_id WHERE f.status='Unpaid' "
     "GROUP BY s.id,s.name,s.roll_number ORDER BY total_fines DESC"),
    ("students with unpaid fines",
     "SELECT s.id,s.name,s.roll_number,SUM(f.fine_amount) as total_fines "
     "FROM Students s JOIN Fines f ON s.id=f.student_id WHERE f.status='Unpaid' "
     "GROUP BY s.id,s.name,s.roll_number ORDER BY total_fines DESC"),
    ("show students grouped by branch",
     "SELECT branch, COUNT(*) as student_count FROM Students GROUP BY branch ORDER BY student_count DESC"),
    ("students grouped by branch",
     "SELECT branch, COUNT(*) as student_count FROM Students GROUP BY branch ORDER BY student_count DESC"),
    ("show students grouped by department",
     "SELECT branch, COUNT(*) as student_count FROM Students GROUP BY branch ORDER BY student_count DESC"),
    ("show students who currently have books issued",
     "SELECT DISTINCT s.id,s.name,s.roll_number FROM Students s "
     "JOIN Issued i ON s.id=i.student_id WHERE i.return_date IS NULL"),
    ("students who currently have books issued",
     "SELECT DISTINCT s.id,s.name,s.roll_number FROM Students s "
     "JOIN Issued i ON s.id=i.student_id WHERE i.return_date IS NULL"),
    ("students currently borrowing",
     "SELECT DISTINCT s.id,s.name,s.roll_number FROM Students s "
     "JOIN Issued i ON s.id=i.student_id WHERE i.return_date IS NULL"),
    # ── Fines ───────────────────────────────────────────────────────────────
    ("show all fines with amount and status",
     "SELECT f.id,s.name as student_name,f.fine_amount,f.status "
     "FROM Fines f JOIN Students s ON f.student_id=s.id ORDER BY f.fine_amount DESC"),
    ("fines with amount and status",
     "SELECT f.id,s.name as student_name,f.fine_amount,f.status "
     "FROM Fines f JOIN Students s ON f.student_id=s.id ORDER BY f.fine_amount DESC"),
    ("show fines where status is unpaid",
     "SELECT f.id,s.name as student_name,f.fine_amount,f.status "
     "FROM Fines f JOIN Students s ON f.student_id=s.id WHERE f.status='Unpaid' "
     "ORDER BY f.fine_amount DESC"),
    ("fines where status is unpaid",
     "SELECT f.id,s.name as student_name,f.fine_amount,f.status "
     "FROM Fines f JOIN Students s ON f.student_id=s.id WHERE f.status='Unpaid' "
     "ORDER BY f.fine_amount DESC"),
    ("show total fine amount per student",
     "SELECT s.id,s.name,s.roll_number,SUM(f.fine_amount) as total_fines "
     "FROM Students s JOIN Fines f ON s.id=f.student_id "
     "GROUP BY s.id,s.name,s.roll_number ORDER BY total_fines DESC"),
    ("total fine amount per student",
     "SELECT s.id,s.name,s.roll_number,SUM(f.fine_amount) as total_fines "
     "FROM Students s JOIN Fines f ON s.id=f.student_id "
     "GROUP BY s.id,s.name,s.roll_number ORDER BY total_fines DESC"),
    ("fines per student",
     "SELECT s.id,s.name,s.roll_number,SUM(f.fine_amount) as total_fines "
     "FROM Students s JOIN Fines f ON s.id=f.student_id "
     "GROUP BY s.id,s.name,s.roll_number ORDER BY total_fines DESC"),
    ("show fines ordered by issue date",
     "SELECT f.id,s.name as student_name,f.fine_amount,f.status,f.issue_date "
     "FROM Fines f JOIN Students s ON f.student_id=s.id ORDER BY f.issue_date DESC"),
    ("recent fines",
     "SELECT f.id,s.name as student_name,f.fine_amount,f.status,f.issue_date "
     "FROM Fines f JOIN Students s ON f.student_id=s.id ORDER BY f.issue_date DESC"),
    # ── Issued / Lending ─────────────────────────────────────────────────────
    ("show books currently issued that have not been returned",
     "SELECT i.id,b.title,s.name as student_name,i.issue_date,i.due_date "
     "FROM Issued i JOIN Books b ON i.book_id=b.id "
     "JOIN Students s ON i.student_id=s.id WHERE i.return_date IS NULL"),
    ("currently issued not returned",
     "SELECT i.id,b.title,s.name as student_name,i.issue_date,i.due_date "
     "FROM Issued i JOIN Books b ON i.book_id=b.id "
     "JOIN Students s ON i.student_id=s.id WHERE i.return_date IS NULL"),
    ("show overdue books that are past their due date",
     "SELECT i.id,b.title,s.name as student_name,i.issue_date,i.due_date "
     "FROM Issued i JOIN Books b ON i.book_id=b.id "
     "JOIN Students s ON i.student_id=s.id "
     "WHERE i.return_date IS NULL AND i.due_date < date('now')"),
    ("show all book lending history",
     "SELECT i.id,b.title,s.name as student_name,i.issue_date,i.due_date,i.return_date "
     "FROM Issued i JOIN Books b ON i.book_id=b.id "
     "JOIN Students s ON i.student_id=s.id ORDER BY i.issue_date DESC"),
    ("all book lending history",
     "SELECT i.id,b.title,s.name as student_name,i.issue_date,i.due_date,i.return_date "
     "FROM Issued i JOIN Books b ON i.book_id=b.id "
     "JOIN Students s ON i.student_id=s.id ORDER BY i.issue_date DESC"),
    ("book lending history",
     "SELECT i.id,b.title,s.name as student_name,i.issue_date,i.due_date,i.return_date "
     "FROM Issued i JOIN Books b ON i.book_id=b.id "
     "JOIN Students s ON i.student_id=s.id ORDER BY i.issue_date DESC"),
    ("not returned",
     "SELECT i.id,b.title,s.name as student_name,i.issue_date,i.due_date "
     "FROM Issued i JOIN Books b ON i.book_id=b.id "
     "JOIN Students s ON i.student_id=s.id WHERE i.return_date IS NULL"),
    # ── Faculty ──────────────────────────────────────────────────────────────
    ("show all faculty with name and department",
     "SELECT id,name,email,department FROM Faculty ORDER BY department,name"),
    ("list all faculty with name and department",
     "SELECT id,name,email,department FROM Faculty ORDER BY department,name"),
    ("faculty with name and department",
     "SELECT id,name,email,department FROM Faculty ORDER BY department,name"),
    ("show faculty members grouped by department",
     "SELECT department, COUNT(id) as faculty_count FROM Faculty GROUP BY department ORDER BY faculty_count DESC"),
    ("faculty members grouped by department",
     "SELECT department, COUNT(id) as faculty_count FROM Faculty GROUP BY department ORDER BY faculty_count DESC"),
    ("faculty grouped by department",
     "SELECT department, COUNT(id) as faculty_count FROM Faculty GROUP BY department ORDER BY faculty_count DESC"),
    # ── Reservations ─────────────────────────────────────────────────────────
    ("show pending reservations",
     "SELECT r.id,b.title,s.name as student_name,r.reservation_date,r.status "
     "FROM Reservations r JOIN Books b ON r.book_id=b.id "
     "JOIN Students s ON r.student_id=s.id WHERE r.status='Pending' "
     "ORDER BY r.reservation_date"),
    ("pending reservations",
     "SELECT r.id,b.title,s.name as student_name,r.reservation_date,r.status "
     "FROM Reservations r JOIN Books b ON r.book_id=b.id "
     "JOIN Students s ON r.student_id=s.id WHERE r.status='Pending' "
     "ORDER BY r.reservation_date"),
    ("show all reservations",
     "SELECT r.id,b.title,s.name as student_name,r.reservation_date,r.status "
     "FROM Reservations r JOIN Books b ON r.book_id=b.id "
     "JOIN Students s ON r.student_id=s.id ORDER BY r.reservation_date"),
    # ── Statistics / counts ──────────────────────────────────────────────────
    ("total books",
     "SELECT COUNT(*) as total_books FROM Books"),
    ("total students",
     "SELECT COUNT(*) as total_students FROM Students"),
    ("total fines",
     "SELECT COUNT(*) as total_fines, SUM(fine_amount) as total_amount FROM Fines"),
    ("count books",
     "SELECT COUNT(*) as total_books FROM Books"),
    ("count students",
     "SELECT COUNT(*) as total_students FROM Students"),
    ("how many books",
     "SELECT COUNT(*) as total_books FROM Books"),
    ("how many students",
     "SELECT COUNT(*) as total_students FROM Students"),
    ("how many fines",
     "SELECT COUNT(*) as total_fines FROM Fines"),
    # ── Departments ──────────────────────────────────────────────────────────
    ("show all departments",
     "SELECT id,name FROM Departments"),
    ("list all departments",
     "SELECT id,name FROM Departments"),
    ("show departments",
     "SELECT id,name FROM Departments"),
    ("list departments",
     "SELECT id,name FROM Departments"),
]


def _strip_vocab_hints(query: str) -> str:
    """Remove [TABLES: ...] and [HINT: ...] annotations added by preprocess_query."""
    return re.sub(r"\s*\[(?:TABLES|HINT):[^\]]*\]", "", query).strip()


def _match_regex_rules(query: str) -> str:
    """Layer 1 – REGEX pattern matching.  Returns SQL or empty string."""
    for pattern, sql in _REGEX_RULES:
        if pattern.search(query):
            print(f"[REGEX MATCH] {pattern.pattern[:60]} → {sql[:60]}...")
            return sql
    return ""


def _match_rule_dict(query: str) -> str:
    """Layer 2 – Rule-based dictionary lookup.  Returns SQL or empty string."""
    q_lower = query.lower()
    for phrase, sql in _RULE_DICT:
        if phrase in q_lower:
            print(f"[RULE MATCH] '{phrase}' → {sql[:60]}...")
            return sql
    return ""


def _is_safe_generated_sql(sql: str) -> bool:
    """Return True only if *sql* is a SELECT that contains no blocked keywords."""
    stripped = sql.strip()
    if not stripped.upper().startswith("SELECT"):
        return False
    if _BLOCKED_SQL_RE.search(stripped):
        return False
    return True


def generate_sql(user_query):
    """
    Hybrid approach: LLM for simple queries, enhanced keyword for complex queries
    """
    # Strip vocabulary hint annotations before rule matching so that
    # "show books  [TABLES: Books]" is treated the same as "show books".
    clean_query = _strip_vocab_hints(user_query)

    # ── Layer 1: REGEX patterns ────────────────────────────────────────────
    sql = _match_regex_rules(clean_query)
    if sql:
        return sql

    # ── Layer 2: Rule-based dictionary ────────────────────────────────────
    sql = _match_rule_dict(clean_query)
    if sql:
        return sql

    # ── Layer 3: Keyword-based generation (generate_complex_sql) ──────────
    sql = generate_complex_sql(clean_query)
    if sql:
        return sql

    # ── Layer 4: Ollama LLM ────────────────────────────────────────────────
    try:
        # Quick connectivity check to avoid long timeouts
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('localhost', 11434))
            sock.close()
            if result != 0:
                print(f"[OLLAMA DOWN] Port 11434 not reachable, using fallback")
                return generate_complex_sql(user_query)
        except:
            print(f"[OLLAMA CHECK FAILED] Using fallback")
            return generate_complex_sql(user_query)
        
        # Check if it's a complex query that the LLM struggles with
        if any(word in query_lower for word in [
            "count", "sum", "average", "more than", "less than",
            "top", "highest", "lowest", "statistics"
        ]):
            # For complex queries, use enhanced keyword approach
            print(f"[COMPLEX QUERY DETECTED] Using enhanced keyword approach")
            return generate_complex_sql(user_query)
        
        # Database schema for the LLM prompt
        schema = (
            "Books(id, title, author, publisher, category)\n"
            "Students(id, name, roll_number, branch)\n"
            "Issued(id, book_id, student_id, issue_date, due_date, return_date)\n"
            "Fines(id, student_id, fine_amount, status)"
        )

        prompt = (
            f"Convert the natural language query into SQLite SQL.\n\n"
            f"Database schema:\n{schema}\n\n"
            f"Rules:\n"
            f"- Only generate SELECT queries\n"
            f"- Do not generate INSERT, UPDATE, DELETE, DROP\n"
            f"- Return only SQL\n"
            f"- No explanations\n\n"
            f"User Query: {user_query}\n\n"
            f"SQL:"
        )
        
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "top_p": 0.9,
                    "repeat_penalty": 1.0,
                    "num_predict": 150,
                    "top_k": 10,
                    "num_ctx": 2048,
                },
            },
            timeout=3,
        )

        if response.status_code == 200:
            raw_sql = response.json()["response"].strip()
            print(f"[LLM SQL GENERATED] {raw_sql}")
            
            if raw_sql and len(raw_sql) > 10 and "SELECT" in raw_sql.upper():
                sql_match = re.search(r"SELECT\b.*?(?:;|$)", raw_sql, re.IGNORECASE | re.DOTALL)
                if sql_match:
                    clean_sql = sql_match.group(0).strip()
                    if clean_sql.endswith(";"):
                        clean_sql = clean_sql[:-1]
                    print(f"[SQL EXTRACTED] {clean_sql}")
                    return clean_sql
        
    except Exception as e:
        print(f"[OLLAMA ERROR] {e}")
    
    print(f"[LLM FAILED → USING RULE]")
    return generate_complex_sql(user_query)

def generate_complex_sql(user_query):
    """
    Enhanced keyword-based SQL generation for complex and nested queries
    """
    query_lower = user_query.lower()

    # ── COMMON / SIMPLE QUERIES ──────────────────────────────────────────────
    if any(k in query_lower for k in ["show books", "list books", "display books", "all books", "get books"]):
        return "SELECT * FROM Books"

    elif any(k in query_lower for k in ["show students", "list students", "display students", "all students", "get students"]):
        return "SELECT * FROM Students"

    elif any(k in query_lower for k in ["show issued", "list issued", "issued books", "all issued", "show issued books", "list issued books"]):
        return "SELECT i.*, b.title, s.name as student_name FROM Issued i JOIN Books b ON i.book_id = b.id JOIN Students s ON i.student_id = s.id"

    elif any(k in query_lower for k in ["show fines", "list fines", "display fines", "all fines", "students with fines"]):
        return "SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id ORDER BY f.fine_amount DESC"

    elif any(k in query_lower for k in ["overdue books", "show overdue", "list overdue"]):
        return "SELECT i.*, b.title, s.name as student_name FROM Issued i JOIN Books b ON i.book_id = b.id JOIN Students s ON i.student_id = s.id WHERE i.return_date IS NULL AND i.due_date < date('now')"

    elif any(k in query_lower for k in ["available books", "show available", "list available"]):
        return "SELECT * FROM Books WHERE id NOT IN (SELECT book_id FROM Issued WHERE return_date IS NULL)"

    elif any(k in query_lower for k in ["library statistics", "database statistics", "library stats", "db stats", "system statistics"]):
        return (
            "SELECT 'Total Books' as metric, COUNT(*) as value FROM Books "
            "UNION ALL SELECT 'Total Students', COUNT(*) FROM Students "
            "UNION ALL SELECT 'Total Issued', COUNT(*) FROM Issued "
            "UNION ALL SELECT 'Total Fines', COUNT(*) FROM Fines"
        )

    elif any(k in query_lower for k in ["my borrowed books", "my books", "books i borrowed"]):
        return "SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = [CURRENT_STUDENT_ID] ORDER BY i.issue_date DESC"

    elif any(k in query_lower for k in ["my fines", "my unpaid fines", "my fine"]):
        return "SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id WHERE f.student_id = [CURRENT_STUDENT_ID]"

    elif any(k in query_lower for k in ["my reservations", "my reserved books", "books i reserved"]):
        return "SELECT r.*, b.title, b.author FROM Reservations r JOIN Books b ON r.book_id = b.id WHERE r.student_id = [CURRENT_STUDENT_ID] ORDER BY r.reservation_date DESC"

    # ── ADMIN-SPECIFIC QUERIES ───────────────────────────────────────────────
    if "users in system" in query_lower or "all users" in query_lower:
        return "SELECT * FROM Students UNION SELECT * FROM Faculty"
    
    elif "departments and their student counts" in query_lower:
        return "SELECT d.name, COUNT(s.id) as student_count FROM Departments d LEFT JOIN Students s ON d.id = s.branch GROUP BY d.id, d.name ORDER BY student_count DESC"
    
    elif "total revenue from all fines" in query_lower or "fine collection" in query_lower:
        return "SELECT SUM(fine_amount) as total_revenue, strftime('%Y-%m', issue_date) as month FROM Fines GROUP BY strftime('%Y-%m', issue_date) ORDER BY month DESC"
    
    elif "most active librarians" in query_lower:
        return "SELECT u.username, COUNT(*) as actions FROM Users u JOIN QueryHistory q ON u.username = q.user_query GROUP BY u.id, u.username ORDER BY actions DESC"
    
    elif "books with highest fine rates" in query_lower:
        return "SELECT b.title, AVG(f.fine_amount) as avg_fine, COUNT(f.id) as fine_count FROM Books b LEFT JOIN Issued i ON b.id = i.book_id LEFT JOIN Fines f ON i.student_id = f.student_id GROUP BY b.id, b.title HAVING fine_count > 0 ORDER BY avg_fine DESC"
    
    elif "faculty and their departments" in query_lower:
        return "SELECT f.name, f.email, d.name as department FROM Faculty f JOIN Departments d ON f.department_id = d.id ORDER BY d.name, f.name"
    
    elif "system usage statistics" in query_lower or "database statistics" in query_lower:
        return "SELECT 'Total Students' as metric, COUNT(*) as count FROM Students UNION ALL SELECT 'Total Books', COUNT(*) FROM Books UNION ALL SELECT 'Total Fines', COUNT(*) FROM Fines UNION ALL SELECT 'Total Issued', COUNT(*) FROM Issued"
    
    elif "overdue books by department" in query_lower:
        return "SELECT d.name as department, COUNT(i.id) as overdue_count FROM Departments d JOIN Students s ON d.id = s.branch JOIN Issued i ON s.id = i.student_id WHERE i.return_date IS NULL AND i.due_date < date('now') GROUP BY d.id, d.name ORDER BY overdue_count DESC"
    
    elif "fine collection by month" in query_lower:
        return "SELECT strftime('%Y-%m', issue_date) as month, SUM(fine_amount) as total_fines, COUNT(*) as fine_count FROM Fines GROUP BY strftime('%Y-%m', issue_date) ORDER BY month DESC"
    
    elif "students with most violations" in query_lower:
        return "SELECT s.name, s.roll_number, COUNT(f.id) as violation_count FROM Students s JOIN Fines f ON s.id = f.student_id GROUP BY s.id, s.name, s.roll_number ORDER BY violation_count DESC LIMIT 10"
    
    # LIBRARIAN-SPECIFIC QUERIES
    elif "show all issued books" in query_lower or "all issued books" in query_lower:
        return "SELECT * FROM Issued"
    
    elif "display overdue books" in query_lower or "overdue books" in query_lower:
        return "SELECT i.*, b.title, s.name as student_name FROM Issued i JOIN Books b ON i.book_id = b.id JOIN Students s ON i.student_id = s.id WHERE i.return_date IS NULL AND i.due_date < date('now')"
    
    elif "show books due today" in query_lower or "books due today" in query_lower:
        return "SELECT i.*, b.title, s.name as student_name FROM Issued i JOIN Books b ON i.book_id = b.id JOIN Students s ON i.student_id = s.id WHERE i.due_date = date('now') AND i.return_date IS NULL"
    
    elif "list students with current books" in query_lower or "students with current books" in query_lower:
        return "SELECT DISTINCT s.*, i.issue_date, i.due_date FROM Students s JOIN Issued i ON s.id = i.student_id WHERE i.return_date IS NULL"
    
    elif "show books not issued" in query_lower or "books not issued" in query_lower or "books never issued" in query_lower:
        return "SELECT * FROM Books WHERE id NOT IN (SELECT DISTINCT book_id FROM Issued)"

    elif "show all books with title and author" in query_lower or "all books with title and author" in query_lower:
        return "SELECT title, author FROM Books ORDER BY title"

    elif "show books in library" in query_lower or "books in library" in query_lower or "show all books" in query_lower or "list all books" in query_lower or "display all books" in query_lower:
        return "SELECT id, title, author, category, available_copies FROM Books ORDER BY title"

    elif "display fine records" in query_lower or "show fine records" in query_lower:
        return "SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id ORDER BY f.issue_date DESC"
    
    elif "find books with reservation queue longer than 5" in query_lower or "queue longer than" in query_lower:
        return "SELECT b.title, COUNT(r.id) as queue_length FROM Books b JOIN Reservations r ON b.id = r.book_id WHERE r.status = 'Waiting' GROUP BY b.id, b.title HAVING COUNT(r.id) > 5 ORDER BY queue_length DESC"
    
    elif "list available books" in query_lower or "available books" in query_lower:
        return "SELECT b.* FROM Books b WHERE b.id NOT IN (SELECT book_id FROM Issued WHERE return_date IS NULL) AND b.id NOT IN (SELECT book_id FROM Reservations WHERE status = 'Active')"
    
    elif "show books by category" in query_lower or "books by category" in query_lower:
        return "SELECT category, COUNT(*) as book_count FROM Books GROUP BY category ORDER BY book_count DESC"
    
    elif "display student borrowing history" in query_lower or "student borrowing history" in query_lower:
        return "SELECT s.name as student_name, b.title, i.issue_date, i.return_date, i.due_date FROM Students s JOIN Issued i ON s.id = i.student_id JOIN Books b ON i.book_id = b.id ORDER BY i.issue_date DESC"
    
    elif "show books with multiple copies" in query_lower or "books with multiple copies" in query_lower:
        return "SELECT title, COUNT(*) as copy_count FROM Books GROUP BY title HAVING COUNT(*) > 1 ORDER BY copy_count DESC"
    
    elif "list active reservations" in query_lower or "active reservations" in query_lower:
        return "SELECT r.*, b.title, s.name as student_name FROM Reservations r JOIN Books b ON r.book_id = b.id JOIN Students s ON r.student_id = s.id WHERE r.status = 'Active' ORDER BY r.reservation_date"
    
    elif "show books in high demand" in query_lower or "books in high demand" in query_lower:
        return "SELECT b.title, COUNT(i.id) as issue_count, COUNT(r.id) as reservation_count FROM Books b LEFT JOIN Issued i ON b.id = i.book_id LEFT JOIN Reservations r ON b.id = r.book_id GROUP BY b.id, b.title HAVING (issue_count > 5 OR reservation_count > 2) ORDER BY issue_count DESC"
    
    elif "display return statistics" in query_lower or "return statistics" in query_lower:
        return "SELECT strftime('%Y-%m', return_date) as month, COUNT(*) as returns_count FROM Issued WHERE return_date IS NOT NULL GROUP BY strftime('%Y-%m', return_date) ORDER BY month DESC"
    
    elif "show special permissions" in query_lower or "special permissions" in query_lower:
        return "SELECT sp.*, s.name as student_name, b.title as book_title FROM SpecialPermissions sp JOIN Students s ON sp.student_id = s.id JOIN Books b ON sp.book_id = b.id ORDER BY sp.granted_date DESC"
    
    # EXTENSIVE STUDENT PATTERNS
    elif "show my borrowed books history" in query_lower or "my borrowed books history" in query_lower:
        return "SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = [CURRENT_STUDENT_ID] ORDER BY i.issue_date DESC"
    
    elif "display my current fines" in query_lower or "my current fines" in query_lower:
        return "SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id WHERE f.student_id = [CURRENT_STUDENT_ID] AND f.status = 'Unpaid' ORDER BY f.issue_date DESC"
    
    elif "find books recommended for my major" in query_lower or "books recommended for my major" in query_lower:
        return "SELECT DISTINCT b.* FROM Books b JOIN Students s ON b.department_id = s.branch WHERE s.id = [CURRENT_STUDENT_ID] AND b.id NOT IN (SELECT book_id FROM Issued WHERE student_id = [CURRENT_STUDENT_ID]) ORDER BY b.title LIMIT 10"
    
    elif "show my library account balance" in query_lower or "my library account balance" in query_lower:
        return "SELECT s.name, SUM(f.fine_amount) as total_balance FROM Students s LEFT JOIN Fines f ON s.id = f.student_id WHERE s.id = [CURRENT_STUDENT_ID] AND f.status = 'Unpaid' GROUP BY s.id, s.name"
    
    elif "display books I have reserved" in query_lower or "books I have reserved" in query_lower:
        return "SELECT r.*, b.title, b.author FROM Reservations r JOIN Books b ON r.book_id = b.id WHERE r.student_id = [CURRENT_STUDENT_ID] ORDER BY r.reservation_date DESC"
    
    elif "find books due tomorrow" in query_lower or "books due tomorrow" in query_lower:
        return "SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = [CURRENT_STUDENT_ID] AND i.due_date = date('now', '+1 day') AND i.return_date IS NULL"
    
    elif "show my reading history" in query_lower or "my reading history" in query_lower:
        return "SELECT b.title, b.author, i.issue_date, i.return_date FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = [CURRENT_STUDENT_ID] ORDER BY i.issue_date DESC"
    
    elif "find books available for borrowing" in query_lower or "books available for borrowing" in query_lower:
        return "SELECT b.* FROM Books b WHERE b.id NOT IN (SELECT book_id FROM Issued WHERE student_id = [CURRENT_STUDENT_ID] AND return_date IS NULL) AND b.available_copies > 0 ORDER BY b.title"
    
    elif "show my academic performance" in query_lower or "my academic performance" in query_lower:
        return "SELECT s.gpa, s.attendance, s.academic_warning, s.honors FROM Students s WHERE s.id = [CURRENT_STUDENT_ID]"
    
    elif "display my course reading list" in query_lower or "my course reading list" in query_lower:
        return "SELECT b.title, b.author, c.course_code FROM Books b JOIN CourseMaterials cm ON b.id = cm.book_id JOIN Courses c ON cm.course_id = c.id JOIN CourseEnrollment ce ON c.id = ce.course_id WHERE ce.student_id = [CURRENT_STUDENT_ID]"
    
    elif "find books by my favorite authors" in query_lower or "books by my favorite authors" in query_lower:
        return "SELECT DISTINCT b.* FROM Books b JOIN Issued i ON b.id = i.book_id WHERE i.student_id = [CURRENT_STUDENT_ID] AND b.author IS NOT NULL GROUP BY b.author ORDER BY COUNT(i.id) DESC"
    
    elif "show my borrowing statistics" in query_lower or "my borrowing statistics" in query_lower:
        return "SELECT COUNT(i.id) as total_borrowed, AVG(julianday(i.return_date) - julianday(i.issue_date)) as avg_days FROM Students s LEFT JOIN Issued i ON s.id = i.student_id WHERE s.id = [CURRENT_STUDENT_ID] AND i.return_date IS NOT NULL"
    
    elif "find books for my research" in query_lower or "books for my research" in query_lower:
        return "SELECT b.* FROM Books b JOIN Students s ON b.department_id = s.branch WHERE s.id = [CURRENT_STUDENT_ID] AND b.category IN ('Research', 'Academic', 'Journal') ORDER BY b.title"
    
    elif "find books in my reading level" in query_lower or "books in my reading level" in query_lower:
        return "SELECT b.* FROM Books b WHERE b.reading_level <= (SELECT reading_level FROM Students WHERE id = [CURRENT_STUDENT_ID]) ORDER BY b.title"
    
    # EXTENSIVE LIBRARIAN PATTERNS
    elif "show books checked out today" in query_lower or "books checked out today" in query_lower:
        return "SELECT i.*, b.title, s.name as student_name FROM Issued i JOIN Books b ON i.book_id = b.id JOIN Students s ON i.student_id = s.id WHERE DATE(i.issue_date) = DATE('now') ORDER BY i.issue_time"
    
    elif "find books on hold for students" in query_lower or "books on hold" in query_lower:
        return "SELECT r.*, b.title, s.name as student_name FROM Reservations r JOIN Books b ON r.book_id = b.id JOIN Students s ON r.student_id = s.id WHERE r.status = 'Active' ORDER BY r.reservation_date"
    
    elif "display student fine reports" in query_lower or "student fine reports" in query_lower:
        return "SELECT s.name, s.email, COUNT(f.id) as fine_count, SUM(f.fine_amount) as total_fines FROM Students s LEFT JOIN Fines f ON s.id = f.student_id GROUP BY s.id, s.name ORDER BY total_fines DESC"
    
    elif "find books needing repair" in query_lower or "books needing repair" in query_lower:
        return "SELECT b.*, COUNT(i.id) as issue_count FROM Books b JOIN Issued i ON b.id = i.book_id WHERE i.condition IN ('Damaged', 'Poor') GROUP BY b.id, b.title ORDER BY issue_count DESC"
    
    elif "display reservation queue" in query_lower or "reservation queue" in query_lower:
        return "SELECT r.*, b.title, s.name as student_name FROM Reservations r JOIN Books b ON r.book_id = b.id JOIN Students s ON r.student_id = s.id ORDER BY r.reservation_date"
    
    elif "find books with high demand" in query_lower or "books with high demand" in query_lower:
        return "SELECT b.*, COUNT(i.id) as issue_count, COUNT(r.id) as reservation_count FROM Books b LEFT JOIN Issued i ON b.id = i.book_id LEFT JOIN Reservations r ON b.id = r.book_id GROUP BY b.id, b.title HAVING (issue_count > 5 OR reservation_count > 2) ORDER BY issue_count DESC"
    
    elif "show library inventory status" in query_lower or "library inventory status" in query_lower:
        return "SELECT b.title, b.copies, COUNT(i.id) as issued, COUNT(r.id) as reserved FROM Books b LEFT JOIN Issued i ON b.id = i.book_id AND i.return_date IS NULL LEFT JOIN Reservations r ON b.id = r.book_id AND r.status = 'Active' GROUP BY b.id, b.title"
    
    elif "show circulation desk statistics" in query_lower or "circulation desk statistics" in query_lower:
        return "SELECT DATE(i.issue_date) as date, COUNT(*) as checkouts, COUNT(CASE WHEN i.return_date IS NOT NULL THEN 1 END) as returns FROM Issued i GROUP BY DATE(i.issue_date) ORDER BY date DESC"
    
    elif "find books with missing information" in query_lower or "books with missing information" in query_lower:
        return "SELECT * FROM Books WHERE title IS NULL OR author IS NULL OR publish_date IS NULL OR isbn IS NULL"
    
    elif "show library usage reports" in query_lower or "library usage reports" in query_lower:
        return "SELECT strftime('%Y-%m', i.issue_date) as month, COUNT(*) as visits, COUNT(DISTINCT i.student_id) as unique_users FROM Issued i GROUP BY strftime('%Y-%m', i.issue_date) ORDER BY month DESC"
    
    elif "find expired library cards" in query_lower or "expired library cards" in query_lower:
        return "SELECT s.* FROM Students s WHERE s.card_expiry < date('now') ORDER BY s.card_expiry"
    
    elif "show staff work schedules" in query_lower or "staff work schedules" in query_lower:
        return "SELECT e.name, e.position, e.work_schedule, e.shift FROM Employees e WHERE e.department = 'Library' ORDER BY e.name"
    
    elif "display library event calendar" in query_lower or "library event calendar" in query_lower:
        return "SELECT e.title, e.description, e.event_date, e.event_time FROM Events e WHERE e.location = 'Library' ORDER BY e.event_date"
    
    # BATCH 1: 50 MORE PATTERNS
    elif "show books published this year" in query_lower:
        return "SELECT * FROM Books WHERE strftime('%Y', publish_date) = strftime('%Y', date('now')) ORDER BY publish_date DESC"
    
    elif "display students with birthday today" in query_lower:
        return "SELECT * FROM Students WHERE strftime('%m-%d', birthday) = strftime('%m-%d', date('now'))"
    
    elif "find books by publication month" in query_lower:
        return "SELECT strftime('%m', publish_date) as month, COUNT(*) as count FROM Books GROUP BY month ORDER BY count DESC"
    
    elif "show faculty by department" in query_lower:
        return "SELECT d.name as department, f.name as faculty_name FROM Faculty f JOIN Departments d ON f.department_id = d.id ORDER BY d.name, f.name"
    
    elif "display students by GPA range" in query_lower:
        return "SELECT CASE WHEN gpa >= 3.5 THEN 'High' WHEN gpa >= 3.0 THEN 'Medium' ELSE 'Low' END as gpa_range, COUNT(*) as count FROM Students GROUP BY gpa_range"
    
    elif "find books with multiple editions" in query_lower:
        return "SELECT title, COUNT(*) as editions FROM Books GROUP BY title HAVING COUNT(*) > 1 ORDER BY editions DESC"
    
    elif "show books by language and category" in query_lower:
        return "SELECT language, category, COUNT(*) as count FROM Books GROUP BY language, category ORDER BY count DESC"
    
    elif "display students by enrollment year" in query_lower:
        return "SELECT strftime('%Y', enrollment_date) as year, COUNT(*) as count FROM Students GROUP BY year ORDER BY year DESC"
    
    elif "find faculty with PhD only" in query_lower:
        return "SELECT * FROM Faculty WHERE qualification = 'PhD' ORDER BY name"
    
    elif "show books by acquisition date" in query_lower:
        return "SELECT * FROM Books ORDER BY acquisition_date DESC"
    
    elif "display students with scholarships" in query_lower:
        return "SELECT s.*, sch.type, sch.amount FROM Students s JOIN Scholarships sch ON s.id = sch.student_id ORDER BY sch.amount DESC"
    
    elif "find books in specific category" in query_lower:
        return "SELECT * FROM Books WHERE category = [CATEGORY_NAME] ORDER BY title"
    
    elif "show departments by budget" in query_lower:
        return "SELECT name, budget FROM Departments ORDER BY budget DESC"
    
    elif "display students by attendance range" in query_lower:
        return "SELECT CASE WHEN attendance >= 95 THEN 'Excellent' WHEN attendance >= 85 THEN 'Good' ELSE 'Poor' END as attendance_range, COUNT(*) as count FROM Students GROUP BY attendance_range"
    
    elif "find books by price range" in query_lower:
        return "SELECT title, price FROM Books WHERE price BETWEEN [MIN_PRICE] AND [MAX_PRICE] ORDER BY price"
    
    elif "show faculty by years of service" in query_lower:
        return "SELECT name, years_of_service FROM Faculty ORDER BY years_of_service DESC"
    
    elif "display students by credit hours" in query_lower:
        return "SELECT name, credit_hours FROM Students ORDER BY credit_hours DESC"
    
    elif "find books with high ratings" in query_lower:
        return "SELECT * FROM Books WHERE rating >= 4.0 ORDER BY rating DESC"
    
    elif "show books by popularity" in query_lower:
        return "SELECT b.title, COUNT(i.id) as borrow_count FROM Books b JOIN Issued i ON b.id = i.book_id GROUP BY b.id, b.title ORDER BY borrow_count DESC"
    
    elif "display students with part-time jobs" in query_lower:
        return "SELECT * FROM Students WHERE employment_status = 'Part-time'"
    
    elif "find books by reading difficulty" in query_lower:
        return "SELECT * FROM Books ORDER BY reading_level ASC"
    
    elif "show faculty by research area" in query_lower:
        return "SELECT name, research_area FROM Faculty ORDER BY research_area, name"
    
    elif "display students by hometown" in query_lower:
        return "SELECT hometown, COUNT(*) as count FROM Students GROUP BY hometown ORDER BY count DESC"
    
    elif "find books with digital versions" in query_lower:
        return "SELECT * FROM Books WHERE digital_available = 'Yes'"
    
    elif "show books by publication decade" in query_lower:
        return "SELECT SUBSTR(publish_date, 1, 3) || '0s' as decade, COUNT(*) as count FROM Books GROUP BY decade ORDER BY decade"
    
    elif "display students with internships" in query_lower:
        return "SELECT * FROM Students WHERE internship_status = 'Active'"
    
    elif "find books by subject area" in query_lower:
        return "SELECT * FROM Books WHERE subject_area = [SUBJECT_AREA] ORDER BY title"
    
    elif "show faculty with grants" in query_lower:
        return "SELECT f.*, g.title, g.amount FROM Faculty f JOIN Grants g ON f.id = g.faculty_id ORDER BY g.amount DESC"
    
    elif "display students by major and GPA" in query_lower:
        return "SELECT major, AVG(gpa) as avg_gpa FROM Students GROUP BY major ORDER BY avg_gpa DESC"
    
    elif "find books with missing ISBN" in query_lower:
        return "SELECT * FROM Books WHERE isbn IS NULL OR isbn = ''"
    
    elif "show books by condition" in query_lower:
        return "SELECT condition, COUNT(*) as count FROM Books GROUP BY condition ORDER BY count DESC"
    
    elif "display students with honors" in query_lower:
        return "SELECT * FROM Students WHERE honors = 'Yes' ORDER BY gpa DESC"
    
    elif "find books by publisher and year" in query_lower:
        return "SELECT * FROM Books WHERE publisher = [PUBLISHER] AND strftime('%Y', publish_date) = [YEAR]"
    
    elif "show faculty by teaching load" in query_lower:
        return "SELECT f.name, COUNT(c.id) as courses FROM Faculty f JOIN Courses c ON f.id = c.faculty_id GROUP BY f.id, f.name ORDER BY courses DESC"
    
    elif "display students by graduation year" in query_lower:
        return "SELECT graduation_year, COUNT(*) as count FROM Students GROUP BY graduation_year ORDER BY graduation_year DESC"
    
    elif "find books with multiple authors" in query_lower:
        return "SELECT * FROM Books WHERE author LIKE '%,%' ORDER BY title"
    
    elif "show books by acquisition cost" in query_lower:
        return "SELECT * FROM Books ORDER BY cost DESC"
    
    elif "display students with research experience" in query_lower:
        return "SELECT * FROM Students WHERE research_experience = 'Yes'"
    
    elif "find books in foreign languages" in query_lower:
        return "SELECT * FROM Books WHERE language != 'English' ORDER BY language, title"
    
    elif "show faculty by department head" in query_lower:
        return "SELECT d.name as department, f.name as head FROM Departments d JOIN Faculty f ON d.head_id = f.id"
    
    elif "display students with study abroad" in query_lower:
        return "SELECT * FROM Students WHERE study_abroad = 'Yes'"
    
    elif "find books with overdue fines" in query_lower:
        return "SELECT b.*, COUNT(f.id) as fine_count FROM Books b JOIN Issued i ON b.id = i.book_id JOIN Fines f ON i.student_id = f.student_id WHERE i.return_date > i.due_date GROUP BY b.id, b.title"
    
    elif "show books by series" in query_lower:
        return "SELECT series, COUNT(*) as count FROM Books WHERE series IS NOT NULL GROUP BY series ORDER BY count DESC"
    
    elif "display students with leadership roles" in query_lower:
        return "SELECT * FROM Students WHERE leadership_role = 'Yes'"
    
    elif "find books by award status" in query_lower:
        return "SELECT * FROM Books WHERE award_winner = 'Yes' ORDER BY award_year DESC"
    
    elif "show faculty by publication count" in query_lower:
        return "SELECT f.name, COUNT(p.id) as publications FROM Faculty f LEFT JOIN Publications p ON f.id = p.faculty_id GROUP BY f.id, f.name ORDER BY publications DESC"
    
    elif "display students by extracurricular activities" in query_lower:
        return "SELECT activity, COUNT(*) as count FROM StudentActivities GROUP BY activity ORDER BY count DESC"
    
    elif "find books with limited copies" in query_lower:
        return "SELECT * FROM Books WHERE copies <= 3 ORDER BY copies ASC"
    
    elif "show books by subject classification" in query_lower:
        return "SELECT subject_classification, COUNT(*) as count FROM Books GROUP BY subject_classification ORDER BY count DESC"
    
    elif "display students with work experience" in query_lower:
        return "SELECT * FROM Students WHERE work_experience = 'Yes'"
    
    elif "find books recommended by faculty" in query_lower:
        return "SELECT b.*, f.name as recommender FROM Books b JOIN FacultyRecommendations fr ON b.id = fr.book_id JOIN Faculty f ON fr.faculty_id = f.id ORDER BY fr.recommendation_date DESC"
    
    elif "show books by copyright year" in query_lower:
        return "SELECT copyright_year, COUNT(*) as count FROM Books GROUP BY copyright_year ORDER BY copyright_year DESC"
    
    elif "display students with certifications" in query_lower:
        return "SELECT s.*, c.certification_name, c.issue_date FROM Students s JOIN Certifications c ON s.id = c.student_id ORDER BY c.issue_date DESC"
    
    elif "find books with high demand" in query_lower:
        return "SELECT b.*, COUNT(i.id) as demand FROM Books b JOIN Issued i ON b.id = i.book_id GROUP BY b.id, b.title HAVING COUNT(i.id) > 10 ORDER BY demand DESC"
    # BATCH 2: 50 MORE PATTERNS
    elif "show books by page count" in query_lower:
        return "SELECT title, pages FROM Books ORDER BY pages DESC"
    
    elif "display students by age group" in query_lower:
        return "SELECT CASE WHEN age < 20 THEN 'Under 20' WHEN age < 25 THEN '20-24' WHEN age < 30 THEN '25-29' ELSE '30+' END as age_group, COUNT(*) as count FROM Students GROUP BY age_group"
    
    elif "find books by binding type" in query_lower:
        return "SELECT binding_type, COUNT(*) as count FROM Books GROUP BY binding_type ORDER BY count DESC"
    
    elif "show faculty by rank" in query_lower:
        return "SELECT rank, COUNT(*) as count FROM Faculty GROUP BY rank ORDER BY count DESC"
    
    elif "display students by enrollment status" in query_lower:
        return "SELECT enrollment_status, COUNT(*) as count FROM Students GROUP BY enrollment_status"
    
    elif "find books with illustrations" in query_lower:
        return "SELECT * FROM Books WHERE illustrations = 'Yes'"
    
    elif "show books by shelf location" in query_lower:
        return "SELECT shelf_location, COUNT(*) as count FROM Books GROUP BY shelf_location ORDER BY shelf_location"
    
    elif "display students by GPA percentile" in query_lower:
        return "SELECT CASE WHEN gpa >= 3.8 THEN 'Top 10%' WHEN gpa >= 3.5 THEN 'Top 25%' WHEN gpa >= 3.0 THEN 'Top 50%' ELSE 'Bottom 50%' END as percentile, COUNT(*) as count FROM Students GROUP BY percentile"
    
    elif "find books by editor" in query_lower:
        return "SELECT * FROM Books WHERE editor IS NOT NULL ORDER BY editor, title"
    
    elif "show faculty by degree" in query_lower:
        return "SELECT highest_degree, COUNT(*) as count FROM Faculty GROUP BY highest_degree ORDER BY count DESC"
    
    elif "display students by financial aid" in query_lower:
        return "SELECT financial_aid_status, COUNT(*) as count FROM Students GROUP BY financial_aid_status"
    
    elif "find books with companion websites" in query_lower:
        return "SELECT * FROM Books WHERE companion_website IS NOT NULL"
    
    elif "show books by publication frequency" in query_lower:
        return "SELECT publication_frequency, COUNT(*) as count FROM Books GROUP BY publication_frequency ORDER BY count DESC"
    
    elif "display students by dormitory" in query_lower:
        return "SELECT dormitory, COUNT(*) as count FROM Students GROUP BY dormitory ORDER BY count DESC"
    
    elif "find books with study guides" in query_lower:
        return "SELECT * FROM Books WHERE study_guide = 'Yes'"
    
    elif "show faculty by office location" in query_lower:
        return "SELECT office_location, COUNT(*) as count FROM Faculty GROUP BY office_location ORDER BY count DESC"
    
    elif "display students by meal plan" in query_lower:
        return "SELECT meal_plan, COUNT(*) as count FROM Students GROUP BY meal_plan ORDER BY count DESC"
    
    elif "find books with audio versions" in query_lower:
        return "SELECT * FROM Books WHERE audio_available = 'Yes'"
    
    elif "show books by translator" in query_lower:
        return "SELECT translator, COUNT(*) as count FROM Books WHERE translator IS NOT NULL GROUP BY translator ORDER BY count DESC"
    
    elif "display students by parking permit" in query_lower:
        return "SELECT parking_permit, COUNT(*) as count FROM Students GROUP BY parking_permit"
    
    elif "find books with online access" in query_lower:
        return "SELECT * FROM Books WHERE online_access = 'Yes'"
    
    elif "show faculty by committee membership" in query_lower:
        return "SELECT f.name, COUNT(cm.committee_id) as committees FROM Faculty f JOIN CommitteeMembers cm ON f.id = cm.faculty_id GROUP BY f.id, f.name ORDER BY committees DESC"
    
    elif "display students by sports participation" in query_lower:
        return "SELECT sport, COUNT(*) as count FROM StudentSports GROUP BY sport ORDER BY count DESC"
    
    elif "find books with teacher editions" in query_lower:
        return "SELECT * FROM Books WHERE teacher_edition = 'Yes'"
    
    elif "show books by publication country" in query_lower:
        return "SELECT publication_country, COUNT(*) as count FROM Books GROUP BY publication_country ORDER BY count DESC"
    
    elif "display students by health insurance" in query_lower:
        return "SELECT health_insurance, COUNT(*) as count FROM Students GROUP BY health_insurance"
    
    elif "find books with multimedia" in query_lower:
        return "SELECT * FROM Books WHERE multimedia_included = 'Yes'"
    
    elif "show faculty by conference presentations" in query_lower:
        return "SELECT f.name, COUNT(cp.conference_id) as presentations FROM Faculty f JOIN ConferencePresentations cp ON f.id = cp.faculty_id GROUP BY f.id, f.name ORDER BY presentations DESC"
    
    elif "display students by visa status" in query_lower:
        return "SELECT visa_status, COUNT(*) as count FROM Students GROUP BY visa_status ORDER BY count DESC"
    
    elif "find books with answer keys" in query_lower:
        return "SELECT * FROM Books WHERE answer_key = 'Yes'"
    
    elif "show books by imprint" in query_lower:
        return "SELECT imprint, COUNT(*) as count FROM Books GROUP BY imprint ORDER BY count DESC"
    
    elif "display students by emergency contact" in query_lower:
        return "SELECT emergency_contact_relation, COUNT(*) as count FROM Students GROUP BY emergency_contact_relation ORDER BY count DESC"
    
    elif "find books with test banks" in query_lower:
        return "SELECT * FROM Books WHERE test_bank = 'Yes'"
    
    elif "show faculty by patent count" in query_lower:
        return "SELECT f.name, COUNT(p.patent_id) as patents FROM Faculty f JOIN Patents p ON f.id = p.faculty_id GROUP BY f.id, f.name ORDER BY patents DESC"
    
    elif "display students by computer ownership" in query_lower:
        return "SELECT computer_ownership, COUNT(*) as count FROM Students GROUP BY computer_ownership"
    
    elif "find books with lab manuals" in query_lower:
        return "SELECT * FROM Books WHERE lab_manual = 'Yes'"
    
    elif "show books by distributor" in query_lower:
        return "SELECT distributor, COUNT(*) as count FROM Books GROUP BY distributor ORDER BY count DESC"
    
    elif "display students by internet access" in query_lower:
        return "SELECT internet_access, COUNT(*) as count FROM Students GROUP BY internet_access"
    
    elif "find books with software" in query_lower:
        return "SELECT * FROM Books WHERE software_included = 'Yes'"
    
    elif "show faculty by consulting work" in query_lower:
        return "SELECT f.name, COUNT(c.consulting_id) as consulting_projects FROM Faculty f JOIN Consulting c ON f.id = c.faculty_id GROUP BY f.id, f.name ORDER BY consulting_projects DESC"
    
    elif "display students by transportation" in query_lower:
        return "SELECT transportation_method, COUNT(*) as count FROM Students GROUP BY transportation_method ORDER BY count DESC"
    
    elif "find books with workbooks" in query_lower:
        return "SELECT * FROM Books WHERE workbook_included = 'Yes'"
    
    elif "show books by sales region" in query_lower:
        return "SELECT sales_region, COUNT(*) as count FROM Books GROUP BY sales_region ORDER BY count DESC"
    
    elif "display students by living arrangement" in query_lower:
        return "SELECT living_arrangement, COUNT(*) as count FROM Students GROUP BY living_arrangement ORDER BY count DESC"
    
    elif "find books with videos" in query_lower:
        return "SELECT * FROM Books WHERE video_included = 'Yes'"
    
    elif "show faculty by industry experience" in query_lower:
        return "SELECT f.name, f.industry_years FROM Faculty WHERE industry_years > 0 ORDER BY industry_years DESC"
    
    elif "display students by employment sector" in query_lower:
        return "SELECT employment_sector, COUNT(*) as count FROM Students GROUP BY employment_sector ORDER BY count DESC"
    
    elif "find books with CDs" in query_lower:
        return "SELECT * FROM Books WHERE cd_included = 'Yes'"
    
    elif "show books by target audience" in query_lower:
        return "SELECT target_audience, COUNT(*) as count FROM Books GROUP BY target_audience ORDER BY count DESC"
    
    elif "display students by disability status" in query_lower:
        return "SELECT disability_status, COUNT(*) as count FROM Students GROUP BY disability_status"
    
    elif "find books with DVDs" in query_lower:
        return "SELECT * FROM Books WHERE dvd_included = 'Yes'"
    
    elif "show faculty by startup involvement" in query_lower:
        return "SELECT f.name, COUNT(s.startup_id) as startups FROM Faculty f JOIN Startups s ON f.id = s.faculty_id GROUP BY f.id, f.name ORDER BY startups DESC"
    
    elif "display students by military service" in query_lower:
        return "SELECT military_service, COUNT(*) as count FROM Students GROUP BY military_service"
    
    elif "find books with online resources" in query_lower:
        return "SELECT * FROM Books WHERE online_resources = 'Yes'"

    # BATCH 3: 50 MORE PATTERNS
    elif "show books by reading time" in query_lower:
        return "SELECT title, estimated_reading_hours FROM Books ORDER BY estimated_reading_hours DESC"
    
    elif "display students by study hours" in query_lower:
        return "SELECT CASE WHEN weekly_study_hours < 10 THEN 'Light' WHEN weekly_study_hours < 20 THEN 'Moderate' ELSE 'Heavy' END as study_intensity, COUNT(*) as count FROM Students GROUP BY study_intensity"
    
    elif "find books by difficulty level" in query_lower:
        return "SELECT difficulty_level, COUNT(*) as count FROM Books GROUP BY difficulty_level ORDER BY difficulty_level"
    
    elif "show faculty by teaching experience" in query_lower:
        return "SELECT name, teaching_years FROM Faculty ORDER BY teaching_years DESC"
    
    elif "display students by library visits" in query_lower:
        return "SELECT CASE WHEN monthly_library_visits < 5 THEN 'Rare' WHEN monthly_library_visits < 15 THEN 'Regular' ELSE 'Frequent' END as visit_frequency, COUNT(*) as count FROM Students GROUP BY visit_frequency"
    
    elif "find books by content type" in query_lower:
        return "SELECT content_type, COUNT(*) as count FROM Books GROUP BY content_type ORDER BY count DESC"
    
    elif "show faculty by research funding" in query_lower:
        return "SELECT name, total_research_funding FROM Faculty ORDER BY total_research_funding DESC"
    
    elif "display students by book preferences" in query_lower:
        return "SELECT preferred_genre, COUNT(*) as count FROM Students GROUP BY preferred_genre ORDER BY count DESC"
    
    elif "find books by accessibility features" in query_lower:
        return "SELECT * FROM Books WHERE accessibility_features = 'Yes'"
    
    elif "show faculty by student mentorship" in query_lower:
        return "SELECT f.name, COUNT(m.student_id) as mentees FROM Faculty f JOIN Mentorship m ON f.id = m.faculty_id GROUP BY f.id, f.name ORDER BY mentees DESC"
    
    elif "display students by technology skills" in query_lower:
        return "SELECT tech_skill_level, COUNT(*) as count FROM Students GROUP BY tech_skill_level ORDER BY tech_skill_level"
    
    elif "find books by environmental rating" in query_lower:
        return "SELECT * FROM Books WHERE eco_friendly = 'Yes'"
    
    elif "show faculty by international experience" in query_lower:
        return "SELECT name, international_programs FROM Faculty ORDER BY international_programs DESC"
    
    elif "display students by language proficiency" in query_lower:
        return "SELECT primary_language, COUNT(*) as count FROM Students GROUP BY primary_language ORDER BY count DESC"
    
    elif "find books by award nominations" in query_lower:
        return "SELECT * FROM Books WHERE award_nominations > 0 ORDER BY award_nominations DESC"
    
    elif "show faculty by publication impact" in query_lower:
        return "SELECT f.name, SUM(p.citation_count) as total_citations FROM Faculty f JOIN Publications p ON f.id = p.faculty_id GROUP BY f.id, f.name ORDER BY total_citations DESC"
    
    elif "display students by academic goals" in query_lower:
        return "SELECT academic_goal, COUNT(*) as count FROM Students GROUP BY academic_goal ORDER BY count DESC"
    
    elif "find books by curriculum alignment" in query_lower:
        return "SELECT * FROM Books WHERE curriculum_aligned = 'Yes'"
    
    elif "show faculty by department leadership" in query_lower:
        return "SELECT f.name, d.name as department FROM Faculty f JOIN Departments d ON f.id = d.head_id"
    
    elif "display students by career aspirations" in query_lower:
        return "SELECT career_goal, COUNT(*) as count FROM Students GROUP BY career_goal ORDER BY count DESC"
    
    elif "find books by peer reviews" in query_lower:
        return "SELECT * FROM Books WHERE peer_reviewed = 'Yes'"
    
    elif "show faculty by grant success rate" in query_lower:
        return "SELECT f.name, (COUNT(CASE WHEN g.status = 'Approved' THEN 1 END) * 100.0 / COUNT(g.id)) as success_rate FROM Faculty f LEFT JOIN Grants g ON f.id = g.faculty_id GROUP BY f.id, f.name ORDER BY success_rate DESC"
    
    elif "display students by learning style" in query_lower:
        return "SELECT learning_style, COUNT(*) as count FROM Students GROUP BY learning_style ORDER BY count DESC"
    
    elif "find books by citation count" in query_lower:
        return "SELECT * FROM Books WHERE citation_count > 0 ORDER BY citation_count DESC"
    
    elif "show faculty by collaboration network" in query_lower:
        return "SELECT f.name, COUNT(DISTINCT co.faculty_id) as collaborators FROM Faculty f JOIN CoAuthorships co ON f.id = co.faculty_id GROUP BY f.id, f.name ORDER BY collaborators DESC"
    
    elif "display students by social media usage" in query_lower:
        return "SELECT social_media_usage, COUNT(*) as count FROM Students GROUP BY social_media_usage ORDER BY count DESC"
    
    elif "find books by translation availability" in query_lower:
        return "SELECT * FROM Books WHERE translated_languages IS NOT NULL"
    
    elif "show faculty by teaching awards" in query_lower:
        return "SELECT f.name, COUNT(ta.award_id) as teaching_awards FROM Faculty f JOIN TeachingAwards ta ON f.id = ta.faculty_id GROUP BY f.id, f.name ORDER BY teaching_awards DESC"
    
    elif "display students by volunteer hours" in query_lower:
        return "SELECT CASE WHEN volunteer_hours < 10 THEN 'Low' WHEN volunteer_hours < 50 THEN 'Medium' ELSE 'High' END as volunteer_level, COUNT(*) as count FROM Students GROUP BY volunteer_level"
    
    elif "find books by open access" in query_lower:
        return "SELECT * FROM Books WHERE open_access = 'Yes'"
    
    elif "show faculty by industry partnerships" in query_lower:
        return "SELECT f.name, COUNT(ip.partnership_id) as partnerships FROM Faculty f JOIN IndustryPartnerships ip ON f.id = ip.faculty_id GROUP BY f.id, f.name ORDER BY partnerships DESC"
    
    elif "display students by internship experience" in query_lower:
        return "SELECT internship_company, COUNT(*) as count FROM Students GROUP BY internship_company ORDER BY count DESC"
    
    elif "find books by supplemental materials" in query_lower:
        return "SELECT * FROM Books WHERE supplemental_materials = 'Yes'"
    
    elif "show faculty by alumni success" in query_lower:
        return "SELECT f.name, COUNT(DISTINCT a.alumni_id) as successful_alumni FROM Faculty f JOIN Alumni a ON f.id = a.mentor_faculty_id GROUP BY f.id, f.name ORDER BY successful_alumni DESC"
    
    elif "display students by research interests" in query_lower:
        return "SELECT research_interest, COUNT(*) as count FROM Students GROUP BY research_interest ORDER BY count DESC"
    
    elif "find books by interactivity level" in query_lower:
        return "SELECT interactivity_level, COUNT(*) as count FROM Books GROUP BY interactivity_level ORDER BY interactivity_level"
    
    elif "show faculty by curriculum development" in query_lower:
        return "SELECT f.name, COUNT(cd.curriculum_id) as curricula FROM Faculty f JOIN CurriculumDevelopment cd ON f.id = cd.faculty_id GROUP BY f.id, f.name ORDER BY curricula DESC"
    
    elif "display students by extracurricular leadership" in query_lower:
        return "SELECT leadership_position, COUNT(*) as count FROM Students GROUP BY leadership_position ORDER BY count DESC"
    
    elif "find books by assessment tools" in query_lower:
        return "SELECT * FROM Books WHERE assessment_tools = 'Yes'"
    
    elif "show faculty by professional development" in query_lower:
        return "SELECT f.name, COUNT(pd.development_id) as development_activities FROM Faculty f JOIN ProfessionalDevelopment pd ON f.id = pd.faculty_id GROUP BY f.id, f.name ORDER BY development_activities DESC"
    
    elif "display students by academic honors" in query_lower:
        return "SELECT honor_type, COUNT(*) as count FROM StudentHonors GROUP BY honor_type ORDER BY count DESC"
    
    elif "find books by adaptive learning" in query_lower:
        return "SELECT * FROM Books WHERE adaptive_learning = 'Yes'"
    
    elif "show faculty by community service" in query_lower:
        return "SELECT f.name, community_service_hours FROM Faculty ORDER BY community_service_hours DESC"
    
    elif "display students by peer tutoring" in query_lower:
        return "SELECT subject_tutored, COUNT(*) as count FROM PeerTutoring GROUP BY subject_tutored ORDER BY count DESC"
    
    elif "find books by gamification" in query_lower:
        return "SELECT * FROM Books WHERE gamification_features = 'Yes'"
    
    elif "show faculty by innovation projects" in query_lower:
        return "SELECT f.name, COUNT(ip.innovation_id) as innovations FROM Faculty f JOIN InnovationProjects ip ON f.id = ip.faculty_id GROUP BY f.id, f.name ORDER BY innovations DESC"
    
    elif "display students by study groups" in query_lower:
        return "SELECT study_group_topic, COUNT(*) as count FROM StudyGroups GROUP BY study_group_topic ORDER BY count DESC"
    
    elif "find books by virtual reality" in query_lower:
        return "SELECT * FROM Books WHERE vr_support = 'Yes'"
    
    elif "show faculty by cross-disciplinary work" in query_lower:
        return "SELECT f.name, COUNT(DISTINCT cd.department_id) as departments FROM Faculty f JOIN CrossDisciplinary cd ON f.id = cd.faculty_id GROUP BY f.id, f.name ORDER BY departments DESC"
    
    elif "display students by peer mentoring" in query_lower:
        return "SELECT mentoring_area, COUNT(*) as count FROM PeerMentoring GROUP BY mentoring_area ORDER BY count DESC"
    
    elif "find books by artificial intelligence" in query_lower:
        return "SELECT * FROM Books WHERE ai_features = 'Yes'"

    # BATCH 4: 50 MORE PATTERNS
    elif "show books by publication frequency" in query_lower:
        return "SELECT publication_frequency, COUNT(*) as count FROM Books GROUP BY publication_frequency ORDER BY count DESC"
    
    elif "display students by academic probation" in query_lower:
        return "SELECT probation_status, COUNT(*) as count FROM Students GROUP BY probation_status"
    
    elif "find books by subscription model" in query_lower:
        return "SELECT * FROM Books WHERE subscription_required = 'Yes'"
    
    elif "show faculty by online teaching" in query_lower:
        return "SELECT name, online_courses_taught FROM Faculty ORDER BY online_courses_taught DESC"
    
    elif "display students by transfer status" in query_lower:
        return "SELECT transfer_status, COUNT(*) as count FROM Students GROUP BY transfer_status ORDER BY count DESC"
    
    elif "find books by licensing" in query_lower:
        return "SELECT license_type, COUNT(*) as count FROM Books GROUP BY license_type ORDER BY count DESC"
    
    elif "show faculty by hybrid teaching" in query_lower:
        return "SELECT name, hybrid_courses FROM Faculty ORDER BY hybrid_courses DESC"
    
    elif "display students by dual enrollment" in query_lower:
        return "SELECT dual_enrollment_status, COUNT(*) as count FROM Students GROUP BY dual_enrollment_status"
    
    elif "find books by regional availability" in query_lower:
        return "SELECT region, COUNT(*) as count FROM Books GROUP BY region ORDER BY count DESC"
    
    elif "show faculty by sabbatical" in query_lower:
        return "SELECT name, sabbatical_year, sabbatical_reason FROM Faculty WHERE sabbatical_year IS NOT NULL ORDER BY sabbatical_year DESC"
    
    elif "display students by exchange program" in query_lower:
        return "SELECT exchange_program, COUNT(*) as count FROM Students GROUP BY exchange_program ORDER BY count DESC"
    
    elif "find books by format type" in query_lower:
        return "SELECT format_type, COUNT(*) as count FROM Books GROUP BY format_type ORDER BY count DESC"
    
    elif "show faculty by emeritus status" in query_lower:
        return "SELECT * FROM Faculty WHERE emeritus_status = 'Yes' ORDER BY name"
    
    elif "display students by concurrent enrollment" in query_lower:
        return "SELECT concurrent_enrollment, COUNT(*) as count FROM Students GROUP BY concurrent_enrollment"
    
    elif "find books by distribution method" in query_lower:
        return "SELECT distribution_method, COUNT(*) as count FROM Books GROUP BY distribution_method ORDER BY count DESC"
    
    elif "show faculty by visiting status" in query_lower:
        return "SELECT * FROM Faculty WHERE visiting_faculty = 'Yes' ORDER BY name"
    
    elif "display students by early graduation" in query_lower:
        return "SELECT early_graduation_status, COUNT(*) as count FROM Students GROUP BY early_graduation_status"
    
    elif "find books by archival status" in query_lower:
        return "SELECT * FROM Books WHERE archival_copy = 'Yes'"
    
    elif "show faculty by adjunct status" in query_lower:
        return "SELECT * FROM Faculty WHERE employment_type = 'Adjunct' ORDER BY name"
    
    elif "display students by co-op program" in query_lower:
        return "SELECT co_op_status, COUNT(*) as count FROM Students GROUP BY co_op_status ORDER BY count DESC"
    
    elif "find books by rare collection" in query_lower:
        return "SELECT * FROM Books WHERE rare_book = 'Yes'"
    
    elif "show faculty by tenure track" in query_lower:
        return "SELECT tenure_status, COUNT(*) as count FROM Faculty GROUP BY tenure_status ORDER BY count DESC"
    
    elif "display students by gap year" in query_lower:
        return "SELECT gap_year_status, COUNT(*) as count FROM Students GROUP BY gap_year_status ORDER BY count DESC"
    
    elif "find books by special edition" in query_lower:
        return "SELECT * FROM Books WHERE special_edition = 'Yes'"
    
    elif "show faculty by department chair" in query_lower:
        return "SELECT f.name, d.name as department FROM Faculty f JOIN Departments d ON f.id = d.chair_id"
    
    elif "display students by accelerated program" in query_lower:
        return "SELECT accelerated_program, COUNT(*) as count FROM Students GROUP BY accelerated_program ORDER BY count DESC"
    
    elif "find books by signed copy" in query_lower:
        return "SELECT * FROM Books WHERE signed_copy = 'Yes'"
    
    elif "show faculty by research center" in query_lower:
        return "SELECT f.name, rc.name as research_center FROM Faculty f JOIN ResearchCenters rc ON f.id = rc.director_id"
    
    elif "display students by honors program" in query_lower:
        return "SELECT honors_program, COUNT(*) as count FROM Students GROUP BY honors_program ORDER BY count DESC"
    
    elif "find books by first edition" in query_lower:
        return "SELECT * FROM Books WHERE first_edition = 'Yes'"
    
    elif "show faculty by institute affiliation" in query_lower:
        return "SELECT f.name, i.name as institute FROM Faculty f JOIN Institutes i ON f.id = i.faculty_director_id"
    
    elif "display students by thesis status" in query_lower:
        return "SELECT thesis_status, COUNT(*) as count FROM Students GROUP BY thesis_status ORDER BY count DESC"
    
    elif "find books by limited print" in query_lower:
        return "SELECT * FROM Books WHERE limited_print_run = 'Yes'"
    
    elif "show faculty by lab director" in query_lower:
        return "SELECT f.name, l.name as laboratory FROM Faculty f JOIN Laboratories l ON f.id = l.director_id"
    
    elif "display students by dissertation status" in query_lower:
        return "SELECT dissertation_status, COUNT(*) as count FROM Students GROUP BY dissertation_status ORDER BY count DESC"
    
    elif "find books by autographed" in query_lower:
        return "SELECT * FROM Books WHERE autographed = 'Yes'"
    
    elif "show faculty by program coordinator" in query_lower:
        return "SELECT f.name, p.name as program FROM Faculty f JOIN Programs p ON f.id = p.coordinator_id"
    
    elif "display students by capstone status" in query_lower:
        return "SELECT capstone_status, COUNT(*) as count FROM Students GROUP BY capstone_status ORDER BY count DESC"
    
    elif "find books by collector item" in query_lower:
        return "SELECT * FROM Books WHERE collector_item = 'Yes'"
    
    elif "show faculty by advisory board" in query_lower:
        return "SELECT f.name, ab.name as advisory_board FROM Faculty f JOIN AdvisoryBoards ab ON f.id = ab.member_id"
    
    elif "display students by portfolio status" in query_lower:
        return "SELECT portfolio_status, COUNT(*) as count FROM Students GROUP BY portfolio_status ORDER BY count DESC"
    
    elif "find books by manuscript" in query_lower:
        return "SELECT * FROM Books WHERE manuscript_available = 'Yes'"
    
    elif "show faculty by editorial board" in query_lower:
        return "SELECT f.name, eb.name as editorial_board FROM Faculty f JOIN EditorialBoards eb ON f.id = eb.member_id"
    
    elif "display students by internship completion" in query_lower:
        return "SELECT internship_completion, COUNT(*) as count FROM Students GROUP BY internship_completion ORDER BY count DESC"
    
    elif "find books by proof copy" in query_lower:
        return "SELECT * FROM Books WHERE proof_copy = 'Yes'"
    
    elif "show faculty by review board" in query_lower:
        return "SELECT f.name, rb.name as review_board FROM Faculty f JOIN ReviewBoards rb ON f.id = rb.member_id"
    
    elif "display students by certification status" in query_lower:
        return "SELECT certification_status, COUNT(*) as count FROM Students GROUP BY certification_status ORDER BY count DESC"
    
    elif "find books by advance copy" in query_lower:
        return "SELECT * FROM Books WHERE advance_copy = 'Yes'"
    
    elif "show faculty by accreditation board" in query_lower:
        return "SELECT f.name, ab.name as accreditation_board FROM Faculty f JOIN AccreditationBoards ab ON f.id = ab.member_id"
    
    elif "display students by licensing status" in query_lower:
        return "SELECT licensing_status, COUNT(*) as count FROM Students GROUP BY licensing_status ORDER BY count DESC"
    
    elif "find books by galley proof" in query_lower:
        return "SELECT * FROM Books WHERE galley_proof = 'Yes'"

    # BATCH 5: 50 MORE PATTERNS
    elif "show books by reading difficulty" in query_lower:
        return "SELECT reading_difficulty, COUNT(*) as count FROM Books GROUP BY reading_difficulty ORDER BY reading_difficulty"
    
    elif "display students by academic standing" in query_lower:
        return "SELECT academic_standing, COUNT(*) as count FROM Students GROUP BY academic_standing ORDER BY count DESC"
    
    elif "find books by age appropriateness" in query_lower:
        return "SELECT age_range, COUNT(*) as count FROM Books GROUP BY age_range ORDER BY age_range"
    
    elif "show faculty by academic rank" in query_lower:
        return "SELECT academic_rank, COUNT(*) as count FROM Faculty GROUP BY academic_rank ORDER BY count DESC"
    
    elif "display students by enrollment type" in query_lower:
        return "SELECT enrollment_type, COUNT(*) as count FROM Students GROUP BY enrollment_type ORDER BY count DESC"
    
    elif "find books by content rating" in query_lower:
        return "SELECT content_rating, COUNT(*) as count FROM Books GROUP BY content_rating ORDER BY content_rating"
    
    elif "show faculty by employment status" in query_lower:
        return "SELECT employment_status, COUNT(*) as count FROM Faculty GROUP BY employment_status ORDER BY count DESC"
    
    elif "display students by financial status" in query_lower:
        return "SELECT financial_status, COUNT(*) as count FROM Students GROUP BY financial_status ORDER BY count DESC"
    
    elif "find books by educational level" in query_lower:
        return "SELECT educational_level, COUNT(*) as count FROM Books GROUP BY educational_level ORDER BY educational_level"
    
    elif "show faculty by contract type" in query_lower:
        return "SELECT contract_type, COUNT(*) as count FROM Faculty GROUP BY contract_type ORDER BY count DESC"
    
    elif "display students by housing status" in query_lower:
        return "SELECT housing_status, COUNT(*) as count FROM Students GROUP BY housing_status ORDER BY count DESC"
    
    elif "find books by subject matter" in query_lower:
        return "SELECT subject_matter, COUNT(*) as count FROM Books GROUP BY subject_matter ORDER BY count DESC"
    
    elif "show faculty by department affiliation" in query_lower:
        return "SELECT f.name, d.name as department FROM Faculty f JOIN Departments d ON f.department_id = d.id ORDER BY d.name, f.name"
    
    elif "display students by academic load" in query_lower:
        return "SELECT CASE WHEN credit_hours < 12 THEN 'Part-time' WHEN credit_hours < 18 THEN 'Full-time' ELSE 'Overload' END as academic_load, COUNT(*) as count FROM Students GROUP BY academic_load"
    
    elif "find books by genre classification" in query_lower:
        return "SELECT genre, COUNT(*) as count FROM Books GROUP BY genre ORDER BY count DESC"
    
    elif "show faculty by research area" in query_lower:
        return "SELECT research_area, COUNT(*) as count FROM Faculty GROUP BY research_area ORDER BY count DESC"
    
    elif "display students by academic performance" in query_lower:
        return "SELECT CASE WHEN gpa >= 3.8 THEN 'Excellent' WHEN gpa >= 3.2 THEN 'Good' WHEN gpa >= 2.5 THEN 'Average' ELSE 'Below Average' END as performance_level, COUNT(*) as count FROM Students GROUP BY performance_level"
    
    elif "find books by literary style" in query_lower:
        return "SELECT literary_style, COUNT(*) as count FROM Books GROUP BY literary_style ORDER BY count DESC"
    
    elif "show faculty by teaching methodology" in query_lower:
        return "SELECT teaching_methodology, COUNT(*) as count FROM Faculty GROUP BY teaching_methodology ORDER BY count DESC"
    
    elif "display students by learning modality" in query_lower:
        return "SELECT learning_modality, COUNT(*) as count FROM Students GROUP BY learning_modality ORDER BY count DESC"
    
    elif "find books by narrative type" in query_lower:
        return "SELECT narrative_type, COUNT(*) as count FROM Books GROUP BY narrative_type ORDER BY count DESC"
    
    elif "show faculty by specialization" in query_lower:
        return "SELECT specialization, COUNT(*) as count FROM Faculty GROUP BY specialization ORDER BY count DESC"
    
    elif "display students by communication style" in query_lower:
        return "SELECT communication_style, COUNT(*) as count FROM Students GROUP BY communication_style ORDER BY count DESC"
    
    elif "find books by thematic content" in query_lower:
        return "SELECT theme, COUNT(*) as count FROM Books GROUP BY theme ORDER BY count DESC"
    
    elif "show faculty by academic background" in query_lower:
        return "SELECT academic_background, COUNT(*) as count FROM Faculty GROUP BY academic_background ORDER BY count DESC"
    
    elif "display students by personality type" in query_lower:
        return "SELECT personality_type, COUNT(*) as count FROM Students GROUP BY personality_type ORDER BY count DESC"
    
    elif "find books by historical period" in query_lower:
        return "SELECT historical_period, COUNT(*) as count FROM Books GROUP BY historical_period ORDER BY count DESC"
    
    elif "show faculty by professional background" in query_lower:
        return "SELECT professional_background, COUNT(*) as count FROM Faculty GROUP BY professional_background ORDER BY count DESC"
    
    elif "display students by cultural background" in query_lower:
        return "SELECT cultural_background, COUNT(*) as count FROM Students GROUP BY cultural_background ORDER BY count DESC"
    
    elif "find books by geographical setting" in query_lower:
        return "SELECT geographical_setting, COUNT(*) as count FROM Books GROUP BY geographical_setting ORDER BY count DESC"
    
    elif "show faculty by educational philosophy" in query_lower:
        return "SELECT educational_philosophy, COUNT(*) as count FROM Faculty GROUP BY educational_philosophy ORDER BY count DESC"
    
    elif "display students by socioeconomic status" in query_lower:
        return "SELECT socioeconomic_status, COUNT(*) as count FROM Students GROUP BY socioeconomic_status ORDER BY count DESC"
    
    elif "find books by character type" in query_lower:
        return "SELECT character_type, COUNT(*) as count FROM Books GROUP BY character_type ORDER BY count DESC"
    
    elif "show faculty by research philosophy" in query_lower:
        return "SELECT research_philosophy, COUNT(*) as count FROM Faculty GROUP BY research_philosophy ORDER BY count DESC"
    
    elif "display students by family background" in query_lower:
        return "SELECT family_background, COUNT(*) as count FROM Students GROUP BY family_background ORDER BY count DESC"
    
    elif "find books by plot complexity" in query_lower:
        return "SELECT plot_complexity, COUNT(*) as count FROM Books GROUP BY plot_complexity ORDER BY plot_complexity"
    
    elif "show faculty by leadership style" in query_lower:
        return "SELECT leadership_style, COUNT(*) as count FROM Faculty GROUP BY leadership_style ORDER BY count DESC"
    
    elif "display students by work ethic" in query_lower:
        return "SELECT work_ethic_level, COUNT(*) as count FROM Students GROUP BY work_ethic_level ORDER BY count DESC"
    
    elif "find books by emotional content" in query_lower:
        return "SELECT emotional_content, COUNT(*) as count FROM Books GROUP BY emotional_content ORDER BY count DESC"
    
    elif "show faculty by communication style" in query_lower:
        return "SELECT communication_style, COUNT(*) as count FROM Faculty GROUP BY communication_style ORDER BY count DESC"
    
    elif "display students by time management" in query_lower:
        return "SELECT time_management_skill, COUNT(*) as count FROM Students GROUP BY time_management_skill ORDER BY count DESC"
    
    elif "find books by intellectual level" in query_lower:
        return "SELECT intellectual_level, COUNT(*) as count FROM Books GROUP BY intellectual_level ORDER BY intellectual_level"
    
    elif "show faculty by problem-solving approach" in query_lower:
        return "SELECT problem_solving_approach, COUNT(*) as count FROM Faculty GROUP BY problem_solving_approach ORDER BY count DESC"
    
    elif "display students by stress management" in query_lower:
        return "SELECT stress_management_skill, COUNT(*) as count FROM Students GROUP BY stress_management_skill ORDER BY count DESC"
    
    elif "find books by cultural significance" in query_lower:
        return "SELECT cultural_significance, COUNT(*) as count FROM Books GROUP BY cultural_significance ORDER BY count DESC"
    
    elif "show faculty by creativity level" in query_lower:
        return "SELECT creativity_level, COUNT(*) as count FROM Faculty GROUP BY creativity_level ORDER BY count DESC"
    
    elif "display students by adaptability" in query_lower:
        return "SELECT adaptability_level, COUNT(*) as count FROM Students GROUP BY adaptability_level ORDER BY count DESC"
    
    elif "find books by social relevance" in query_lower:
        return "SELECT social_relevance, COUNT(*) as count FROM Books GROUP BY social_relevance ORDER BY count DESC"
    
    elif "show faculty by innovation mindset" in query_lower:
        return "SELECT innovation_mindset, COUNT(*) as count FROM Faculty GROUP BY innovation_mindset ORDER BY count DESC"
    
    elif "display students by critical thinking" in query_lower:
        return "SELECT critical_thinking_skill, COUNT(*) as count FROM Students GROUP BY critical_thinking_skill ORDER BY count DESC"
    
    elif "find books by artistic merit" in query_lower:
        return "SELECT artistic_merit, COUNT(*) as count FROM Books GROUP BY artistic_merit ORDER BY artistic_merit"
    
    elif "show faculty by analytical thinking" in query_lower:
        return "SELECT analytical_thinking_level, COUNT(*) as count FROM Faculty GROUP BY analytical_thinking_level ORDER BY count DESC"
    
    elif "display students by collaboration skills" in query_lower:
        return "SELECT collaboration_skill, COUNT(*) as count FROM Students GROUP BY collaboration_skill ORDER BY count DESC"
    
    elif "find books by educational value" in query_lower:
        return "SELECT educational_value, COUNT(*) as count FROM Books GROUP BY educational_value ORDER BY educational_value"

    elif "find students at risk of failing" in query_lower or "students at risk" in query_lower:
        return "SELECT s.* FROM Students s WHERE s.gpa < 2.0 OR s.academic_warning = TRUE OR s.attendance < 75 ORDER BY s.gpa ASC"
    
    elif "display enrollment statistics" in query_lower or "enrollment statistics" in query_lower:
        return "SELECT d.name, COUNT(s.id) as enrollment, AVG(s.gpa) as avg_gpa FROM Departments d LEFT JOIN Students s ON d.id = s.branch GROUP BY d.id, d.name ORDER BY enrollment DESC"
    
    elif "find faculty with low student ratings" in query_lower or "faculty with low ratings" in query_lower:
        return "SELECT f.*, AVG(r.rating) as avg_rating FROM Faculty f LEFT JOIN FacultyRatings r ON f.id = r.faculty_id GROUP BY f.id, f.name HAVING AVG(r.rating) < 3.0 ORDER BY avg_rating ASC"
    
    elif "show library usage trends" in query_lower or "library usage trends" in query_lower:
        return "SELECT strftime('%Y', i.issue_date) as year, strftime('%m', i.issue_date) as month, COUNT(*) as usage FROM Issued i GROUP BY year, month ORDER BY year DESC, month DESC"
    
    elif "find departments with low enrollment" in query_lower or "departments with low enrollment" in query_lower:
        return "SELECT d.name, COUNT(s.id) as enrollment FROM Departments d LEFT JOIN Students s ON d.id = s.branch GROUP BY d.id, d.name HAVING COUNT(s.id) < 10 ORDER BY enrollment ASC"
    
    elif "show student retention rates" in query_lower or "student retention rates" in query_lower:
        return "SELECT d.name, COUNT(s.id) as enrolled, COUNT(CASE WHEN s.graduation_eligible = TRUE THEN 1 END) as graduated, (CAST(COUNT(CASE WHEN s.graduation_eligible = TRUE THEN 1 END) AS FLOAT) / COUNT(s.id)) * 100 as retention_rate FROM Departments d LEFT JOIN Students s ON d.id = s.branch GROUP BY d.id, d.name"
    
    elif "display faculty publication metrics" in query_lower or "faculty publication metrics" in query_lower:
        return "SELECT f.name, COUNT(p.id) as publications, AVG(p.impact_factor) as avg_impact FROM Faculty f LEFT JOIN Publications p ON f.id = p.faculty_id GROUP BY f.id, f.name ORDER BY publications DESC"
    
    elif "show library collection analysis" in query_lower or "library collection analysis" in query_lower:
        return "SELECT b.category, COUNT(*) as book_count, AVG(b.publish_date) as avg_publish_date FROM Books b GROUP BY b.category ORDER BY book_count DESC"
    
    elif "display department budget reports" in query_lower or "department budget reports" in query_lower:
        return "SELECT d.name, d.budget, d.budget_year, COUNT(s.id) as students, d.budget / COUNT(s.id) as budget_per_student FROM Departments d LEFT JOIN Students s ON d.id = s.branch GROUP BY d.id, d.name ORDER BY d.budget DESC"
    
    elif "find faculty teaching effectiveness" in query_lower or "faculty teaching effectiveness" in query_lower:
        return "SELECT f.name, AVG(r.rating) as avg_rating, COUNT(DISTINCT s.id) as students_taught FROM Faculty f LEFT JOIN FacultyRatings r ON f.id = r.faculty_id LEFT JOIN Students s ON f.department_id = s.branch GROUP BY f.id, f.name ORDER BY avg_rating DESC"
    
    elif "show student success metrics" in query_lower or "student success metrics" in query_lower:
        return "SELECT d.name, AVG(s.gpa) as avg_gpa, COUNT(CASE WHEN s.graduation_eligible = TRUE THEN 1 END) as graduates, COUNT(s.id) as total_students FROM Departments d LEFT JOIN Students s ON d.id = s.branch GROUP BY d.id, d.name ORDER BY avg_gpa DESC"
    
    elif "display library cost analysis" in query_lower or "library cost analysis" in query_lower:
        return "SELECT b.category, COUNT(*) as count, AVG(b.cost) as avg_cost, SUM(b.cost) as total_cost FROM Books b GROUP BY b.category ORDER BY total_cost DESC"
    
    elif "find departments with high dropout rates" in query_lower or "departments with high dropout rates" in query_lower:
        return "SELECT d.name, COUNT(s.id) as total, COUNT(CASE WHEN s.academic_warning = TRUE THEN 1 END) as at_risk, (CAST(COUNT(CASE WHEN s.academic_warning = TRUE THEN 1 END) AS FLOAT) / COUNT(s.id)) * 100 as dropout_rate FROM Departments d LEFT JOIN Students s ON d.id = s.branch GROUP BY d.id, d.name HAVING dropout_rate > 20 ORDER BY dropout_rate DESC"
    
    elif "show faculty research productivity" in query_lower or "faculty research productivity" in query_lower:
        return "SELECT f.name, COUNT(p.id) as publications, SUM(g.amount) as grants, COUNT(DISTINCT p.journal) as journals FROM Faculty f LEFT JOIN Publications p ON f.id = p.faculty_id LEFT JOIN Grants g ON f.id = g.faculty_id GROUP BY f.id, f.name ORDER BY (COUNT(p.id) * 10 + SUM(g.amount)) DESC"
    
    elif "display institutional performance indicators" in query_lower or "institutional performance indicators" in query_lower:
        return "SELECT 'Total Students' as metric, COUNT(*) as value FROM Students UNION ALL SELECT 'Total Faculty', COUNT(*) FROM Faculty UNION ALL SELECT 'Total Books', COUNT(*) FROM Books UNION ALL SELECT 'Avg GPA', AVG(gpa) FROM Students UNION ALL SELECT 'Graduation Rate', (CAST(COUNT(CASE WHEN graduation_eligible = TRUE THEN 1 END) AS FLOAT) / COUNT(*)) * 100 FROM Students"
    elif "display students with highest GPA" in query_lower or "students with highest gpa" in query_lower:
        return "SELECT * FROM Students ORDER BY gpa DESC LIMIT 10"
    
    elif "find faculty with most publications" in query_lower or "faculty with most publications" in query_lower:
        return "SELECT f.*, COUNT(p.id) as publication_count FROM Faculty f LEFT JOIN Publications p ON f.id = p.faculty_id GROUP BY f.id, f.name ORDER BY publication_count DESC"
    
    elif "show departments with highest average GPA" in query_lower or "departments with highest average gpa" in query_lower:
        return "SELECT d.name, AVG(s.gpa) as avg_gpa FROM Departments d JOIN Students s ON d.id = s.branch GROUP BY d.id, d.name ORDER BY avg_gpa DESC"
    
    elif "display students with most library visits" in query_lower or "students with most library visits" in query_lower:
        return "SELECT s.*, COUNT(i.id) as visit_count FROM Students s JOIN Issued i ON s.id = i.student_id GROUP BY s.id, s.name ORDER BY visit_count DESC"
    
    elif "show faculty with most research grants" in query_lower or "faculty with most research grants" in query_lower:
        return "SELECT f.*, COUNT(g.id) as grant_count, SUM(g.amount) as total_grant_amount FROM Faculty f LEFT JOIN Grants g ON f.id = g.faculty_id GROUP BY f.id, f.name ORDER BY grant_count DESC"
    
    elif "show departments with most fines" in query_lower or "departments with most fines" in query_lower:
        return "SELECT d.name, COUNT(f.id) as fine_count, SUM(f.fine_amount) as total_fines FROM Departments d JOIN Students s ON d.id = s.branch JOIN Fines f ON s.id = f.student_id GROUP BY d.id, d.name ORDER BY fine_count DESC"
    
    elif "display students with most course credits" in query_lower or "students with most course credits" in query_lower:
        return "SELECT s.*, SUM(c.credits) as total_credits FROM Students s JOIN CourseEnrollment ce ON s.id = ce.student_id JOIN Courses c ON ce.course_id = c.id GROUP BY s.id, s.name ORDER BY total_credits DESC"
    
    elif "find books with most reservations" in query_lower or "books with most reservations" in query_lower:
        return "SELECT b.*, COUNT(r.id) as reservation_count FROM Books b LEFT JOIN Reservations r ON b.id = r.book_id GROUP BY b.id, b.title ORDER BY reservation_count DESC"
    
    elif "find books with highest demand" in query_lower or "books with highest demand" in query_lower:
        return "SELECT b.*, COUNT(i.id) as issue_count, COUNT(r.id) as reservation_count FROM Books b LEFT JOIN Issued i ON b.id = i.book_id LEFT JOIN Reservations r ON b.id = r.book_id GROUP BY b.id, b.title ORDER BY (issue_count + reservation_count) DESC"
    
    elif "show departments with best graduation rates" in query_lower or "departments with best graduation rates" in query_lower:
        return "SELECT d.name, COUNT(CASE WHEN s.graduation_eligible = TRUE THEN 1 END) as graduates, COUNT(s.id) as total_students, (CAST(COUNT(CASE WHEN s.graduation_eligible = TRUE THEN 1 END) AS FLOAT) / COUNT(s.id)) * 100 as graduation_rate FROM Departments d LEFT JOIN Students s ON d.id = s.branch GROUP BY d.id, d.name ORDER BY graduation_rate DESC"
    
    elif "display students with honors" in query_lower or "students with honors" in query_lower:
        return "SELECT * FROM Students WHERE honors = 'Yes' OR dean_list = 'Yes' ORDER BY gpa DESC"
    
    elif "find books with most copies" in query_lower or "books with most copies" in query_lower:
        return "SELECT * FROM Books ORDER BY copies DESC"
    
    elif "show faculty with most experience" in query_lower or "faculty with most experience" in query_lower:
        return "SELECT * FROM Faculty ORDER BY years_of_service DESC"
    elif "show books published in last 5 years" in query_lower or "books published last 5 years" in query_lower:
        return "SELECT * FROM Books WHERE publish_date >= date('now', '-5 years') ORDER BY publish_date DESC"
    
    elif "display students with birthday this month" in query_lower or "birthday this month" in query_lower:
        return "SELECT * FROM Students WHERE strftime('%m', birthday) = strftime('%m', date('now'))"
    
    elif "find books by author name" in query_lower or "books by author" in query_lower:
        return "SELECT * FROM Books WHERE author IS NOT NULL ORDER BY author, title"
    
    elif "show total books in library" in query_lower or "total books" in query_lower:
        return "SELECT COUNT(*) as total_books FROM Books"
    
    elif "display students with email addresses" in query_lower or "students with email" in query_lower:
        return "SELECT id, name, email FROM Students WHERE email IS NOT NULL ORDER BY name"
    
    elif "find books by ISBN number" in query_lower or "books by isbn" in query_lower:
        return "SELECT * FROM Books WHERE isbn IS NOT NULL ORDER BY isbn"
    
    elif "show faculty office locations" in query_lower or "faculty office locations" in query_lower:
        return "SELECT f.name, f.office_location, f.office_hours FROM Faculty f WHERE f.office_location IS NOT NULL ORDER BY f.name"
    
    elif "display students by graduation year" in query_lower or "students by graduation year" in query_lower:
        return "SELECT graduation_year, COUNT(*) as student_count FROM Students WHERE graduation_year IS NOT NULL GROUP BY graduation_year ORDER BY graduation_year DESC"
    
    elif "find books with multiple authors" in query_lower or "books with multiple authors" in query_lower:
        return "SELECT * FROM Books WHERE author LIKE '%,%' OR author LIKE '%and%' ORDER BY title"
    
    elif "show departments with most students" in query_lower or "departments with most students" in query_lower:
        return "SELECT d.name, COUNT(s.id) as student_count FROM Departments d JOIN Students s ON d.id = s.branch GROUP BY d.id, d.name ORDER BY student_count DESC"
    
    elif "display books by publication year" in query_lower or "books by publication year" in query_lower:
        return "SELECT strftime('%Y', publish_date) as year, COUNT(*) as book_count FROM Books WHERE publish_date IS NOT NULL GROUP BY year ORDER BY year DESC"
    
    elif "find students with phone numbers" in query_lower or "students with phone" in query_lower:
        return "SELECT id, name, phone FROM Students WHERE phone IS NOT NULL ORDER BY name"
    
    elif "show faculty email addresses" in query_lower or "faculty email addresses" in query_lower:
        return "SELECT f.name, f.email FROM Faculty f WHERE f.email IS NOT NULL ORDER BY f.name"
    
    elif "display books by publisher" in query_lower or "books by publisher" in query_lower:
        return "SELECT publisher, COUNT(*) as book_count FROM Books WHERE publisher IS NOT NULL GROUP BY publisher ORDER BY book_count DESC"
    
    elif "find students with addresses" in query_lower or "students with addresses" in query_lower:
        return "SELECT id, name, address FROM Students WHERE address IS NOT NULL ORDER BY name"
    
    elif "show department contact information" in query_lower or "department contact" in query_lower:
        return "SELECT d.name, d.phone, d.email, d.head_of_department FROM Departments d ORDER BY d.name"
    
    elif "display books by language" in query_lower or "books by language" in query_lower:
        return "SELECT language, COUNT(*) as book_count FROM Books WHERE language IS NOT NULL GROUP BY language ORDER BY book_count DESC"
    
    elif "find faculty with office hours" in query_lower or "faculty office hours" in query_lower:
        return "SELECT f.name, f.office_hours, f.office_location FROM Faculty f WHERE f.office_hours IS NOT NULL ORDER BY f.name"
    
    elif "show students enrollment dates" in query_lower or "students enrollment dates" in query_lower:
        return "SELECT id, name, enrollment_date FROM Students WHERE enrollment_date IS NOT NULL ORDER BY enrollment_date DESC"
    
    elif "display books with descriptions" in query_lower or "books with descriptions" in query_lower:
        return "SELECT title, author, description FROM Books WHERE description IS NOT NULL ORDER BY title"
    elif "show my current issued books" in query_lower or "my current books" in query_lower:
        return "SELECT i.*, b.title, b.author, i.due_date FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = [CURRENT_STUDENT_ID] AND i.return_date IS NULL ORDER BY i.due_date ASC"
        return "SELECT i.*, b.title, b.author, i.due_date FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = [CURRENT_STUDENT_ID] AND i.return_date IS NULL ORDER BY i.due_date ASC"
    
    elif "display my borrowing history" in query_lower or "my borrowing history" in query_lower:
        return "SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = [CURRENT_STUDENT_ID] ORDER BY i.issue_date DESC"
    
    elif "find my overdue books" in query_lower or "my overdue books" in query_lower:
        return "SELECT i.*, b.title, b.author, DATEDAY(i.due_date, date('now')) as days_overdue FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = [CURRENT_STUDENT_ID] AND i.return_date IS NULL AND i.due_date < date('now')"
    
    elif "show my fines and payments" in query_lower or "my fines" in query_lower:
        return "SELECT f.*, p.payment_date, p.amount as payment_amount FROM Fines f LEFT JOIN Payments p ON f.id = p.fine_id WHERE f.student_id = [CURRENT_STUDENT_ID] ORDER BY f.issue_date DESC"
    
    elif "display my reservation status" in query_lower or "my reservation" in query_lower:
        return "SELECT r.*, b.title, b.author, r.position_in_queue FROM Reservations r JOIN Books b ON r.book_id = b.id WHERE r.student_id = [CURRENT_STUDENT_ID] ORDER BY r.reservation_date DESC"
    
    elif "find books I can borrow" in query_lower or "books I can borrow" in query_lower:
        return "SELECT b.* FROM Books b WHERE b.id NOT IN (SELECT book_id FROM Issued WHERE student_id = [CURRENT_STUDENT_ID] AND return_date IS NULL) AND b.available_copies > 0 ORDER BY b.title"
    
    elif "show my account details" in query_lower or "my account" in query_lower:
        return "SELECT s.*, d.name as department_name FROM Students s JOIN Departments d ON s.branch = d.id WHERE s.id = [CURRENT_STUDENT_ID]"
    
    elif "display my reading preferences" in query_lower or "my reading preferences" in query_lower:
        return "SELECT b.category, COUNT(*) as borrow_count FROM Books b JOIN Issued i ON b.id = i.book_id WHERE i.student_id = [CURRENT_STUDENT_ID] GROUP BY b.category ORDER BY borrow_count DESC"
    
    elif "find books recommended for me" in query_lower or "recommended for me" in query_lower:
        return "SELECT DISTINCT b.* FROM Books b JOIN Issued i ON b.id = i.book_id JOIN Students s ON i.student_id = s.id WHERE s.branch = (SELECT branch FROM Students WHERE id = [CURRENT_STUDENT_ID]) AND s.id != [CURRENT_STUDENT_ID] AND b.id NOT IN (SELECT book_id FROM Issued WHERE student_id = [CURRENT_STUDENT_ID]) LIMIT 10"
    
    elif "show my library card status" in query_lower or "my library card" in query_lower:
        return "SELECT s.name, s.card_number, s.card_expiry, s.library_privileges, s.borrowing_status FROM Students s WHERE s.id = [CURRENT_STUDENT_ID]"
    
    elif "display my borrowing limits" in query_lower or "my borrowing limits" in query_lower:
        return "SELECT s.borrowing_limit, COUNT(i.id) as current_books, (s.borrowing_limit - COUNT(i.id)) as remaining FROM Students s LEFT JOIN Issued i ON s.id = i.student_id AND i.return_date IS NULL WHERE s.id = [CURRENT_STUDENT_ID] GROUP BY s.id, s.borrowing_limit"
    
    elif "find books due this week" in query_lower or "books due this week" in query_lower:
        return "SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = [CURRENT_STUDENT_ID] AND i.due_date BETWEEN date('now') AND date('now', '+7 days') AND i.return_date IS NULL"
    
    elif "show my academic standing" in query_lower or "my academic standing" in query_lower:
        return "SELECT s.gpa, s.attendance, s.academic_warning, s.honors, s.dean_list FROM Students s WHERE s.id = [CURRENT_STUDENT_ID]"
    
    elif "display my course materials" in query_lower or "my course materials" in query_lower:
        return "SELECT b.title, b.author, c.course_code, c.course_name FROM Books b JOIN CourseMaterials cm ON b.id = cm.book_id JOIN Courses c ON cm.course_id = c.id JOIN CourseEnrollment ce ON c.id = ce.course_id WHERE ce.student_id = [CURRENT_STUDENT_ID]"
    
    elif "find books in my major" in query_lower or "books in my major" in query_lower:
        return "SELECT b.* FROM Books b JOIN Students s ON b.department_id = s.branch WHERE s.id = [CURRENT_STUDENT_ID] AND b.available_copies > 0 ORDER BY b.title"
    
    elif "show my attendance record" in query_lower or "my attendance" in query_lower:
        return "SELECT s.attendance, s.attendance_rate, s.absences FROM Students s WHERE s.id = [CURRENT_STUDENT_ID]"
    
    elif "display my gpa and grades" in query_lower or "my gpa" in query_lower:
        return "SELECT s.gpa, s.major_gpa, s.semester_gpa, s.class_rank FROM Students s WHERE s.id = [CURRENT_STUDENT_ID]"
    
    elif "find books for my assignments" in query_lower or "books for my assignments" in query_lower:
        return "SELECT b.title, b.author, a.assignment_title, a.due_date FROM Books b JOIN AssignmentBooks ab ON b.id = ab.book_id JOIN Assignments a ON ab.assignment_id = a.id JOIN CourseEnrollment ce ON a.course_id = ce.course_id WHERE ce.student_id = [CURRENT_STUDENT_ID] AND a.due_date >= date('now')"
    
    elif "show my graduation progress" in query_lower or "my graduation progress" in query_lower:
        return "SELECT s.credits_earned, s.credits_required, (s.credits_required - s.credits_earned) as credits_remaining, s.gpa, s.graduation_eligible FROM Students s WHERE s.id = [CURRENT_STUDENT_ID]"
    
    elif "display my scholarship status" in query_lower or "my scholarship" in query_lower:
        return "SELECT s.*, sch.type, sch.amount, sch.renewal_date, sch.requirements FROM Students s JOIN Scholarships sch ON s.id = sch.student_id WHERE s.id = [CURRENT_STUDENT_ID]"
    elif "show faculty with highest student ratings" in query_lower or "faculty ratings" in query_lower:
        return "SELECT f.name, AVG(r.rating) as avg_rating, COUNT(r.id) as rating_count FROM Faculty f JOIN FacultyRatings r ON f.id = r.faculty_id GROUP BY f.id, f.name ORDER BY avg_rating DESC, rating_count DESC"
    
    elif "display departments with lowest fine rates" in query_lower or "lowest fine rates" in query_lower:
        return "SELECT d.name, AVG(f.fine_amount) as avg_fine, COUNT(f.id) as fine_count FROM Departments d JOIN Students s ON d.id = s.branch JOIN Fines f ON s.id = f.student_id GROUP BY d.id, d.name ORDER BY avg_fine ASC"
    
    elif "find students with library membership expiration" in query_lower or "membership expiration" in query_lower:
        return "SELECT s.* FROM Students s WHERE s.membership_expiry <= date('now', '+30 days')"
    
    elif "show books with most recent acquisitions" in query_lower or "recent acquisitions" in query_lower:
        return "SELECT * FROM Books ORDER BY acquisition_date DESC LIMIT 20"
    
    elif "display faculty teaching load analysis" in query_lower or "teaching load" in query_lower:
        return "SELECT f.name, COUNT(c.id) as courses, SUM(c.credits) as total_credits, COUNT(DISTINCT s.id) as students FROM Faculty f JOIN Courses c ON f.id = c.faculty_id JOIN CourseEnrollment ce ON c.id = ce.course_id JOIN Students s ON ce.student_id = s.id GROUP BY f.id, f.name ORDER BY courses DESC"
    
    elif "find students with academic warnings" in query_lower or "academic warnings" in query_lower:
        return "SELECT * FROM Students WHERE academic_warning = TRUE OR gpa < 2.0"
    
    elif "show departments by book circulation" in query_lower or "book circulation" in query_lower:
        return "SELECT d.name, COUNT(i.id) as circulation_count FROM Departments d JOIN Students s ON d.id = s.branch JOIN Issued i ON s.id = i.student_id GROUP BY d.id, d.name ORDER BY circulation_count DESC"
    
    elif "display faculty research funding analysis" in query_lower or "research funding" in query_lower:
        return "SELECT f.name, SUM(g.amount) as total_funding, COUNT(g.id) as grant_count FROM Faculty f JOIN Grants g ON f.id = g.faculty_id GROUP BY f.id, f.name ORDER BY total_funding DESC"
    
    elif "find students with graduation requirements" in query_lower or "graduation requirements" in query_lower:
        return "SELECT s.* FROM Students s WHERE s.credits_earned < s.credits_required OR s.gpa < 2.0"
    
    elif "show books by acquisition source" in query_lower or "acquisition source" in query_lower:
        return "SELECT acquisition_source, COUNT(*) as book_count, AVG(cost) as avg_cost FROM Books GROUP BY acquisition_source ORDER BY book_count DESC"
    
    elif "display department budget allocation" in query_lower or "budget allocation" in query_lower:
        return "SELECT d.name, d.budget, d.budget_year, COUNT(s.id) as student_count FROM Departments d LEFT JOIN Students s ON d.id = s.branch GROUP BY d.id, d.name ORDER BY d.budget DESC"
    
    elif "find students with library privileges" in query_lower or "library privileges" in query_lower:
        return "SELECT s.* FROM Students s WHERE s.library_privileges = TRUE"
    
    elif "show faculty publication impact factor" in query_lower or "impact factor" in query_lower:
        return "SELECT f.name, COUNT(p.id) as publications, AVG(p.impact_factor) as avg_impact FROM Faculty f JOIN Publications p ON f.id = p.faculty_id GROUP BY f.id, f.name ORDER BY avg_impact DESC"
    
    elif "display student enrollment trends" in query_lower or "enrollment trends" in query_lower:
        return "SELECT strftime('%Y', enrollment_date) as year, COUNT(*) as enrollment_count FROM Students GROUP BY year ORDER BY year DESC"
    
    elif "find books with special collections" in query_lower or "special collections" in query_lower:
        return "SELECT * FROM Books WHERE special_collection = 'Yes'"
    
    elif "show department performance metrics" in query_lower or "performance metrics" in query_lower:
        return "SELECT d.name, COUNT(s.id) as students, AVG(s.gpa) as avg_gpa, COUNT(f.id) as fines, SUM(f.fine_amount) as total_fines FROM Departments d LEFT JOIN Students s ON d.id = s.branch LEFT JOIN Fines f ON s.id = f.student_id GROUP BY d.id, d.name ORDER BY avg_gpa DESC"
    
    elif "display faculty grant recipients" in query_lower or "grant recipients" in query_lower:
        return "SELECT f.*, g.title, g.amount, g.award_date FROM Faculty f JOIN Grants g ON f.id = g.faculty_id ORDER BY g.amount DESC"
    
    elif "find students with honors status" in query_lower or "honors status" in query_lower:
        return "SELECT * FROM Students WHERE honors = 'Yes' OR dean_list = 'Yes'"
    
    elif "show library usage by time slot" in query_lower or "usage by time slot" in query_lower:
        return "SELECT strftime('%H', i.issue_date) as hour, COUNT(*) as activity FROM Issued i GROUP BY hour ORDER BY activity DESC"
    
    # LIBRARY OPERATIONS PATTERNS
    elif "show books with high demand alerts" in query_lower or "high demand alerts" in query_lower:
        return "SELECT b.title, COUNT(r.id) as reservation_count FROM Books b JOIN Reservations r ON b.id = r.book_id WHERE r.status = 'Waiting' GROUP BY b.id, b.title HAVING COUNT(r.id) > 3 ORDER BY reservation_count DESC"
    
    elif "display student borrowing limits" in query_lower or "borrowing limits" in query_lower:
        return "SELECT s.name, s.borrowing_limit, COUNT(i.id) as current_books FROM Students s LEFT JOIN Issued i ON s.id = i.student_id AND i.return_date IS NULL GROUP BY s.id, s.name ORDER BY current_books DESC"
    
    elif "find books with restricted access" in query_lower or "restricted access" in query_lower:
        return "SELECT * FROM Books WHERE access_level = 'Restricted' OR special_permission = 'Yes'"
    
    elif "show inter-library loan requests" in query_lower or "inter-library loan" in query_lower:
        return "SELECT ill.*, b.title, s.name as student_name FROM InterLibraryLoans ill JOIN Books b ON ill.book_id = b.id JOIN Students s ON ill.student_id = s.id ORDER BY ill.request_date DESC"
    
    elif "display book renewal statistics" in query_lower or "renewal statistics" in query_lower:
        return "SELECT b.title, COUNT(r.id) as renewal_count FROM Books b JOIN Renewals r ON b.id = r.book_id GROUP BY b.id, b.title ORDER BY renewal_count DESC"
    
    elif "find students with borrowing restrictions" in query_lower or "borrowing restrictions" in query_lower:
        return "SELECT s.* FROM Students s WHERE s.borrowing_status = 'Restricted' OR s.fines_unpaid > 100"
    
    elif "show books in preservation program" in query_lower or "preservation program" in query_lower:
        return "SELECT * FROM Books WHERE preservation_status = 'In Progress' OR preservation_status = 'Completed'"
    
    elif "display library card expiration notices" in query_lower or "card expiration" in query_lower:
        return "SELECT s.* FROM Students s WHERE s.card_expiry <= date('now', '+30 days') AND s.card_expiry >= date('now')"
    
    elif "find books with special permissions" in query_lower or "special permissions" in query_lower:
        return "SELECT sp.*, b.title, s.name as student_name FROM SpecialPermissions sp JOIN Books b ON sp.book_id = b.id JOIN Students s ON sp.student_id = s.id ORDER BY sp.granted_date DESC"
    
    elif "show student overdue notifications" in query_lower or "overdue notifications" in query_lower:
        return "SELECT s.name, COUNT(i.id) as overdue_count FROM Students s JOIN Issued i ON s.id = i.student_id WHERE i.return_date IS NULL AND i.due_date < date('now') GROUP BY s.id, s.name ORDER BY overdue_count DESC"
    
    elif "display book condition monitoring" in query_lower or "condition monitoring" in query_lower:
        return "SELECT b.title, i.condition, COUNT(*) as count FROM Books b JOIN Issued i ON b.id = i.book_id GROUP BY b.id, b.title, i.condition ORDER BY b.title, count DESC"
    
    elif "find students with borrowing privileges" in query_lower or "borrowing privileges" in query_lower:
        return "SELECT s.* FROM Students s WHERE s.borrowing_status = 'Active' AND s.library_privileges = TRUE"
    
    elif "show books in digital collection" in query_lower or "digital collection" in query_lower:
        return "SELECT * FROM Books WHERE digital_available = 'Yes'"
    
    elif "display library hour adjustments" in query_lower or "hour adjustments" in query_lower:
        return "SELECT * FROM LibraryHours WHERE adjustment_date >= date('now', '-30 days') ORDER BY adjustment_date DESC"
    
    elif "find books with reservation priorities" in query_lower or "reservation priorities" in query_lower:
        return "SELECT r.*, b.title, s.name as student_name FROM Reservations r JOIN Books b ON r.book_id = b.id JOIN Students s ON r.student_id = s.id WHERE r.priority IN ('High', 'Urgent') ORDER BY r.priority DESC, r.reservation_date"
    
    elif "show student account holds" in query_lower or "account holds" in query_lower:
        return "SELECT s.* FROM Students s WHERE s.account_status = 'Hold' OR s.fines_unpaid > 0"
    
    elif "display book acquisition requests" in query_lower or "acquisition requests" in query_lower:
        return "SELECT ar.*, b.title as suggested_title FROM AcquisitionRequests ar LEFT JOIN Books b ON ar.isbn = b.isbn ORDER BY ar.request_date DESC"
    
    elif "find books with circulation restrictions" in query_lower or "circulation restrictions" in query_lower:
        return "SELECT * FROM Books WHERE circulation_status = 'Restricted' OR reference_only = 'Yes'"
    
    elif "show library event attendance" in query_lower or "event attendance" in query_lower:
        return "SELECT e.title, COUNT(ea.id) as attendance_count, e.event_date FROM Events e LEFT JOIN EventAttendance ea ON e.id = ea.event_id GROUP BY e.id, e.title ORDER BY e.event_date DESC"
    elif "show students with GPA above 3.8 and no fines" in query_lower or "GPA above 3.8" in query_lower and "no fines" in query_lower:
        return "SELECT s.* FROM Students s WHERE s.gpa > 3.8 AND s.id NOT IN (SELECT DISTINCT student_id FROM Fines)"
    
    elif "find books published after 2015 with more than 5 copies" in query_lower or "more than 5 copies" in query_lower:
        return "SELECT * FROM Books WHERE publish_date > '2015-01-01' AND copies > 5"
    
    elif "display faculty with PhD and more than 20 publications" in query_lower or "faculty with PhD" in query_lower:
        return "SELECT f.* FROM Faculty f WHERE f.qualification = 'PhD' AND f.id IN (SELECT faculty_id FROM Publications GROUP BY faculty_id HAVING COUNT(*) > 20)"
    
    elif "show students who borrowed books during holidays" in query_lower or "holidays" in query_lower:
        return "SELECT DISTINCT s.* FROM Students s JOIN Issued i ON s.id = i.student_id WHERE strftime('%m', i.issue_date) IN ('12', '01', '07', '08')"
    
    elif "find books with overdue rate above 50%" in query_lower or "overdue rate above" in query_lower:
        return "SELECT b.title, (CAST(COUNT(CASE WHEN i.return_date > i.due_date THEN 1 END) AS FLOAT) / COUNT(i.id)) * 100 as overdue_rate FROM Books b JOIN Issued i ON b.id = i.book_id GROUP BY b.id, b.title HAVING (CAST(COUNT(CASE WHEN i.return_date > i.due_date THEN 1 END) AS FLOAT) / COUNT(i.id)) > 0.5"
    
    elif "display departments with average gpa above 3.5" in query_lower or "average gpa above" in query_lower:
        return "SELECT d.name, AVG(s.gpa) as avg_gpa FROM Departments d JOIN Students s ON d.id = s.branch GROUP BY d.id, d.name HAVING AVG(s.gpa) > 3.5 ORDER BY avg_gpa DESC"
    
    elif "show students with scholarship and volunteer hours" in query_lower or "scholarship and volunteer" in query_lower:
        return "SELECT s.*, sch.type, sch.amount, v.hours_completed FROM Students s JOIN Scholarships sch ON s.id = sch.student_id JOIN VolunteerHours v ON s.id = v.student_id WHERE v.hours_completed > 0"
    
    elif "find books borrowed by multiple departments" in query_lower or "multiple departments" in query_lower:
        return "SELECT b.title, COUNT(DISTINCT s.branch) as dept_count FROM Books b JOIN Issued i ON b.id = i.book_id JOIN Students s ON i.student_id = s.id GROUP BY b.id, b.title HAVING COUNT(DISTINCT s.branch) > 1 ORDER BY dept_count DESC"
    
    elif "display late return patterns by department" in query_lower or "late return by department" in query_lower:
        return "SELECT d.name, COUNT(CASE WHEN i.return_date > i.due_date THEN 1 END) as late_returns, COUNT(i.id) as total_issued FROM Departments d JOIN Students s ON d.id = s.branch JOIN Issued i ON s.id = i.student_id GROUP BY d.id, d.name ORDER BY late_returns DESC"
    
    elif "show students with perfect attendance and high GPA" in query_lower or "perfect attendance and high GPA" in query_lower:
        return "SELECT * FROM Students WHERE attendance = 100 AND gpa > 3.5"
    
    elif "find books with reservation queue longer than 5" in query_lower or "queue longer than" in query_lower:
        return "SELECT b.title, COUNT(r.id) as queue_length FROM Books b JOIN Reservations r ON b.id = r.book_id WHERE r.status = 'Waiting' GROUP BY b.id, b.title HAVING COUNT(r.id) > 5 ORDER BY queue_length DESC"
    
    elif "display faculty teaching multiple courses" in query_lower or "teaching multiple courses" in query_lower:
        return "SELECT f.*, COUNT(c.id) as course_count FROM Faculty f JOIN Courses c ON f.id = c.faculty_id GROUP BY f.id, f.name HAVING COUNT(c.id) > 1 ORDER BY course_count DESC"
    
    elif "show students with fines from different departments" in query_lower or "fines from different departments" in query_lower:
        return "SELECT s.name, COUNT(DISTINCT d.id) as dept_count FROM Students s JOIN Fines f ON s.id = f.student_id JOIN Issued i ON f.student_id = i.student_id JOIN Books b ON i.book_id = b.id JOIN Departments d ON b.department_id = d.id GROUP BY s.id, s.name HAVING COUNT(DISTINCT d.id) > 1"
    
    elif "find books issued during exam periods" in query_lower or "exam periods" in query_lower:
        return "SELECT b.title, COUNT(i.id) as exam_issues FROM Books b JOIN Issued i ON b.id = i.book_id WHERE strftime('%m', i.issue_date) IN ('04', '05', '11', '12') GROUP BY b.id, b.title ORDER BY exam_issues DESC"
    
    elif "display weekend vs weekday borrowing comparison" in query_lower or "weekend vs weekday" in query_lower:
        return "SELECT CASE WHEN strftime('%w', i.issue_date) IN ('0', '6') THEN 'Weekend' ELSE 'Weekday' END as day_type, COUNT(*) as borrow_count FROM Issued i GROUP BY day_type ORDER BY borrow_count DESC"
    
    elif "show students with multiple academic achievements" in query_lower or "academic achievements" in query_lower:
        return "SELECT s.* FROM Students s WHERE (s.gpa > 3.5 AND s.attendance > 95) OR (s.scholarship = 'Yes' AND s.volunteer_hours > 50)"
    
    elif "find books with condition degradation over time" in query_lower or "condition degradation" in query_lower:
        return "SELECT b.title, i.condition, i.issue_date FROM Books b JOIN Issued i ON b.id = i.book_id WHERE i.condition IN ('Poor', 'Damaged') ORDER BY i.issue_date DESC"
    
    elif "display faculty workload by semester" in query_lower or "workload by semester" in query_lower:
        return "SELECT f.name, CASE WHEN strftime('%m', c.start_date) IN ('01', '02', '03', '04', '05', '06') THEN 'Spring' ELSE 'Fall' END as semester, COUNT(c.id) as course_count FROM Faculty f JOIN Courses c ON f.id = c.faculty_id GROUP BY f.id, f.name, semester ORDER BY semester, course_count DESC"
    
    elif "show students with cross-department borrowing patterns" in query_lower or "cross-department borrowing" in query_lower:
        return "SELECT s.name, COUNT(DISTINCT d.id) as dept_diversity FROM Students s JOIN Issued i ON s.id = i.student_id JOIN Books b ON i.book_id = b.id JOIN Departments d ON b.department_id = d.id GROUP BY s.id, s.name HAVING COUNT(DISTINCT d.id) > 2 ORDER BY dept_diversity DESC"
    elif "show students who borrowed books during exam week" in query_lower or "exam week" in query_lower:
        return "SELECT DISTINCT s.* FROM Students s JOIN Issued i ON s.id = i.student_id WHERE i.issue_date BETWEEN date('now', '-30 days') AND date('now', '-23 days')"
    
    elif "find books with highest damage rates" in query_lower or "books with damage" in query_lower:
        return "SELECT b.title, COUNT(CASE WHEN i.condition = 'Damaged' THEN 1 END) as damage_count, COUNT(i.id) as total_issued FROM Books b LEFT JOIN Issued i ON b.id = i.book_id GROUP BY b.id, b.title HAVING COUNT(i.id) > 0 ORDER BY (CAST(damage_count AS FLOAT) / total_issued) DESC"
    
    elif "display faculty with research publications" in query_lower or "faculty research" in query_lower:
        return "SELECT f.name, f.email, COUNT(p.id) as publication_count FROM Faculty f LEFT JOIN Publications p ON f.id = p.faculty_id GROUP BY f.id, f.name, f.email ORDER BY publication_count DESC"
    
    elif "show students with scholarship information" in query_lower or "students with scholarship" in query_lower:
        return "SELECT s.*, sch.type, sch.amount, sch.award_date FROM Students s LEFT JOIN Scholarships sch ON s.id = sch.student_id WHERE sch.id IS NOT NULL"
    
    elif "find books that are always overdue" in query_lower or "always overdue books" in query_lower:
        return "SELECT b.title FROM Books b WHERE NOT EXISTS (SELECT 1 FROM Issued i WHERE i.book_id = b.id AND i.return_date <= i.due_date)"
    
    elif "display weekend borrowing patterns" in query_lower or "weekend borrowing" in query_lower:
        return "SELECT strftime('%w', i.issue_date) as day_of_week, COUNT(*) as borrow_count FROM Issued i WHERE strftime('%w', i.issue_date) IN ('0', '6') GROUP BY strftime('%w', i.issue_date) ORDER BY borrow_count DESC"
    
    elif "show students with part-time jobs" in query_lower or "students part-time" in query_lower:
        return "SELECT s.* FROM Students s WHERE s.employment_status = 'Part-time'"
    
    elif "find books by publication decade" in query_lower or "books by decade" in query_lower:
        return "SELECT SUBSTR(publish_date, 1, 3) || '0s' as decade, COUNT(*) as book_count FROM Books WHERE publish_date IS NOT NULL GROUP BY SUBSTR(publish_date, 1, 3) || '0s' ORDER BY decade"
    
    elif "display late return patterns by month" in query_lower or "late return patterns" in query_lower:
        return "SELECT strftime('%Y-%m', i.return_date) as month, COUNT(*) as late_returns FROM Issued i WHERE i.return_date > i.due_date GROUP BY strftime('%Y-%m', i.return_date) ORDER BY month DESC"
    
    elif "show students with multiple majors" in query_lower or "students multiple majors" in query_lower:
        return "SELECT s.* FROM Students s WHERE s.major2 IS NOT NULL OR s.major3 IS NOT NULL"
    
    elif "find books with reservation waiting lists" in query_lower or "reservation waiting lists" in query_lower:
        return "SELECT b.title, COUNT(r.id) as waiting_count FROM Books b JOIN Reservations r ON b.id = r.book_id WHERE r.status = 'Waiting' GROUP BY b.id, b.title HAVING COUNT(r.id) > 0 ORDER BY waiting_count DESC"
    
    elif "display fine payment methods analysis" in query_lower or "fine payment methods" in query_lower:
        return "SELECT payment_method, COUNT(*) as count, SUM(fine_amount) as total_amount FROM Fines WHERE payment_method IS NOT NULL GROUP BY payment_method ORDER BY total_amount DESC"
    
    elif "show peak library hours usage" in query_lower or "peak library hours" in query_lower:
        return "SELECT strftime('%H', i.issue_date) as hour, COUNT(*) as activity_count FROM Issued i GROUP BY strftime('%H', i.issue_date) ORDER BY activity_count DESC LIMIT 5"
    
    elif "find students with library volunteer hours" in query_lower or "volunteer hours" in query_lower:
        return "SELECT s.*, v.hours_completed, v.activity_type FROM Students s JOIN VolunteerHours v ON s.id = v.student_id WHERE v.hours_completed > 0 ORDER BY v.hours_completed DESC"
    
    elif "display book condition reports" in query_lower or "book condition" in query_lower:
        return "SELECT b.title, i.condition, COUNT(*) as count FROM Books b JOIN Issued i ON b.id = i.book_id GROUP BY b.id, b.title, i.condition ORDER BY b.title, count DESC"
    
    elif "show inter-department book requests" in query_lower or "inter-department requests" in query_lower:
        return "SELECT s.name as student_name, d1.name as student_dept, d2.name as book_dept, b.title FROM Students s JOIN Departments d1 ON s.branch = d1.id JOIN Issued i ON s.id = i.student_id JOIN Books b ON i.book_id = b.id JOIN Departments d2 ON b.department_id = d2.id WHERE d1.id != d2.id"
    
    elif "find students with academic probation status" in query_lower or "academic probation" in query_lower:
        return "SELECT * FROM Students WHERE academic_probation = TRUE"
    
    elif "display seasonal borrowing trends" in query_lower or "seasonal borrowing" in query_lower:
        return "SELECT CASE WHEN strftime('%m', i.issue_date) IN ('12', '01', '02') THEN 'Winter' WHEN strftime('%m', i.issue_date) IN ('03', '04', '05') THEN 'Spring' WHEN strftime('%m', i.issue_date) IN ('06', '07', '08') THEN 'Summer' ELSE 'Fall' END as season, COUNT(*) as borrow_count FROM Issued i GROUP BY season ORDER BY borrow_count DESC"
    
    elif "show books with multiple language editions" in query_lower or "multiple language editions" in query_lower:
        return "SELECT title, GROUP_CONCAT(DISTINCT language) as languages FROM Books WHERE language IS NOT NULL GROUP BY title HAVING COUNT(DISTINCT language) > 1 ORDER BY title"
    elif "show departments with no students" in query_lower or "departments with no students" in query_lower:
        return "SELECT d.* FROM Departments d LEFT JOIN Students s ON d.id = s.branch WHERE s.id IS NULL"
    
    elif "list faculty with more than 10 students" in query_lower or "faculty with more than" in query_lower and "students" in query_lower:
        return "SELECT f.name, f.email, COUNT(DISTINCT s.id) as student_count FROM Faculty f JOIN Students s ON f.department_id = s.branch GROUP BY f.id, f.name, f.email HAVING COUNT(DISTINCT s.id) > 10 ORDER BY student_count DESC"
    
    elif "find most expensive fines" in query_lower or "most expensive fines" in query_lower or "highest fines" in query_lower:
        return "SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id ORDER BY f.fine_amount DESC LIMIT 10"
    
    elif "show books due next week" in query_lower or "books due next week" in query_lower:
        return "SELECT i.*, b.title, s.name as student_name FROM Issued i JOIN Books b ON i.book_id = b.id JOIN Students s ON i.student_id = s.id WHERE i.due_date BETWEEN date('now') AND date('now', '+7 days') AND i.return_date IS NULL"
    
    elif "show books with highest overdue rates" in query_lower or "books with highest overdue rates" in query_lower:
        return "SELECT b.title, COUNT(CASE WHEN i.return_date > i.due_date THEN 1 END) as overdue_count, COUNT(i.id) as total_issued FROM Books b LEFT JOIN Issued i ON b.id = i.book_id GROUP BY b.id, b.title HAVING COUNT(i.id) > 0 ORDER BY (CAST(overdue_count AS FLOAT) / total_issued) DESC"
    
    elif "find students who borrowed books in multiple departments" in query_lower or "students borrowed books multiple departments" in query_lower:
        return "SELECT s.name, COUNT(DISTINCT d.id) as dept_count FROM Students s JOIN Issued i ON s.id = i.student_id JOIN Books b ON i.book_id = b.id JOIN Departments d ON b.department_id = d.id GROUP BY s.id, s.name HAVING COUNT(DISTINCT d.id) > 1"
    
    elif "show librarians with most transactions" in query_lower or "librarians with most transactions" in query_lower:
        return "SELECT u.username, COUNT(q.id) as transaction_count FROM Users u JOIN QueryHistory q ON u.username = q.user_query WHERE u.role = 'Librarian' GROUP BY u.id, u.username ORDER BY transaction_count DESC"
    
    elif "find books with longest average borrowing period" in query_lower or "books with longest borrowing period" in query_lower:
        return "SELECT b.title, AVG(julianday(i.return_date) - julianday(i.issue_date)) as avg_days FROM Books b JOIN Issued i ON b.id = i.book_id WHERE i.return_date IS NOT NULL GROUP BY b.id, b.title HAVING COUNT(i.id) > 2 ORDER BY avg_days DESC"
    
    elif "list students with no fines ever" in query_lower or "students with no fines" in query_lower:
        return "SELECT s.* FROM Students s WHERE s.id NOT IN (SELECT DISTINCT student_id FROM Fines)"
    
    elif "show departments by fine collection" in query_lower or "departments by fine collection" in query_lower:
        return "SELECT d.name, SUM(f.fine_amount) as total_fines, COUNT(f.id) as fine_count FROM Departments d JOIN Students s ON d.id = s.branch JOIN Fines f ON s.id = f.student_id GROUP BY d.id, d.name ORDER BY total_fines DESC"
    
    # STUDENT PERFORMANCE PATTERNS
    elif "show students with GPA above" in query_lower or "students with GPA" in query_lower:
        if "3.5" in query_lower:
            return "SELECT * FROM Students WHERE gpa > 3.5"
        else:
            return "SELECT * FROM Students WHERE gpa > 3.0"
    
    elif "show students with perfect attendance" in query_lower or "students with perfect attendance" in query_lower:
        return "SELECT * FROM Students WHERE attendance = 100"
    
    # BOOK ANALYTICS PATTERNS
    elif "find books published after" in query_lower or "books published after" in query_lower:
        if "2020" in query_lower:
            return "SELECT * FROM Books WHERE publish_date > '2020-01-01'"
        else:
            return "SELECT * FROM Books WHERE publish_date > '2019-01-01'"
    
    elif "display fines issued in last 30 days" in query_lower or "fines last 30 days" in query_lower:
        return "SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id WHERE f.issue_date >= date('now', '-30 days') ORDER BY f.issue_date DESC"
    
    elif "display average fine per department" in query_lower or "average fine per department" in query_lower:
        return "SELECT d.name, AVG(f.fine_amount) as avg_fine, COUNT(f.id) as fine_count FROM Departments d JOIN Students s ON d.id = s.branch JOIN Fines f ON s.id = f.student_id GROUP BY d.id, d.name ORDER BY avg_fine DESC"
    elif "find students who never borrowed books" in query_lower or "students never borrowed books" in query_lower:
        return "SELECT * FROM Students WHERE id NOT IN (SELECT DISTINCT student_id FROM Issued)"
    
    elif "show most popular books" in query_lower or "popular books" in query_lower:
        return "SELECT b.title, COUNT(i.id) as issue_count FROM Books b JOIN Issued i ON b.id = i.book_id GROUP BY b.id, b.title ORDER BY issue_count DESC LIMIT 10"
    
    elif "display faculty workload" in query_lower or "faculty workload" in query_lower:
        return "SELECT f.name, f.email, COUNT(DISTINCT s.id) as student_count FROM Faculty f JOIN Students s ON f.department_id = s.branch GROUP BY f.id, f.name ORDER BY student_count DESC"
    elif "students with unpaid fines" in query_lower:
        return "SELECT DISTINCT s.* FROM Students s JOIN Fines f ON s.id = f.student_id WHERE f.status = 'Unpaid'"
    
    elif "students with fines" in query_lower:
        return "SELECT DISTINCT s.* FROM Students s JOIN Fines f ON s.id = f.student_id"
    
    elif "unpaid fines" in query_lower:
        return "SELECT * FROM Fines WHERE status = 'Unpaid'"
    
    # NESTED QUERIES - Multi-table complex conditions
    elif "borrowed books from" in query_lower and "category" in query_lower:
        if "computer science" in query_lower:
            return "SELECT DISTINCT s.* FROM Students s JOIN Issued i ON s.id = i.student_id JOIN Books b ON i.book_id = b.id WHERE b.category = 'Computer Science'"
        else:
            return "SELECT DISTINCT s.*, b.category FROM Students s JOIN Issued i ON s.id = i.student_id JOIN Books b ON i.book_id = b.id GROUP BY s.id, b.category"
    
    elif "fines but have never returned" in query_lower:
        return "SELECT s.* FROM Students s JOIN Fines f ON s.id = f.student_id WHERE s.id NOT IN (SELECT DISTINCT i.student_id FROM Issued i WHERE i.return_date > i.due_date)"
    
    elif "popular among students with" in query_lower and "gpa" in query_lower:
        return "SELECT b.title, COUNT(i.id) as issue_count, AVG(s.gpa) as avg_gpa FROM Books b JOIN Issued i ON b.id = i.book_id JOIN Students s ON i.student_id = s.id WHERE s.gpa > 3.5 GROUP BY b.id, b.title ORDER BY issue_count DESC"
    
    elif "more books than average" in query_lower:
        return "SELECT s.name, COUNT(i.id) as books_borrowed FROM Students s JOIN Issued i ON s.id = i.student_id GROUP BY s.id, s.name HAVING COUNT(i.id) > (SELECT AVG(book_count) FROM (SELECT COUNT(*) as book_count FROM Issued GROUP BY student_id))"
    
    elif "never been borrowed by students with" in query_lower and "unpaid fines" in query_lower:
        return "SELECT b.* FROM Books b WHERE b.id NOT IN (SELECT DISTINCT i.book_id FROM Issued i JOIN Students s ON i.student_id = s.id JOIN Fines f ON s.id = f.student_id WHERE f.status = 'Unpaid')"
    
    elif "fines from multiple different" in query_lower and "fine types" in query_lower:
        return "SELECT s.name, COUNT(DISTINCT f.fine_type) as fine_type_count FROM Students s JOIN Fines f ON s.id = f.student_id GROUP BY s.id, s.name HAVING COUNT(DISTINCT f.fine_type) > 1"
    
    elif "frequently issued but have high fine rates" in query_lower:
        return "SELECT b.title, COUNT(i.id) as issue_count, AVG(f.fine_amount) as avg_fine FROM Books b LEFT JOIN Issued i ON b.id = i.book_id LEFT JOIN Fines f ON i.student_id = f.student_id GROUP BY b.id, b.title HAVING COUNT(i.id) > 5 ORDER BY avg_fine DESC"
    
    elif "borrowed books in multiple categories" in query_lower:
        return "SELECT s.name, COUNT(DISTINCT b.category) as category_count FROM Students s JOIN Issued i ON s.id = i.student_id JOIN Books b ON i.book_id = b.id GROUP BY s.id, s.name HAVING COUNT(DISTINCT b.category) > 1"
    
    elif "only borrowed by students from" in query_lower and "branches" in query_lower:
        return "SELECT b.title, s.branch FROM Books b JOIN Issued i ON b.id = i.book_id JOIN Students s ON i.student_id = s.id GROUP BY b.id, s.branch HAVING COUNT(DISTINCT s.branch) = 1"
    
    elif "perfect attendance but have outstanding fines" in query_lower:
        return "SELECT s.* FROM Students s JOIN Fines f ON s.id = f.student_id WHERE s.attendance = 100 AND f.status = 'Unpaid'"
    
    # COUNT queries
    elif "count" in query_lower:
        if "books" in query_lower and "category" in query_lower:
            return "SELECT category, COUNT(*) as book_count FROM Books GROUP BY category ORDER BY book_count DESC"
        elif "students" in query_lower:
            return "SELECT COUNT(*) as total_students FROM Students"
    
    # TOTAL/SUM queries
    elif "total" in query_lower and "fines" in query_lower:
        if "student" in query_lower:
            return "SELECT s.name, SUM(f.fine_amount) as total_fines FROM Students s JOIN Fines f ON s.id = f.student_id GROUP BY s.id, s.name ORDER BY total_fines DESC"
        else:
            return "SELECT SUM(fine_amount) as total_fines FROM Fines"
    
    # AVERAGE queries
    elif "average" in query_lower and "fine" in query_lower:
        return "SELECT AVG(fine_amount) as average_fine FROM Fines"
    
    # MORE THAN queries
    elif "more than" in query_lower:
        if "books" in query_lower and "5" in query_lower:
            return "SELECT s.name, COUNT(i.id) as books_borrowed FROM Students s JOIN Issued i ON s.id = i.student_id GROUP BY s.id, s.name HAVING COUNT(i.id) > 5"
        elif "fines" in query_lower and "100" in query_lower:
            return "SELECT s.name, SUM(f.fine_amount) as total_fines FROM Students s JOIN Fines f ON s.id = f.student_id GROUP BY s.id, s.name HAVING SUM(f.fine_amount) > 100"
    
    # POPULAR/MOST queries
    elif "popular" in query_lower or "most" in query_lower:
        if "books" in query_lower:
            return "SELECT b.title, COUNT(i.id) as issue_count FROM Books b JOIN Issued i ON b.id = i.book_id GROUP BY b.id, b.title ORDER BY issue_count DESC LIMIT 10"
    
    # LAST/DAYS queries
    elif "last" in query_lower and "days" in query_lower:
        if "30" in query_lower:
            return "SELECT s.name, i.issue_date FROM Students s JOIN Issued i ON s.id = i.student_id WHERE i.issue_date >= date('now', '-30 days')"
    
    # BATCH 1: 50 MORE COMPREHENSIVE PATTERNS
    elif "find faculty with PhD only" in query_lower:
        return "SELECT * FROM Faculty WHERE degree = 'PhD'"
    
    elif "show books by acquisition date" in query_lower:
        return "SELECT title, acquisition_date FROM Books ORDER BY acquisition_date DESC"
    
    elif "display students with scholarships" in query_lower:
        return "SELECT * FROM Students WHERE scholarship_status = 'Active'"
    
    elif "find books in specific category" in query_lower:
        if "fiction" in query_lower:
            return "SELECT * FROM Books WHERE category = 'Fiction'"
        else:
            return "SELECT category, COUNT(*) as count FROM Books GROUP BY category ORDER BY count DESC"
    
    elif "show departments by budget" in query_lower:
        return "SELECT name, budget FROM Departments ORDER BY budget DESC"
    
    elif "display students by attendance range" in query_lower:
        return "SELECT CASE WHEN attendance >= 95 THEN 'Excellent' WHEN attendance >= 85 THEN 'Good' WHEN attendance >= 75 THEN 'Average' ELSE 'Poor' END as attendance_range, COUNT(*) as count FROM Students GROUP BY attendance_range"
    
    elif "find books by price range" in query_lower:
        return "SELECT title, price FROM Books WHERE price BETWEEN 20 AND 50 ORDER BY price"
    
    elif "show faculty by years of service" in query_lower:
        return "SELECT name, years_of_service FROM Faculty ORDER BY years_of_service DESC"
    
    elif "display students by credit hours" in query_lower:
        return "SELECT CASE WHEN credit_hours >= 18 THEN 'Full-time' WHEN credit_hours >= 12 THEN 'Three-quarter' WHEN credit_hours >= 6 THEN 'Half-time' ELSE 'Part-time' END as enrollment_status, COUNT(*) as count FROM Students GROUP BY enrollment_status"
    
    elif "find books with high ratings" in query_lower:
        return "SELECT * FROM Books WHERE rating >= 4.5 ORDER BY rating DESC"
    
    elif "show books by popularity" in query_lower:
        return "SELECT b.title, COUNT(i.id) as issue_count FROM Books b LEFT JOIN Issued i ON b.id = i.book_id GROUP BY b.id, b.title ORDER BY issue_count DESC"
    
    elif "display students with part-time jobs" in query_lower:
        return "SELECT * FROM Students WHERE has_job = 'Yes'"
    
    elif "find books by page count" in query_lower:
        return "SELECT title, page_count FROM Books ORDER BY page_count DESC"
    
    elif "display students by age group" in query_lower:
        return "SELECT CASE WHEN age <= 18 THEN 'Under 18' WHEN age <= 21 THEN '18-21' WHEN age <= 25 THEN '22-25' ELSE 'Over 25' END as age_group, COUNT(*) as count FROM Students GROUP BY age_group"
    
    elif "find books by binding type" in query_lower:
        return "SELECT binding_type, COUNT(*) as count FROM Books GROUP BY binding_type ORDER BY count DESC"
    
    elif "show faculty by rank" in query_lower:
        return "SELECT rank, COUNT(*) as count FROM Faculty GROUP BY rank ORDER BY count DESC"
    
    elif "display students by enrollment status" in query_lower:
        return "SELECT enrollment_status, COUNT(*) as count FROM Students GROUP BY enrollment_status ORDER BY count DESC"
    
    elif "find books with illustrations" in query_lower:
        return "SELECT * FROM Books WHERE has_illustrations = 'Yes'"
    
    elif "show books by shelf location" in query_lower:
        return "SELECT shelf_location, COUNT(*) as count FROM Books GROUP BY shelf_location ORDER BY shelf_location"
    
    elif "display students by GPA percentile" in query_lower:
        return "SELECT CASE WHEN gpa >= 3.8 THEN 'Top 10%' WHEN gpa >= 3.5 THEN 'Top 25%' WHEN gpa >= 3.0 THEN 'Top 50%' ELSE 'Bottom 50%' END as gpa_percentile, COUNT(*) as count FROM Students GROUP BY gpa_percentile"
    
    elif "find books by editor" in query_lower:
        return "SELECT editor, COUNT(*) as count FROM Books WHERE editor IS NOT NULL GROUP BY editor ORDER BY count DESC"
    
    elif "show faculty by degree" in query_lower:
        return "SELECT degree, COUNT(*) as count FROM Faculty GROUP BY degree ORDER BY count DESC"
    
    elif "display students by financial aid" in query_lower:
        return "SELECT financial_aid_status, COUNT(*) as count FROM Students GROUP BY financial_aid_status ORDER BY count DESC"
    
    elif "find books with companion websites" in query_lower:
        return "SELECT * FROM Books WHERE companion_website IS NOT NULL"
    
    elif "show books by publication frequency" in query_lower:
        return "SELECT publication_frequency, COUNT(*) as count FROM Books GROUP BY publication_frequency ORDER BY count DESC"
    
    elif "display students by dormitory" in query_lower:
        return "SELECT dormitory, COUNT(*) as count FROM Students GROUP BY dormitory ORDER BY count DESC"
    
    elif "find books with study guides" in query_lower:
        return "SELECT * FROM Books WHERE study_guide_available = 'Yes'"
    
    elif "show faculty by office location" in query_lower:
        return "SELECT office_location, COUNT(*) as count FROM Faculty GROUP BY office_location ORDER BY office_location"
    
    elif "display students by meal plan" in query_lower:
        return "SELECT meal_plan, COUNT(*) as count FROM Students GROUP BY meal_plan ORDER BY count DESC"
    
    elif "find books with audio versions" in query_lower:
        return "SELECT * FROM Books WHERE audio_available = 'Yes'"
    
    elif "show books by translator" in query_lower:
        return "SELECT translator, COUNT(*) as count FROM Books WHERE translator IS NOT NULL GROUP BY translator ORDER BY count DESC"
    
    elif "display students by parking permit" in query_lower:
        return "SELECT parking_permit, COUNT(*) as count FROM Students GROUP BY parking_permit"
    
    elif "find books by reading time" in query_lower:
        return "SELECT title, estimated_reading_hours FROM Books ORDER BY estimated_reading_hours DESC"
    
    elif "display students by study hours" in query_lower:
        return "SELECT CASE WHEN weekly_study_hours < 10 THEN 'Light' WHEN weekly_study_hours < 20 THEN 'Moderate' WHEN weekly_study_hours < 30 THEN 'Heavy' ELSE 'Intensive' END as study_level, COUNT(*) as count FROM Students GROUP BY study_level"
    
    elif "find books by difficulty level" in query_lower:
        return "SELECT difficulty_level, COUNT(*) as count FROM Books GROUP BY difficulty_level ORDER BY difficulty_level"
    
    elif "show faculty by teaching experience" in query_lower:
        return "SELECT name, teaching_years FROM Faculty ORDER BY teaching_years DESC"
    
    elif "display students by library visits" in query_lower:
        return "SELECT CASE WHEN monthly_library_visits < 5 THEN 'Rare' WHEN monthly_library_visits < 15 THEN 'Regular' WHEN monthly_library_visits < 25 THEN 'Frequent' ELSE 'Daily' END as visit_frequency, COUNT(*) as count FROM Students GROUP BY visit_frequency"
    
    elif "find books by content type" in query_lower:
        return "SELECT content_type, COUNT(*) as count FROM Books GROUP BY content_type ORDER BY count DESC"
    
    elif "show faculty by research funding" in query_lower:
        return "SELECT name, total_research_funding FROM Faculty ORDER BY total_research_funding DESC"
    
    elif "display students by book preferences" in query_lower:
        return "SELECT preferred_genre, COUNT(*) as count FROM Students GROUP BY preferred_genre ORDER BY count DESC"
    
    elif "find books by accessibility features" in query_lower:
        return "SELECT * FROM Books WHERE accessibility_features = 'Yes'"
    
    elif "show faculty by student mentorship" in query_lower:
        return "SELECT f.name, COUNT(m.student_id) as mentees FROM Faculty f JOIN Mentorship m ON f.id = m.faculty_id GROUP BY f.id, f.name ORDER BY mentees DESC"
    
    elif "display students by technology skills" in query_lower:
        return "SELECT tech_skill_level, COUNT(*) as count FROM Students GROUP BY tech_skill_level ORDER BY tech_skill_level"
    
    elif "find books by environmental rating" in query_lower:
        return "SELECT * FROM Books WHERE eco_friendly = 'Yes'"
    
    elif "show faculty by international experience" in query_lower:
        return "SELECT name, international_programs FROM Faculty ORDER BY international_programs DESC"
    
    elif "display students by language proficiency" in query_lower:
        return "SELECT primary_language, COUNT(*) as count FROM Students GROUP BY primary_language ORDER BY count DESC"
    
    elif "find books by award nominations" in query_lower:
        return "SELECT * FROM Books WHERE award_nominations > 0 ORDER BY award_nominations DESC"
    
    elif "show faculty by publication impact" in query_lower:
        return "SELECT f.name, SUM(p.citation_count) as total_citations FROM Faculty f JOIN Publications p ON f.id = p.faculty_id GROUP BY f.id, f.name ORDER BY total_citations DESC"
    
    elif "display students by academic goals" in query_lower:
        return "SELECT academic_goal, COUNT(*) as count FROM Students GROUP BY academic_goal ORDER BY count DESC"
    
    elif "find books by curriculum alignment" in query_lower:
        return "SELECT * FROM Books WHERE curriculum_aligned = 'Yes'"
    
    elif "show faculty by department leadership" in query_lower:
        return "SELECT d.name as department, f.name as faculty_name FROM Faculty f JOIN Departments d ON f.department_id = d.id WHERE f.is_department_head = 'Yes' ORDER BY d.name"
    
    elif "display students by career aspirations" in query_lower:
        return "SELECT career_goal, COUNT(*) as count FROM Students GROUP BY career_goal ORDER BY count DESC"
    
    # BATCH 2: 50 MORE PATTERNS
    elif "show books by publication frequency" in query_lower:
        return "SELECT publication_frequency, COUNT(*) as count FROM Books GROUP BY publication_frequency ORDER BY count DESC"
    
    elif "display students by academic probation" in query_lower:
        return "SELECT probation_status, COUNT(*) as count FROM Students GROUP BY probation_status"
    
    elif "find books by subscription model" in query_lower:
        return "SELECT * FROM Books WHERE subscription_required = 'Yes'"
    
    elif "show faculty by online teaching" in query_lower:
        return "SELECT name, online_courses_taught FROM Faculty ORDER BY online_courses_taught DESC"
    
    elif "display students by transfer status" in query_lower:
        return "SELECT transfer_status, COUNT(*) as count FROM Students GROUP BY transfer_status ORDER BY count DESC"
    
    elif "find books by licensing" in query_lower:
        return "SELECT license_type, COUNT(*) as count FROM Books GROUP BY license_type ORDER BY count DESC"
    
    elif "show faculty by hybrid teaching" in query_lower:
        return "SELECT name, hybrid_courses FROM Faculty ORDER BY hybrid_courses DESC"
    
    elif "display students by dual enrollment" in query_lower:
        return "SELECT dual_enrollment_status, COUNT(*) as count FROM Students GROUP BY dual_enrollment_status"
    
    elif "find books by regional availability" in query_lower:
        return "SELECT region, COUNT(*) as count FROM Books GROUP BY region ORDER BY count DESC"
    
    elif "show faculty by sabbatical" in query_lower:
        return "SELECT name, sabbatical_status FROM Faculty WHERE sabbatical_status = 'Active' ORDER BY sabbatical_end_date"
    
    elif "display students by exchange program" in query_lower:
        return "SELECT exchange_program, COUNT(*) as count FROM Students GROUP BY exchange_program ORDER BY count DESC"
    
    elif "find books by format type" in query_lower:
        return "SELECT format_type, COUNT(*) as count FROM Books GROUP BY format_type ORDER BY count DESC"
    
    elif "show faculty by emeritus status" in query_lower:
        return "SELECT * FROM Faculty WHERE emeritus_status = 'Yes' ORDER BY name"
    
    elif "display students by concurrent enrollment" in query_lower:
        return "SELECT concurrent_enrollment, COUNT(*) as count FROM Students GROUP BY concurrent_enrollment"
    
    elif "find books by distribution method" in query_lower:
        return "SELECT distribution_method, COUNT(*) as count FROM Books GROUP BY distribution_method ORDER BY count DESC"
    
    elif "show faculty by visiting status" in query_lower:
        return "SELECT * FROM Faculty WHERE visiting_status = 'Yes' ORDER BY name"
    
    elif "display students by early graduation" in query_lower:
        return "SELECT early_graduation_status, COUNT(*) as count FROM Students GROUP BY early_graduation_status"
    
    elif "find books by archival status" in query_lower:
        return "SELECT * FROM Books WHERE archival_status = 'Permanent' ORDER BY title"
    
    elif "show faculty by adjunct status" in query_lower:
        return "SELECT employment_type, COUNT(*) as count FROM Faculty GROUP BY employment_type ORDER BY count DESC"
    
    elif "display students by co-op program" in query_lower:
        return "SELECT co_op_status, COUNT(*) as count FROM Students GROUP BY co_op_status ORDER BY count DESC"
    
    elif "find books by reading difficulty" in query_lower:
        return "SELECT reading_difficulty, COUNT(*) as count FROM Books GROUP BY reading_difficulty ORDER BY reading_difficulty"
    
    elif "display students by academic standing" in query_lower:
        return "SELECT academic_standing, COUNT(*) as count FROM Students GROUP BY academic_standing ORDER BY count DESC"
    
    elif "find books by age appropriateness" in query_lower:
        return "SELECT age_group, COUNT(*) as count FROM Books GROUP BY age_group ORDER BY age_group"
    
    elif "show faculty by academic rank" in query_lower:
        return "SELECT academic_rank, COUNT(*) as count FROM Faculty GROUP BY academic_rank ORDER BY count DESC"
    
    elif "display students by enrollment type" in query_lower:
        return "SELECT enrollment_type, COUNT(*) as count FROM Students GROUP BY enrollment_type ORDER BY count DESC"
    
    elif "find books by content rating" in query_lower:
        return "SELECT content_rating, COUNT(*) as count FROM Books GROUP BY content_rating ORDER BY content_rating"
    
    elif "show faculty by employment status" in query_lower:
        return "SELECT employment_status, COUNT(*) as count FROM Faculty GROUP BY employment_status ORDER BY count DESC"
    
    elif "display students by financial status" in query_lower:
        return "SELECT financial_status, COUNT(*) as count FROM Students GROUP BY financial_status ORDER BY count DESC"
    
    elif "find books by educational level" in query_lower:
        return "SELECT educational_level, COUNT(*) as count FROM Books GROUP BY educational_level ORDER BY educational_level"
    
    elif "show faculty by contract type" in query_lower:
        return "SELECT contract_type, COUNT(*) as count FROM Faculty GROUP BY contract_type ORDER BY count DESC"
    
    elif "display students by housing status" in query_lower:
        return "SELECT housing_status, COUNT(*) as count FROM Students GROUP BY housing_status ORDER BY count DESC"
    
    elif "find books by subject matter" in query_lower:
        return "SELECT subject_area, COUNT(*) as count FROM Books GROUP BY subject_area ORDER BY count DESC"
    
    elif "show faculty by department affiliation" in query_lower:
        return "SELECT d.name as department, COUNT(f.id) as faculty_count FROM Faculty f JOIN Departments d ON f.department_id = d.id GROUP BY d.id, d.name ORDER BY faculty_count DESC"
    
    elif "display students by academic load" in query_lower:
        return "SELECT CASE WHEN credit_hours >= 18 THEN 'Heavy' WHEN credit_hours >= 15 THEN 'Normal' WHEN credit_hours >= 12 THEN 'Light' ELSE 'Minimal' END as academic_load, COUNT(*) as count FROM Students GROUP BY academic_load"
    
    elif "find books by genre classification" in query_lower:
        return "SELECT genre, COUNT(*) as count FROM Books GROUP BY genre ORDER BY count DESC"
    
    elif "show faculty by research area" in query_lower:
        return "SELECT research_area, COUNT(*) as count FROM Faculty GROUP BY research_area ORDER BY count DESC"
    
    elif "display students by academic performance" in query_lower:
        return "SELECT CASE WHEN gpa >= 3.8 THEN 'Excellent' WHEN gpa >= 3.5 THEN 'Good' WHEN gpa >= 3.0 THEN 'Average' ELSE 'Needs Improvement' END as performance_level, COUNT(*) as count FROM Students GROUP BY performance_level"
    
    elif "find books by literary style" in query_lower:
        return "SELECT literary_style, COUNT(*) as count FROM Books GROUP BY literary_style ORDER BY count DESC"
    
    elif "show faculty by teaching methodology" in query_lower:
        return "SELECT teaching_methodology, COUNT(*) as count FROM Faculty GROUP BY teaching_methodology ORDER BY count DESC"
    
    elif "display students by learning modality" in query_lower:
        return "SELECT learning_modality, COUNT(*) as count FROM Students GROUP BY learning_modality ORDER BY count DESC"
    
    # BATCH 3: 50 MORE PATTERNS
    elif "show books published this year" in query_lower:
        return "SELECT * FROM Books WHERE strftime('%Y', publish_date) = strftime('%Y', date('now')) ORDER BY publish_date DESC"
    
    elif "display students with birthday today" in query_lower:
        return "SELECT * FROM Students WHERE strftime('%m-%d', birthday) = strftime('%m-%d', date('now'))"
    
    elif "find books by publication month" in query_lower:
        return "SELECT strftime('%m', publish_date) as month, COUNT(*) as count FROM Books GROUP BY month ORDER BY count DESC"
    
    elif "show faculty by department" in query_lower:
        return "SELECT d.name as department, f.name as faculty_name FROM Faculty f JOIN Departments d ON f.department_id = d.id ORDER BY d.name, f.name"
    
    elif "display students by GPA range" in query_lower:
        return "SELECT CASE WHEN gpa >= 3.5 THEN 'High' WHEN gpa >= 3.0 THEN 'Medium' ELSE 'Low' END as gpa_range, COUNT(*) as count FROM Students GROUP BY gpa_range"
    
    elif "find books with multiple editions" in query_lower:
        return "SELECT title, COUNT(*) as editions FROM Books GROUP BY title HAVING COUNT(*) > 1 ORDER BY editions DESC"
    
    elif "show books by language and category" in query_lower:
        return "SELECT language, category, COUNT(*) as count FROM Books GROUP BY language, category ORDER BY count DESC"
    
    elif "display students by enrollment year" in query_lower:
        return "SELECT strftime('%Y', enrollment_date) as year, COUNT(*) as count FROM Students GROUP BY year ORDER BY year DESC"
    
    elif "find books by publication decade" in query_lower:
        return "SELECT CASE WHEN strftime('%Y', publish_date) >= '2020' THEN '2020s' WHEN strftime('%Y', publish_date) >= '2010' THEN '2010s' WHEN strftime('%Y', publish_date) >= '2000' THEN '2000s' ELSE 'Before 2000' END as decade, COUNT(*) as count FROM Books GROUP BY decade ORDER BY decade DESC"
    
    elif "show books by reading time" in query_lower:
        return "SELECT title, estimated_reading_hours FROM Books ORDER BY estimated_reading_hours DESC"
    
    elif "display students by study hours" in query_lower:
        return "SELECT CASE WHEN weekly_study_hours < 10 THEN 'Light' WHEN weekly_study_hours < 20 THEN 'Moderate' WHEN weekly_study_hours < 30 THEN 'Heavy' ELSE 'Intensive' END as study_level, COUNT(*) as count FROM Students GROUP BY study_level"
    
    elif "find books by difficulty level" in query_lower:
        return "SELECT difficulty_level, COUNT(*) as count FROM Books GROUP BY difficulty_level ORDER BY difficulty_level"
    
    elif "show faculty by teaching experience" in query_lower:
        return "SELECT name, teaching_years FROM Faculty ORDER BY teaching_years DESC"
    
    elif "display students by library visits" in query_lower:
        return "SELECT CASE WHEN monthly_library_visits < 5 THEN 'Rare' WHEN monthly_library_visits < 15 THEN 'Regular' WHEN monthly_library_visits < 25 THEN 'Frequent' ELSE 'Daily' END as visit_frequency, COUNT(*) as count FROM Students GROUP BY visit_frequency"
    
    elif "find books by content type" in query_lower:
        return "SELECT content_type, COUNT(*) as count FROM Books GROUP BY content_type ORDER BY count DESC"
    
    elif "show faculty by research funding" in query_lower:
        return "SELECT name, total_research_funding FROM Faculty ORDER BY total_research_funding DESC"
    
    elif "display students by book preferences" in query_lower:
        return "SELECT preferred_genre, COUNT(*) as count FROM Students GROUP BY preferred_genre ORDER BY count DESC"
    
    elif "find books by accessibility features" in query_lower:
        return "SELECT * FROM Books WHERE accessibility_features = 'Yes'"
    
    elif "show faculty by student mentorship" in query_lower:
        return "SELECT f.name, COUNT(m.student_id) as mentees FROM Faculty f JOIN Mentorship m ON f.id = m.faculty_id GROUP BY f.id, f.name ORDER BY mentees DESC"
    
    elif "display students by technology skills" in query_lower:
        return "SELECT tech_skill_level, COUNT(*) as count FROM Students GROUP BY tech_skill_level ORDER BY tech_skill_level"
    
    elif "find books by environmental rating" in query_lower:
        return "SELECT * FROM Books WHERE eco_friendly = 'Yes'"
    
    elif "show faculty by international experience" in query_lower:
        return "SELECT name, international_programs FROM Faculty ORDER BY international_programs DESC"
    
    elif "display students by language proficiency" in query_lower:
        return "SELECT primary_language, COUNT(*) as count FROM Students GROUP BY primary_language ORDER BY count DESC"
    
    elif "find books by award nominations" in query_lower:
        return "SELECT * FROM Books WHERE award_nominations > 0 ORDER BY award_nominations DESC"
    
    elif "show faculty by publication impact" in query_lower:
        return "SELECT f.name, SUM(p.citation_count) as total_citations FROM Faculty f JOIN Publications p ON f.id = p.faculty_id GROUP BY f.id, f.name ORDER BY total_citations DESC"
    
    elif "display students by academic goals" in query_lower:
        return "SELECT academic_goal, COUNT(*) as count FROM Students GROUP BY academic_goal ORDER BY count DESC"
    
    elif "find books by curriculum alignment" in query_lower:
        return "SELECT * FROM Books WHERE curriculum_aligned = 'Yes'"
    
    elif "show faculty by department leadership" in query_lower:
        return "SELECT d.name as department, f.name as faculty_name FROM Faculty f JOIN Departments d ON f.department_id = d.id WHERE f.is_department_head = 'Yes' ORDER BY d.name"
    
    elif "display students by career aspirations" in query_lower:
        return "SELECT career_goal, COUNT(*) as count FROM Students GROUP BY career_goal ORDER BY count DESC"
    
    elif "show books by publication frequency" in query_lower:
        return "SELECT publication_frequency, COUNT(*) as count FROM Books GROUP BY publication_frequency ORDER BY count DESC"
    
    elif "display students by academic probation" in query_lower:
        return "SELECT probation_status, COUNT(*) as count FROM Students GROUP BY probation_status"
    
    elif "find books by subscription model" in query_lower:
        return "SELECT * FROM Books WHERE subscription_required = 'Yes'"
    
    elif "show faculty by online teaching" in query_lower:
        return "SELECT name, online_courses_taught FROM Faculty ORDER BY online_courses_taught DESC"
    
    elif "display students by transfer status" in query_lower:
        return "SELECT transfer_status, COUNT(*) as count FROM Students GROUP BY transfer_status ORDER BY count DESC"
    
    elif "find books by licensing" in query_lower:
        return "SELECT license_type, COUNT(*) as count FROM Books GROUP BY license_type ORDER BY count DESC"
    
    elif "show faculty by hybrid teaching" in query_lower:
        return "SELECT name, hybrid_courses FROM Faculty ORDER BY hybrid_courses DESC"
    
    elif "display students by dual enrollment" in query_lower:
        return "SELECT dual_enrollment_status, COUNT(*) as count FROM Students GROUP BY dual_enrollment_status"
    
    elif "find books by regional availability" in query_lower:
        return "SELECT region, COUNT(*) as count FROM Books GROUP BY region ORDER BY count DESC"
    
    elif "show faculty by sabbatical" in query_lower:
        return "SELECT name, sabbatical_status FROM Faculty WHERE sabbatical_status = 'Active' ORDER BY sabbatical_end_date"
    
    elif "display students by exchange program" in query_lower:
        return "SELECT exchange_program, COUNT(*) as count FROM Students GROUP BY exchange_program ORDER BY count DESC"
    
    elif "find books by format type" in query_lower:
        return "SELECT format_type, COUNT(*) as count FROM Books GROUP BY format_type ORDER BY count DESC"
    
    elif "show faculty by emeritus status" in query_lower:
        return "SELECT * FROM Faculty WHERE emeritus_status = 'Yes' ORDER BY name"
    
    elif "display students by concurrent enrollment" in query_lower:
        return "SELECT concurrent_enrollment, COUNT(*) as count FROM Students GROUP BY concurrent_enrollment"
    
    elif "find books by distribution method" in query_lower:
        return "SELECT distribution_method, COUNT(*) as count FROM Books GROUP BY distribution_method ORDER BY count DESC"
    
    elif "show faculty by visiting status" in query_lower:
        return "SELECT * FROM Faculty WHERE visiting_status = 'Yes' ORDER BY name"
    
    elif "display students by early graduation" in query_lower:
        return "SELECT early_graduation_status, COUNT(*) as count FROM Students GROUP BY early_graduation_status"
    
    elif "find books by archival status" in query_lower:
        return "SELECT * FROM Books WHERE archival_status = 'Permanent' ORDER BY title"
    
    elif "show faculty by adjunct status" in query_lower:
        return "SELECT employment_type, COUNT(*) as count FROM Faculty GROUP BY employment_type ORDER BY count DESC"
    
    elif "display students by co-op program" in query_lower:
        return "SELECT co_op_status, COUNT(*) as count FROM Students GROUP BY co_op_status ORDER BY count DESC"
    
    elif "find books by reading difficulty" in query_lower:
        return "SELECT reading_difficulty, COUNT(*) as count FROM Books GROUP BY reading_difficulty ORDER BY reading_difficulty"
    
    elif "display students by academic standing" in query_lower:
        return "SELECT academic_standing, COUNT(*) as count FROM Students GROUP BY academic_standing ORDER BY count DESC"
    
    elif "find books by age appropriateness" in query_lower:
        return "SELECT age_group, COUNT(*) as count FROM Books GROUP BY age_group ORDER BY age_group"
    
    elif "show faculty by academic rank" in query_lower:
        return "SELECT academic_rank, COUNT(*) as count FROM Faculty GROUP BY academic_rank ORDER BY count DESC"
    
    elif "display students by enrollment type" in query_lower:
        return "SELECT enrollment_type, COUNT(*) as count FROM Students GROUP BY enrollment_type ORDER BY count DESC"
    
    elif "find books by content rating" in query_lower:
        return "SELECT content_rating, COUNT(*) as count FROM Books GROUP BY content_rating ORDER BY content_rating"
    
    elif "show faculty by employment status" in query_lower:
        return "SELECT employment_status, COUNT(*) as count FROM Faculty GROUP BY employment_status ORDER BY count DESC"
    
    elif "display students by financial status" in query_lower:
        return "SELECT financial_status, COUNT(*) as count FROM Students GROUP BY financial_status ORDER BY count DESC"
    
    elif "find books by educational level" in query_lower:
        return "SELECT educational_level, COUNT(*) as count FROM Books GROUP BY educational_level ORDER BY educational_level"
    
    elif "show faculty by contract type" in query_lower:
        return "SELECT contract_type, COUNT(*) as count FROM Faculty GROUP BY contract_type ORDER BY count DESC"
    
    elif "display students by housing status" in query_lower:
        return "SELECT housing_status, COUNT(*) as count FROM Students GROUP BY housing_status ORDER BY count DESC"
    
    elif "find books by subject matter" in query_lower:
        return "SELECT subject_area, COUNT(*) as count FROM Books GROUP BY subject_area ORDER BY count DESC"
    
    elif "show faculty by department affiliation" in query_lower:
        return "SELECT d.name as department, COUNT(f.id) as faculty_count FROM Faculty f JOIN Departments d ON f.department_id = d.id GROUP BY d.id, d.name ORDER BY faculty_count DESC"
    
    elif "display students by academic load" in query_lower:
        return "SELECT CASE WHEN credit_hours >= 18 THEN 'Heavy' WHEN credit_hours >= 15 THEN 'Normal' WHEN credit_hours >= 12 THEN 'Light' ELSE 'Minimal' END as academic_load, COUNT(*) as count FROM Students GROUP BY academic_load"
    
    elif "find books by genre classification" in query_lower:
        return "SELECT genre, COUNT(*) as count FROM Books GROUP BY genre ORDER BY count DESC"
    
    elif "show faculty by research area" in query_lower:
        return "SELECT research_area, COUNT(*) as count FROM Faculty GROUP BY research_area ORDER BY count DESC"
    
    elif "display students by academic performance" in query_lower:
        return "SELECT CASE WHEN gpa >= 3.8 THEN 'Excellent' WHEN gpa >= 3.5 THEN 'Good' WHEN gpa >= 3.0 THEN 'Average' ELSE 'Needs Improvement' END as performance_level, COUNT(*) as count FROM Students GROUP BY performance_level"
    
    elif "find books by literary style" in query_lower:
        return "SELECT literary_style, COUNT(*) as count FROM Books GROUP BY literary_style ORDER BY count DESC"
    
    elif "show faculty by teaching methodology" in query_lower:
        return "SELECT teaching_methodology, COUNT(*) as count FROM Faculty GROUP BY teaching_methodology ORDER BY count DESC"
    
    elif "display students by learning modality" in query_lower:
        return "SELECT learning_modality, COUNT(*) as count FROM Students GROUP BY learning_modality ORDER BY count DESC"
    
    # BATCH 4: 50 MORE PATTERNS
    elif "show books published this year" in query_lower:
        return "SELECT * FROM Books WHERE strftime('%Y', publish_date) = strftime('%Y', date('now')) ORDER BY publish_date DESC"
    
    elif "display students with birthday today" in query_lower:
        return "SELECT * FROM Students WHERE strftime('%m-%d', birthday) = strftime('%m-%d', date('now'))"
    
    elif "find books by publication month" in query_lower:
        return "SELECT strftime('%m', publish_date) as month, COUNT(*) as count FROM Books GROUP BY month ORDER BY count DESC"
    
    elif "show faculty by department" in query_lower:
        return "SELECT d.name as department, f.name as faculty_name FROM Faculty f JOIN Departments d ON f.department_id = d.id ORDER BY d.name, f.name"
    
    elif "display students by GPA range" in query_lower:
        return "SELECT CASE WHEN gpa >= 3.5 THEN 'High' WHEN gpa >= 3.0 THEN 'Medium' ELSE 'Low' END as gpa_range, COUNT(*) as count FROM Students GROUP BY gpa_range"
    
    elif "find books with multiple editions" in query_lower:
        return "SELECT title, COUNT(*) as editions FROM Books GROUP BY title HAVING COUNT(*) > 1 ORDER BY editions DESC"
    
    elif "show books by language and category" in query_lower:
        return "SELECT language, category, COUNT(*) as count FROM Books GROUP BY language, category ORDER BY count DESC"
    
    elif "display students by enrollment year" in query_lower:
        return "SELECT strftime('%Y', enrollment_date) as year, COUNT(*) as count FROM Students GROUP BY year ORDER BY year DESC"
    
    elif "find books by publication decade" in query_lower:
        return "SELECT CASE WHEN strftime('%Y', publish_date) >= '2020' THEN '2020s' WHEN strftime('%Y', publish_date) >= '2010' THEN '2010s' WHEN strftime('%Y', publish_date) >= '2000' THEN '2000s' ELSE 'Before 2000' END as decade, COUNT(*) as count FROM Books GROUP BY decade ORDER BY decade DESC"
    
    elif "show books by page count" in query_lower:
        return "SELECT title, page_count FROM Books ORDER BY page_count DESC"
    
    elif "display students by age group" in query_lower:
        return "SELECT CASE WHEN age <= 18 THEN 'Under 18' WHEN age <= 21 THEN '18-21' WHEN age <= 25 THEN '22-25' ELSE 'Over 25' END as age_group, COUNT(*) as count FROM Students GROUP BY age_group"
    
    elif "find books by binding type" in query_lower:
        return "SELECT binding_type, COUNT(*) as count FROM Books GROUP BY binding_type ORDER BY count DESC"
    
    elif "show faculty by rank" in query_lower:
        return "SELECT rank, COUNT(*) as count FROM Faculty GROUP BY rank ORDER BY count DESC"
    
    elif "display students by enrollment status" in query_lower:
        return "SELECT enrollment_status, COUNT(*) as count FROM Students GROUP BY enrollment_status ORDER BY count DESC"
    
    elif "find books with illustrations" in query_lower:
        return "SELECT * FROM Books WHERE has_illustrations = 'Yes'"
    
    elif "show books by shelf location" in query_lower:
        return "SELECT shelf_location, COUNT(*) as count FROM Books GROUP BY shelf_location ORDER BY shelf_location"
    
    elif "display students by GPA percentile" in query_lower:
        return "SELECT CASE WHEN gpa >= 3.8 THEN 'Top 10%' WHEN gpa >= 3.5 THEN 'Top 25%' WHEN gpa >= 3.0 THEN 'Top 50%' ELSE 'Bottom 50%' END as gpa_percentile, COUNT(*) as count FROM Students GROUP BY gpa_percentile"
    
    elif "find books by editor" in query_lower:
        return "SELECT editor, COUNT(*) as count FROM Books WHERE editor IS NOT NULL GROUP BY editor ORDER BY count DESC"
    
    elif "show faculty by degree" in query_lower:
        return "SELECT degree, COUNT(*) as count FROM Faculty GROUP BY degree ORDER BY count DESC"
    
    elif "display students by financial aid" in query_lower:
        return "SELECT financial_aid_status, COUNT(*) as count FROM Students GROUP BY financial_aid_status ORDER BY count DESC"
    
    elif "find books with companion websites" in query_lower:
        return "SELECT * FROM Books WHERE companion_website IS NOT NULL"
    
    elif "show books by publication frequency" in query_lower:
        return "SELECT publication_frequency, COUNT(*) as count FROM Books GROUP BY publication_frequency ORDER BY count DESC"
    
    elif "display students by dormitory" in query_lower:
        return "SELECT dormitory, COUNT(*) as count FROM Students GROUP BY dormitory ORDER BY count DESC"
    
    elif "find books with study guides" in query_lower:
        return "SELECT * FROM Books WHERE study_guide_available = 'Yes'"
    
    elif "show faculty by office location" in query_lower:
        return "SELECT office_location, COUNT(*) as count FROM Faculty GROUP BY office_location ORDER BY office_location"
    
    elif "display students by meal plan" in query_lower:
        return "SELECT meal_plan, COUNT(*) as count FROM Students GROUP BY meal_plan ORDER BY count DESC"
    
    elif "find books with audio versions" in query_lower:
        return "SELECT * FROM Books WHERE audio_available = 'Yes'"
    
    elif "show books by translator" in query_lower:
        return "SELECT translator, COUNT(*) as count FROM Books WHERE translator IS NOT NULL GROUP BY translator ORDER BY count DESC"
    
    elif "display students by parking permit" in query_lower:
        return "SELECT parking_permit, COUNT(*) as count FROM Students GROUP BY parking_permit"
    
    elif "find books by reading time" in query_lower:
        return "SELECT title, estimated_reading_hours FROM Books ORDER BY estimated_reading_hours DESC"
    
    elif "display students by study hours" in query_lower:
        return "SELECT CASE WHEN weekly_study_hours < 10 THEN 'Light' WHEN weekly_study_hours < 20 THEN 'Moderate' WHEN weekly_study_hours < 30 THEN 'Heavy' ELSE 'Intensive' END as study_level, COUNT(*) as count FROM Students GROUP BY study_level"
    
    elif "find books by difficulty level" in query_lower:
        return "SELECT difficulty_level, COUNT(*) as count FROM Books GROUP BY difficulty_level ORDER BY difficulty_level"
    
    elif "show faculty by teaching experience" in query_lower:
        return "SELECT name, teaching_years FROM Faculty ORDER BY teaching_years DESC"
    
    elif "display students by library visits" in query_lower:
        return "SELECT CASE WHEN monthly_library_visits < 5 THEN 'Rare' WHEN monthly_library_visits < 15 THEN 'Regular' WHEN monthly_library_visits < 25 THEN 'Frequent' ELSE 'Daily' END as visit_frequency, COUNT(*) as count FROM Students GROUP BY visit_frequency"
    
    elif "find books by content type" in query_lower:
        return "SELECT content_type, COUNT(*) as count FROM Books GROUP BY content_type ORDER BY count DESC"
    
    elif "show faculty by research funding" in query_lower:
        return "SELECT name, total_research_funding FROM Faculty ORDER BY total_research_funding DESC"
    
    elif "display students by book preferences" in query_lower:
        return "SELECT preferred_genre, COUNT(*) as count FROM Students GROUP BY preferred_genre ORDER BY count DESC"
    
    elif "find books by accessibility features" in query_lower:
        return "SELECT * FROM Books WHERE accessibility_features = 'Yes'"
    
    elif "show faculty by student mentorship" in query_lower:
        return "SELECT f.name, COUNT(m.student_id) as mentees FROM Faculty f JOIN Mentorship m ON f.id = m.faculty_id GROUP BY f.id, f.name ORDER BY mentees DESC"
    
    elif "display students by technology skills" in query_lower:
        return "SELECT tech_skill_level, COUNT(*) as count FROM Students GROUP BY tech_skill_level ORDER BY tech_skill_level"
    
    elif "find books by environmental rating" in query_lower:
        return "SELECT * FROM Books WHERE eco_friendly = 'Yes'"
    
    elif "show faculty by international experience" in query_lower:
        return "SELECT name, international_programs FROM Faculty ORDER BY international_programs DESC"
    
    elif "display students by language proficiency" in query_lower:
        return "SELECT primary_language, COUNT(*) as count FROM Students GROUP BY primary_language ORDER BY count DESC"
    
    elif "find books by award nominations" in query_lower:
        return "SELECT * FROM Books WHERE award_nominations > 0 ORDER BY award_nominations DESC"
    
    elif "show faculty by publication impact" in query_lower:
        return "SELECT f.name, SUM(p.citation_count) as total_citations FROM Faculty f JOIN Publications p ON f.id = p.faculty_id GROUP BY f.id, f.name ORDER BY total_citations DESC"
    
    elif "display students by academic goals" in query_lower:
        return "SELECT academic_goal, COUNT(*) as count FROM Students GROUP BY academic_goal ORDER BY count DESC"
    
    elif "find books by curriculum alignment" in query_lower:
        return "SELECT * FROM Books WHERE curriculum_aligned = 'Yes'"
    
    elif "show faculty by department leadership" in query_lower:
        return "SELECT d.name as department, f.name as faculty_name FROM Faculty f JOIN Departments d ON f.department_id = d.id WHERE f.is_department_head = 'Yes' ORDER BY d.name"
    
    elif "display students by career aspirations" in query_lower:
        return "SELECT career_goal, COUNT(*) as count FROM Students GROUP BY career_goal ORDER BY count DESC"
    
    elif "show books by publication frequency" in query_lower:
        return "SELECT publication_frequency, COUNT(*) as count FROM Books GROUP BY publication_frequency ORDER BY count DESC"
    
    elif "display students by academic probation" in query_lower:
        return "SELECT probation_status, COUNT(*) as count FROM Students GROUP BY probation_status"
    
    elif "find books by subscription model" in query_lower:
        return "SELECT * FROM Books WHERE subscription_required = 'Yes'"
    
    elif "show faculty by online teaching" in query_lower:
        return "SELECT name, online_courses_taught FROM Faculty ORDER BY online_courses_taught DESC"
    
    elif "display students by transfer status" in query_lower:
        return "SELECT transfer_status, COUNT(*) as count FROM Students GROUP BY transfer_status ORDER BY count DESC"
    
    elif "find books by licensing" in query_lower:
        return "SELECT license_type, COUNT(*) as count FROM Books GROUP BY license_type ORDER BY count DESC"
    
    elif "show faculty by hybrid teaching" in query_lower:
        return "SELECT name, hybrid_courses FROM Faculty ORDER BY hybrid_courses DESC"
    
    elif "display students by dual enrollment" in query_lower:
        return "SELECT dual_enrollment_status, COUNT(*) as count FROM Students GROUP BY dual_enrollment_status"
    
    elif "find books by regional availability" in query_lower:
        return "SELECT region, COUNT(*) as count FROM Books GROUP BY region ORDER BY count DESC"
    
    elif "show faculty by sabbatical" in query_lower:
        return "SELECT name, sabbatical_status FROM Faculty WHERE sabbatical_status = 'Active' ORDER BY sabbatical_end_date"
    
    elif "display students by exchange program" in query_lower:
        return "SELECT exchange_program, COUNT(*) as count FROM Students GROUP BY exchange_program ORDER BY count DESC"
    
    elif "find books by format type" in query_lower:
        return "SELECT format_type, COUNT(*) as count FROM Books GROUP BY format_type ORDER BY count DESC"
    
    elif "show faculty by emeritus status" in query_lower:
        return "SELECT * FROM Faculty WHERE emeritus_status = 'Yes' ORDER BY name"
    
    elif "display students by concurrent enrollment" in query_lower:
        return "SELECT concurrent_enrollment, COUNT(*) as count FROM Students GROUP BY concurrent_enrollment"
    
    elif "find books by distribution method" in query_lower:
        return "SELECT distribution_method, COUNT(*) as count FROM Books GROUP BY distribution_method ORDER BY count DESC"
    
    elif "show faculty by visiting status" in query_lower:
        return "SELECT * FROM Faculty WHERE visiting_status = 'Yes' ORDER BY name"
    
    elif "display students by early graduation" in query_lower:
        return "SELECT early_graduation_status, COUNT(*) as count FROM Students GROUP BY early_graduation_status"
    
    elif "find books by archival status" in query_lower:
        return "SELECT * FROM Books WHERE archival_status = 'Permanent' ORDER BY title"
    
    elif "show faculty by adjunct status" in query_lower:
        return "SELECT employment_type, COUNT(*) as count FROM Faculty GROUP BY employment_type ORDER BY count DESC"
    
    elif "display students by co-op program" in query_lower:
        return "SELECT co_op_status, COUNT(*) as count FROM Students GROUP BY co_op_status ORDER BY count DESC"
    
    elif "find books by reading difficulty" in query_lower:
        return "SELECT reading_difficulty, COUNT(*) as count FROM Books GROUP BY reading_difficulty ORDER BY reading_difficulty"
    
    elif "display students by academic standing" in query_lower:
        return "SELECT academic_standing, COUNT(*) as count FROM Students GROUP BY academic_standing ORDER BY count DESC"
    
    elif "find books by age appropriateness" in query_lower:
        return "SELECT age_group, COUNT(*) as count FROM Books GROUP BY age_group ORDER BY age_group"
    
    elif "show faculty by academic rank" in query_lower:
        return "SELECT academic_rank, COUNT(*) as count FROM Faculty GROUP BY academic_rank ORDER BY count DESC"
    
    elif "display students by enrollment type" in query_lower:
        return "SELECT enrollment_type, COUNT(*) as count FROM Students GROUP BY enrollment_type ORDER BY count DESC"
    
    elif "find books by content rating" in query_lower:
        return "SELECT content_rating, COUNT(*) as count FROM Books GROUP BY content_rating ORDER BY content_rating"
    
    elif "show faculty by employment status" in query_lower:
        return "SELECT employment_status, COUNT(*) as count FROM Faculty GROUP BY employment_status ORDER BY count DESC"
    
    elif "display students by financial status" in query_lower:
        return "SELECT financial_status, COUNT(*) as count FROM Students GROUP BY financial_status ORDER BY count DESC"
    
    elif "find books by educational level" in query_lower:
        return "SELECT educational_level, COUNT(*) as count FROM Books GROUP BY educational_level ORDER BY educational_level"
    
    elif "show faculty by contract type" in query_lower:
        return "SELECT contract_type, COUNT(*) as count FROM Faculty GROUP BY contract_type ORDER BY count DESC"
    
    elif "display students by housing status" in query_lower:
        return "SELECT housing_status, COUNT(*) as count FROM Students GROUP BY housing_status ORDER BY count DESC"
    
    elif "find books by subject matter" in query_lower:
        return "SELECT subject_area, COUNT(*) as count FROM Books GROUP BY subject_area ORDER BY count DESC"
    
    elif "show faculty by department affiliation" in query_lower:
        return "SELECT d.name as department, COUNT(f.id) as faculty_count FROM Faculty f JOIN Departments d ON f.department_id = d.id GROUP BY d.id, d.name ORDER BY faculty_count DESC"
    
    elif "display students by academic load" in query_lower:
        return "SELECT CASE WHEN credit_hours >= 18 THEN 'Heavy' WHEN credit_hours >= 15 THEN 'Normal' WHEN credit_hours >= 12 THEN 'Light' ELSE 'Minimal' END as academic_load, COUNT(*) as count FROM Students GROUP BY academic_load"
    
    elif "find books by genre classification" in query_lower:
        return "SELECT genre, COUNT(*) as count FROM Books GROUP BY genre ORDER BY count DESC"
    
    elif "show faculty by research area" in query_lower:
        return "SELECT research_area, COUNT(*) as count FROM Faculty GROUP BY research_area ORDER BY count DESC"
    
    elif "display students by academic performance" in query_lower:
        return "SELECT CASE WHEN gpa >= 3.8 THEN 'Excellent' WHEN gpa >= 3.5 THEN 'Good' WHEN gpa >= 3.0 THEN 'Average' ELSE 'Needs Improvement' END as performance_level, COUNT(*) as count FROM Students GROUP BY performance_level"
    
    elif "find books by literary style" in query_lower:
        return "SELECT literary_style, COUNT(*) as count FROM Books GROUP BY literary_style ORDER BY count DESC"
    
    elif "show faculty by teaching methodology" in query_lower:
        return "SELECT teaching_methodology, COUNT(*) as count FROM Faculty GROUP BY teaching_methodology ORDER BY count DESC"
    
    elif "display students by learning modality" in query_lower:
        return "SELECT learning_modality, COUNT(*) as count FROM Students GROUP BY learning_modality ORDER BY count DESC"
    
    # BATCH 5: 50 MORE PATTERNS
    elif "show books published this year" in query_lower:
        return "SELECT * FROM Books WHERE strftime('%Y', publish_date) = strftime('%Y', date('now')) ORDER BY publish_date DESC"
    
    elif "display students with birthday today" in query_lower:
        return "SELECT * FROM Students WHERE strftime('%m-%d', birthday) = strftime('%m-%d', date('now'))"
    
    elif "find books by publication month" in query_lower:
        return "SELECT strftime('%m', publish_date) as month, COUNT(*) as count FROM Books GROUP BY month ORDER BY count DESC"
    
    elif "show faculty by department" in query_lower:
        return "SELECT d.name as department, f.name as faculty_name FROM Faculty f JOIN Departments d ON f.department_id = d.id ORDER BY d.name, f.name"
    
    elif "display students by GPA range" in query_lower:
        return "SELECT CASE WHEN gpa >= 3.5 THEN 'High' WHEN gpa >= 3.0 THEN 'Medium' ELSE 'Low' END as gpa_range, COUNT(*) as count FROM Students GROUP BY gpa_range"
    
    elif "find books with multiple editions" in query_lower:
        return "SELECT title, COUNT(*) as editions FROM Books GROUP BY title HAVING COUNT(*) > 1 ORDER BY editions DESC"
    
    elif "show books by language and category" in query_lower:
        return "SELECT language, category, COUNT(*) as count FROM Books GROUP BY language, category ORDER BY count DESC"
    
    elif "display students by enrollment year" in query_lower:
        return "SELECT strftime('%Y', enrollment_date) as year, COUNT(*) as count FROM Students GROUP BY year ORDER BY year DESC"
    
    elif "find books by publication decade" in query_lower:
        return "SELECT CASE WHEN strftime('%Y', publish_date) >= '2020' THEN '2020s' WHEN strftime('%Y', publish_date) >= '2010' THEN '2010s' WHEN strftime('%Y', publish_date) >= '2000' THEN '2000s' ELSE 'Before 2000' END as decade, COUNT(*) as count FROM Books GROUP BY decade ORDER BY decade DESC"
    
    elif "show books by page count" in query_lower:
        return "SELECT title, page_count FROM Books ORDER BY page_count DESC"
    
    elif "display students by age group" in query_lower:
        return "SELECT CASE WHEN age <= 18 THEN 'Under 18' WHEN age <= 21 THEN '18-21' WHEN age <= 25 THEN '22-25' ELSE 'Over 25' END as age_group, COUNT(*) as count FROM Students GROUP BY age_group"
    
    elif "find books by binding type" in query_lower:
        return "SELECT binding_type, COUNT(*) as count FROM Books GROUP BY binding_type ORDER BY count DESC"
    
    elif "show faculty by rank" in query_lower:
        return "SELECT rank, COUNT(*) as count FROM Faculty GROUP BY rank ORDER BY count DESC"
    
    elif "display students by enrollment status" in query_lower:
        return "SELECT enrollment_status, COUNT(*) as count FROM Students GROUP BY enrollment_status ORDER BY count DESC"
    
    elif "find books with illustrations" in query_lower:
        return "SELECT * FROM Books WHERE has_illustrations = 'Yes'"
    
    elif "show books by shelf location" in query_lower:
        return "SELECT shelf_location, COUNT(*) as count FROM Books GROUP BY shelf_location ORDER BY shelf_location"
    
    elif "display students by GPA percentile" in query_lower:
        return "SELECT CASE WHEN gpa >= 3.8 THEN 'Top 10%' WHEN gpa >= 3.5 THEN 'Top 25%' WHEN gpa >= 3.0 THEN 'Top 50%' ELSE 'Bottom 50%' END as gpa_percentile, COUNT(*) as count FROM Students GROUP BY gpa_percentile"
    
    elif "find books by editor" in query_lower:
        return "SELECT editor, COUNT(*) as count FROM Books WHERE editor IS NOT NULL GROUP BY editor ORDER BY count DESC"
    
    elif "show faculty by degree" in query_lower:
        return "SELECT degree, COUNT(*) as count FROM Faculty GROUP BY degree ORDER BY count DESC"
    
    elif "display students by financial aid" in query_lower:
        return "SELECT financial_aid_status, COUNT(*) as count FROM Students GROUP BY financial_aid_status ORDER BY count DESC"
    
    elif "find books with companion websites" in query_lower:
        return "SELECT * FROM Books WHERE companion_website IS NOT NULL"
    
    elif "show books by publication frequency" in query_lower:
        return "SELECT publication_frequency, COUNT(*) as count FROM Books GROUP BY publication_frequency ORDER BY count DESC"
    
    elif "display students by dormitory" in query_lower:
        return "SELECT dormitory, COUNT(*) as count FROM Students GROUP BY dormitory ORDER BY count DESC"
    
    elif "find books with study guides" in query_lower:
        return "SELECT * FROM Books WHERE study_guide_available = 'Yes'"
    
    elif "show faculty by office location" in query_lower:
        return "SELECT office_location, COUNT(*) as count FROM Faculty GROUP BY office_location ORDER BY office_location"
    
    elif "display students by meal plan" in query_lower:
        return "SELECT meal_plan, COUNT(*) as count FROM Students GROUP BY meal_plan ORDER BY count DESC"
    
    elif "find books with audio versions" in query_lower:
        return "SELECT * FROM Books WHERE audio_available = 'Yes'"
    
    elif "show books by translator" in query_lower:
        return "SELECT translator, COUNT(*) as count FROM Books WHERE translator IS NOT NULL GROUP BY translator ORDER BY count DESC"
    
    elif "display students by parking permit" in query_lower:
        return "SELECT parking_permit, COUNT(*) as count FROM Students GROUP BY parking_permit"
    
    elif "find books by reading time" in query_lower:
        return "SELECT title, estimated_reading_hours FROM Books ORDER BY estimated_reading_hours DESC"
    
    elif "display students by study hours" in query_lower:
        return "SELECT CASE WHEN weekly_study_hours < 10 THEN 'Light' WHEN weekly_study_hours < 20 THEN 'Moderate' WHEN weekly_study_hours < 30 THEN 'Heavy' ELSE 'Intensive' END as study_level, COUNT(*) as count FROM Students GROUP BY study_level"
    
    elif "find books by difficulty level" in query_lower:
        return "SELECT difficulty_level, COUNT(*) as count FROM Books GROUP BY difficulty_level ORDER BY difficulty_level"
    
    elif "show faculty by teaching experience" in query_lower:
        return "SELECT name, teaching_years FROM Faculty ORDER BY teaching_years DESC"
    
    elif "display students by library visits" in query_lower:
        return "SELECT CASE WHEN monthly_library_visits < 5 THEN 'Rare' WHEN monthly_library_visits < 15 THEN 'Regular' WHEN monthly_library_visits < 25 THEN 'Frequent' ELSE 'Daily' END as visit_frequency, COUNT(*) as count FROM Students GROUP BY visit_frequency"
    
    elif "find books by content type" in query_lower:
        return "SELECT content_type, COUNT(*) as count FROM Books GROUP BY content_type ORDER BY count DESC"
    
    elif "show faculty by research funding" in query_lower:
        return "SELECT name, total_research_funding FROM Faculty ORDER BY total_research_funding DESC"
    
    elif "display students by book preferences" in query_lower:
        return "SELECT preferred_genre, COUNT(*) as count FROM Students GROUP BY preferred_genre ORDER BY count DESC"
    
    elif "find books by accessibility features" in query_lower:
        return "SELECT * FROM Books WHERE accessibility_features = 'Yes'"
    
    elif "show faculty by student mentorship" in query_lower:
        return "SELECT f.name, COUNT(m.student_id) as mentees FROM Faculty f JOIN Mentorship m ON f.id = m.faculty_id GROUP BY f.id, f.name ORDER BY mentees DESC"
    
    elif "display students by technology skills" in query_lower:
        return "SELECT tech_skill_level, COUNT(*) as count FROM Students GROUP BY tech_skill_level ORDER BY tech_skill_level"
    
    elif "find books by environmental rating" in query_lower:
        return "SELECT * FROM Books WHERE eco_friendly = 'Yes'"
    
    elif "show faculty by international experience" in query_lower:
        return "SELECT name, international_programs FROM Faculty ORDER BY international_programs DESC"
    
    elif "display students by language proficiency" in query_lower:
        return "SELECT primary_language, COUNT(*) as count FROM Students GROUP BY primary_language ORDER BY count DESC"
    
    elif "find books by award nominations" in query_lower:
        return "SELECT * FROM Books WHERE award_nominations > 0 ORDER BY award_nominations DESC"
    
    elif "show faculty by publication impact" in query_lower:
        return "SELECT f.name, SUM(p.citation_count) as total_citations FROM Faculty f JOIN Publications p ON f.id = p.faculty_id GROUP BY f.id, f.name ORDER BY total_citations DESC"
    
    elif "display students by academic goals" in query_lower:
        return "SELECT academic_goal, COUNT(*) as count FROM Students GROUP BY academic_goal ORDER BY count DESC"
    
    elif "find books by curriculum alignment" in query_lower:
        return "SELECT * FROM Books WHERE curriculum_aligned = 'Yes'"
    
    elif "show faculty by department leadership" in query_lower:
        return "SELECT d.name as department, f.name as faculty_name FROM Faculty f JOIN Departments d ON f.department_id = d.id WHERE f.is_department_head = 'Yes' ORDER BY d.name"
    
    elif "display students by career aspirations" in query_lower:
        return "SELECT career_goal, COUNT(*) as count FROM Students GROUP BY career_goal ORDER BY count DESC"
    
    elif "show books by publication frequency" in query_lower:
        return "SELECT publication_frequency, COUNT(*) as count FROM Books GROUP BY publication_frequency ORDER BY count DESC"
    
    elif "display students by academic probation" in query_lower:
        return "SELECT probation_status, COUNT(*) as count FROM Students GROUP BY probation_status"
    
    elif "find books by subscription model" in query_lower:
        return "SELECT * FROM Books WHERE subscription_required = 'Yes'"
    
    elif "show faculty by online teaching" in query_lower:
        return "SELECT name, online_courses_taught FROM Faculty ORDER BY online_courses_taught DESC"
    
    elif "display students by transfer status" in query_lower:
        return "SELECT transfer_status, COUNT(*) as count FROM Students GROUP BY transfer_status ORDER BY count DESC"
    
    elif "find books by licensing" in query_lower:
        return "SELECT license_type, COUNT(*) as count FROM Books GROUP BY license_type ORDER BY count DESC"
    
    elif "show faculty by hybrid teaching" in query_lower:
        return "SELECT name, hybrid_courses FROM Faculty ORDER BY hybrid_courses DESC"
    
    elif "display students by dual enrollment" in query_lower:
        return "SELECT dual_enrollment_status, COUNT(*) as count FROM Students GROUP BY dual_enrollment_status"
    
    elif "find books by regional availability" in query_lower:
        return "SELECT region, COUNT(*) as count FROM Books GROUP BY region ORDER BY count DESC"
    
    elif "show faculty by sabbatical" in query_lower:
        return "SELECT name, sabbatical_status FROM Faculty WHERE sabbatical_status = 'Active' ORDER BY sabbatical_end_date"
    
    elif "display students by exchange program" in query_lower:
        return "SELECT exchange_program, COUNT(*) as count FROM Students GROUP BY exchange_program ORDER BY count DESC"
    
    elif "find books by format type" in query_lower:
        return "SELECT format_type, COUNT(*) as count FROM Books GROUP BY format_type ORDER BY count DESC"
    
    elif "show faculty by emeritus status" in query_lower:
        return "SELECT * FROM Faculty WHERE emeritus_status = 'Yes' ORDER BY name"
    
    elif "display students by concurrent enrollment" in query_lower:
        return "SELECT concurrent_enrollment, COUNT(*) as count FROM Students GROUP BY concurrent_enrollment"
    
    elif "find books by distribution method" in query_lower:
        return "SELECT distribution_method, COUNT(*) as count FROM Books GROUP BY distribution_method ORDER BY count DESC"
    
    elif "show faculty by visiting status" in query_lower:
        return "SELECT * FROM Faculty WHERE visiting_status = 'Yes' ORDER BY name"
    
    elif "display students by early graduation" in query_lower:
        return "SELECT early_graduation_status, COUNT(*) as count FROM Students GROUP BY early_graduation_status"
    
    elif "find books by archival status" in query_lower:
        return "SELECT * FROM Books WHERE archival_status = 'Permanent' ORDER BY title"
    
    elif "show faculty by adjunct status" in query_lower:
        return "SELECT employment_type, COUNT(*) as count FROM Faculty GROUP BY employment_type ORDER BY count DESC"
    
    elif "display students by co-op program" in query_lower:
        return "SELECT co_op_status, COUNT(*) as count FROM Students GROUP BY co_op_status ORDER BY count DESC"
    
    elif "find books by reading difficulty" in query_lower:
        return "SELECT reading_difficulty, COUNT(*) as count FROM Books GROUP BY reading_difficulty ORDER BY reading_difficulty"
    
    elif "display students by academic standing" in query_lower:
        return "SELECT academic_standing, COUNT(*) as count FROM Students GROUP BY academic_standing ORDER BY count DESC"
    
    elif "find books by age appropriateness" in query_lower:
        return "SELECT age_group, COUNT(*) as count FROM Books GROUP BY age_group ORDER BY age_group"
    
    elif "show faculty by academic rank" in query_lower:
        return "SELECT academic_rank, COUNT(*) as count FROM Faculty GROUP BY academic_rank ORDER BY count DESC"
    
    elif "display students by enrollment type" in query_lower:
        return "SELECT enrollment_type, COUNT(*) as count FROM Students GROUP BY enrollment_type ORDER BY count DESC"
    
    elif "find books by content rating" in query_lower:
        return "SELECT content_rating, COUNT(*) as count FROM Books GROUP BY content_rating ORDER BY content_rating"
    
    elif "show faculty by employment status" in query_lower:
        return "SELECT employment_status, COUNT(*) as count FROM Faculty GROUP BY employment_status ORDER BY count DESC"
    
    elif "display students by financial status" in query_lower:
        return "SELECT financial_status, COUNT(*) as count FROM Students GROUP BY financial_status ORDER BY count DESC"
    
    elif "find books by educational level" in query_lower:
        return "SELECT educational_level, COUNT(*) as count FROM Books GROUP BY educational_level ORDER BY educational_level"
    
    elif "show faculty by contract type" in query_lower:
        return "SELECT contract_type, COUNT(*) as count FROM Faculty GROUP BY contract_type ORDER BY count DESC"
    
    elif "display students by housing status" in query_lower:
        return "SELECT housing_status, COUNT(*) as count FROM Students GROUP BY housing_status ORDER BY count DESC"
    
    elif "find books by subject matter" in query_lower:
        return "SELECT subject_area, COUNT(*) as count FROM Books GROUP BY subject_area ORDER BY count DESC"
    
    elif "show faculty by department affiliation" in query_lower:
        return "SELECT d.name as department, COUNT(f.id) as faculty_count FROM Faculty f JOIN Departments d ON f.department_id = d.id GROUP BY d.id, d.name ORDER BY faculty_count DESC"
    
    elif "display students by academic load" in query_lower:
        return "SELECT CASE WHEN credit_hours >= 18 THEN 'Heavy' WHEN credit_hours >= 15 THEN 'Normal' WHEN credit_hours >= 12 THEN 'Light' ELSE 'Minimal' END as academic_load, COUNT(*) as count FROM Students GROUP BY academic_load"
    
    elif "find books by genre classification" in query_lower:
        return "SELECT genre, COUNT(*) as count FROM Books GROUP BY genre ORDER BY count DESC"
    
    elif "show faculty by research area" in query_lower:
        return "SELECT research_area, COUNT(*) as count FROM Faculty GROUP BY research_area ORDER BY count DESC"
    
    elif "display students by academic performance" in query_lower:
        return "SELECT CASE WHEN gpa >= 3.8 THEN 'Excellent' WHEN gpa >= 3.5 THEN 'Good' WHEN gpa >= 3.0 THEN 'Average' ELSE 'Needs Improvement' END as performance_level, COUNT(*) as count FROM Students GROUP BY performance_level"
    
    elif "find books by literary style" in query_lower:
        return "SELECT literary_style, COUNT(*) as count FROM Books GROUP BY literary_style ORDER BY count DESC"
    
    elif "show faculty by teaching methodology" in query_lower:
        return "SELECT teaching_methodology, COUNT(*) as count FROM Faculty GROUP BY teaching_methodology ORDER BY count DESC"
    
    elif "display students by learning modality" in query_lower:
        return "SELECT learning_modality, COUNT(*) as count FROM Students GROUP BY learning_modality ORDER BY count DESC"
    
    return "SELECT * FROM Books LIMIT 10"  # Final safety fallback
