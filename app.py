"""
🗃️ SPEAK2DB - ORIGINAL WORKING SYSTEM
Exactly as it was yesterday - with all features working
"""

from flask import Flask, render_template, request, jsonify, session, flash, redirect, url_for
import sqlite3
import os
from ollama_sql import generate_sql
import pandas as pd
import os
import re
from collections import Counter
from datetime import datetime

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'

# Database paths
MAIN_DB = "library_main.db"
ARCHIVE_DB = "library_archive.db"

def get_db_connection(db_path):
    """Get database connection"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

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
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    """Logout user"""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/')
def index():
    """Main dashboard"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    user_role = session.get('role', 'Student')
    
    user_info = {
        'username': user_id,
        'role': user_role,
        'permissions': []
    }
    
    return render_template('index.html', 
                         user=user_info.get('username', user_id),
                         role=user_role,
                         user_info=user_info)

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
            SELECT i.*, b.title, b.author, b.isbn 
            FROM Issued i 
            JOIN Books b ON i.book_id = b.id 
            WHERE i.student_id = ? 
            ORDER BY i.issue_date DESC
        """, (student_id,)).fetchall()
        print(f"[DEBUG] Borrowing History: {len(borrowing_history)} records")
        
        # Get current borrowed books
        current_books = conn.execute("""
            SELECT i.*, b.title, b.author, b.isbn, i.due_date
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
    return render_template(template_name)

@app.route('/query', methods=['POST'])
def query():
    """Query handling with row-based filtering for students"""
    print("🔍 Query received - Processing request")
    
    if 'user_id' not in session:
        print("❌ User not logged in")
        return jsonify({'error': 'Not logged in'}), 401
    
    try:
        data = request.get_json()
        user_query = data.get('query', '').strip()
        print(f"📝 Query text: {user_query}")
        
        user_role = session.get('role', 'Student')
        student_id = session.get('student_id')  # Get student ID for filtering
        print(f"👤 User role: {user_role}, Student ID: {student_id}")
        
        if not user_query:
            print("❌ No query provided")
            return jsonify({'error': 'No query provided'}), 400
        
        print("🔗 Connecting to database...")
        conn = get_db_connection(MAIN_DB)
        
        print("🤖 Generating SQL query...")
        # Use AI-powered SQL generation
        sql_query = generate_sql(user_query)
        print(f"⚙️ Generated SQL: {sql_query}")
        
        # Replace student ID placeholders in SQL
        if user_role == 'Student' and student_id:
            sql_query = sql_query.replace('[CURRENT_STUDENT_ID]', str(student_id))
        
        # Apply row-based filtering for students
        if user_role == 'Student' and student_id:
            # Filter queries to show only student's own data
            original_sql = sql_query
            
            # Comprehensive student-specific patterns
            if 'students' in sql_query.lower() and 'WHERE' not in sql_query.upper():
                sql_query += f" WHERE id = {student_id}"
            elif 'issued' in sql_query.lower() and 'WHERE' not in sql_query.upper():
                sql_query += f" WHERE student_id = {student_id}"
            elif 'fines' in sql_query.lower() and 'WHERE' not in sql_query.upper():
                sql_query += f" WHERE student_id = {student_id}"
            elif 'my' in user_query.lower() or 'what books have i' in user_query.lower() or 'show me my' in user_query.lower() or 'display my' in user_query.lower() or 'what books do i' in user_query.lower() or 'books i have' in user_query.lower():
                # Student-specific query patterns
                if 'my fines' in user_query.lower():
                    sql_query = f"SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id WHERE f.student_id = {student_id} ORDER BY f.issue_date DESC"
                elif 'my fine' in user_query.lower():
                    sql_query = f"SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id WHERE f.student_id = {student_id} ORDER BY f.issue_date DESC"
                elif 'my fine records' in user_query.lower():
                    sql_query = f"SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id WHERE f.student_id = {student_id} ORDER BY f.issue_date DESC"
                elif 'my current fines' in user_query.lower():
                    sql_query = f"SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id WHERE f.student_id = {student_id} AND f.status = 'Unpaid' ORDER BY f.issue_date DESC"
                elif 'my unpaid fines' in user_query.lower():
                    sql_query = f"SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id WHERE f.student_id = {student_id} AND f.status = 'Unpaid' ORDER BY f.issue_date DESC"
                elif 'my books' in user_query.lower():
                    sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                elif 'my issued books' in user_query.lower():
                    sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                elif 'my borrowed books' in user_query.lower():
                    sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                elif 'my current books' in user_query.lower():
                    sql_query = f"SELECT i.*, b.title, b.author, i.due_date FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} AND i.return_date IS NULL ORDER BY i.due_date ASC"
                elif 'my overdue books' in user_query.lower():
                    sql_query = f"SELECT i.*, b.title, b.author, julianday(date('now') - julianday(i.due_date)) as days_overdue FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} AND i.return_date IS NULL AND i.due_date < date('now')"
                elif 'my borrowing history' in user_query.lower():
                    sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                elif 'my reading history' in user_query.lower():
                    sql_query = f"SELECT b.title, b.author, i.issue_date, i.return_date FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                elif 'my library account' in user_query.lower():
                    sql_query = f"SELECT s.name, s.email, COUNT(f.id) as fine_count, SUM(f.fine_amount) as total_balance FROM Students s LEFT JOIN Fines f ON s.id = f.student_id WHERE s.id = {student_id} AND f.status = 'Unpaid' GROUP BY s.id, s.name"
                elif 'my library account balance' in user_query.lower():
                    sql_query = f"SELECT s.name, SUM(f.fine_amount) as total_balance FROM Students s LEFT JOIN Fines f ON s.id = f.student_id WHERE s.id = {student_id} AND f.status = 'Unpaid' GROUP BY s.id, s.name"
                elif 'my profile' in user_query.lower():
                    sql_query = f"SELECT s.*, d.name as department_name FROM Students s JOIN Departments d ON s.branch = d.id WHERE s.id = {student_id}"
                elif 'my student info' in user_query.lower():
                    sql_query = f"SELECT s.*, d.name as department_name FROM Students s JOIN Departments d ON s.branch = d.id WHERE s.id = {student_id}"
                elif 'my account details' in user_query.lower():
                    sql_query = f"SELECT s.*, d.name as department_name FROM Students s JOIN Departments d ON s.branch = d.id WHERE s.id = {student_id}"
                elif 'my academic performance' in user_query.lower():
                    sql_query = f"SELECT gpa, attendance, role, created_date FROM Students s WHERE s.id = {student_id}"
                elif 'my gpa' in user_query.lower():
                    sql_query = f"SELECT gpa FROM Students s WHERE s.id = {student_id}"
                elif 'my attendance' in user_query.lower():
                    sql_query = f"SELECT attendance FROM Students s WHERE s.id = {student_id}"
                elif 'my reserved books' in user_query.lower():
                    sql_query = f"SELECT r.*, b.title, b.author FROM Reservations r JOIN Books b ON r.book_id = b.id WHERE r.student_id = {student_id} ORDER BY r.reservation_date DESC"
                elif 'my reservations' in user_query.lower():
                    sql_query = f"SELECT r.*, b.title, b.author FROM Reservations r JOIN Books b ON r.book_id = b.id WHERE r.student_id = {student_id} ORDER BY r.reservation_date DESC"
                elif 'my account' in user_query.lower():
                    sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                
                # Handle the specific "what books have i borrowed" pattern
                elif 'what books have i borrowed' in user_query.lower():
                    sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                elif 'what books have i taken' in user_query.lower():
                    sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                elif 'what books do i have' in user_query.lower():
                    sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                elif 'books i have borrowed' in user_query.lower():
                    sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                elif 'what books do i have' in user_query.lower():
                    sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                
                # Additional comprehensive patterns
                elif 'show me my' in user_query.lower():
                    if 'fines' in user_query.lower():
                        sql_query = f"SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id WHERE f.student_id = {student_id} ORDER BY f.issue_date DESC"
                    elif 'books' in user_query.lower():
                        sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                    elif 'profile' in user_query.lower():
                        sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                    elif 'account' in user_query.lower():
                        sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                
                elif 'display my' in user_query.lower():
                    if 'fines' in user_query.lower():
                        sql_query = f"SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id WHERE f.student_id = {student_id} ORDER BY f.issue_date DESC"
                    elif 'books' in user_query.lower():
                        sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                    elif 'profile' in user_query.lower():
                        sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                
                elif 'what are my' in user_query.lower():
                    if 'fines' in user_query.lower():
                        sql_query = f"SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id WHERE f.student_id = {student_id} ORDER BY f.issue_date DESC"
                    elif 'books' in user_query.lower():
                        sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                    elif 'grades' in user_query.lower():
                        sql_query = f"SELECT gpa, attendance, role, created_date FROM Students s WHERE s.id = {student_id}"
                
                elif 'how much do i' in user_query.lower():
                    if 'owe' in user_query.lower():
                        sql_query = f"SELECT s.name, SUM(f.fine_amount) as total_balance FROM Students s LEFT JOIN Fines f ON s.id = f.student_id WHERE s.id = {student_id} AND f.status = 'Unpaid' GROUP BY s.id, s.name"
                    elif 'have' in user_query.lower():
                        sql_query = f"SELECT COUNT(i.id) as book_count FROM Issued i WHERE i.student_id = {student_id} AND i.return_date IS NULL"
                
                elif 'what books have i' in user_query.lower():
                    if 'borrowed' in user_query.lower():
                        sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                    elif 'have' in user_query.lower():
                        sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} AND i.return_date IS NULL ORDER BY i.due_date ASC"
                    elif 'borrow' in user_query.lower():
                        sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                
                elif 'when are my' in user_query.lower():
                    if 'books' in user_query.lower() and 'due' in user_query.lower():
                        sql_query = f"SELECT i.*, b.title, b.author, i.due_date FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} AND i.return_date IS NULL ORDER BY i.due_date ASC"
                
                elif 'tell me about' in user_query.lower():
                    if 'myself' in user_query.lower():
                        sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                    elif 'my' in user_query.lower():
                        if 'academic' in user_query.lower():
                            sql_query = f"SELECT gpa, attendance, role, created_date FROM Students s WHERE s.id = {student_id}"
                        elif 'profile' in user_query.lower():
                            sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                        elif 'account' in user_query.lower():
                            sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                
                elif 'do i have' in user_query.lower():
                    if 'fines' in user_query.lower():
                        sql_query = f"SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id WHERE f.student_id = {student_id} AND f.status = 'Unpaid' ORDER BY f.issue_date DESC"
                    elif 'books' in user_query.lower():
                        sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} AND i.return_date IS NULL ORDER BY i.due_date ASC"
                    elif 'reservations' in user_query.lower():
                        sql_query = f"SELECT r.*, b.title, b.author FROM Reservations r JOIN Books b ON r.book_id = b.id WHERE r.student_id = {student_id} ORDER BY r.reservation_date DESC"
                
                elif 'am i' in user_query.lower():
                    if 'overdue' in user_query.lower():
                        sql_query = f"SELECT i.*, b.title, b.author, julianday(date('now') - julianday(i.due_date)) as days_overdue FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} AND i.return_date IS NULL AND i.due_date < date('now')"
                    elif 'eligible' in user_query.lower():
                        sql_query = f"SELECT s.*, d.name as department_name FROM Students s JOIN Departments d ON s.branch = d.id WHERE s.id = {student_id}"
                
                elif 'my total' in user_query.lower():
                    if 'fines' in user_query.lower():
                        sql_query = f"SELECT s.name, SUM(f.fine_amount) as total_balance FROM Students s LEFT JOIN Fines f ON s.id = f.student_id WHERE s.id = {student_id} AND f.status = 'Unpaid' GROUP BY s.id, s.name"
                    elif 'books' in user_query.lower():
                        sql_query = f"SELECT COUNT(i.id) as total_books FROM Issued i WHERE i.student_id = {student_id}"
                
                elif 'my outstanding' in user_query.lower():
                    if 'fines' in user_query.lower():
                        sql_query = f"SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id WHERE f.student_id = {student_id} AND f.status = 'Unpaid' ORDER BY f.issue_date DESC"
                    elif 'balance' in user_query.lower():
                        sql_query = f"SELECT s.name, SUM(f.fine_amount) as total_balance FROM Students s LEFT JOIN Fines f ON s.id = f.student_id WHERE s.id = {student_id} AND f.status = 'Unpaid' GROUP BY s.id, s.name"
                
                elif 'my payment' in user_query.lower():
                    if 'history' in user_query.lower():
                        sql_query = f"SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id WHERE f.student_id = {student_id} ORDER BY f.issue_date DESC"
                    elif 'records' in user_query.lower():
                        sql_query = f"SELECT f.*, s.name as student_name FROM Fines f JOIN Students s ON f.student_id = s.id WHERE f.student_id = {student_id} ORDER BY f.issue_date DESC"
                
                elif 'my library' in user_query.lower():
                    if 'status' in user_query.lower():
                        sql_query = f"SELECT s.name, s.email, COUNT(f.id) as fine_count, SUM(f.fine_amount) as total_balance FROM Students s LEFT JOIN Fines f ON s.id = f.student_id WHERE s.id = {student_id} AND f.status = 'Unpaid' GROUP BY s.id, s.name"
                    elif 'record' in user_query.lower():
                        sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                    elif 'history' in user_query.lower():
                        sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                
                elif 'my student' in user_query.lower():
                    if 'record' in user_query.lower():
                        sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                    elif 'information' in user_query.lower():
                        sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                    elif 'details' in user_query.lower():
                        sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                
                elif 'my personal' in user_query.lower():
                    if 'information' in user_query.lower():
                        sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                    elif 'details' in user_query.lower():
                        sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                    elif 'data' in user_query.lower():
                        sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                
                elif 'my current' in user_query.lower():
                    if 'status' in user_query.lower():
                        sql_query = f"SELECT s.name, s.email, COUNT(f.id) as fine_count, SUM(f.fine_amount) as total_balance FROM Students s LEFT JOIN Fines f ON s.id = f.student_id WHERE s.id = {student_id} AND f.status = 'Unpaid' GROUP BY s.id, s.name"
                    elif 'semester' in user_query.lower():
                        sql_query = f"SELECT gpa, attendance, role, created_date FROM Students s WHERE s.id = {student_id}"
                    elif 'year' in user_query.lower():
                        sql_query = f"SELECT gpa, attendance, role, created_date FROM Students s WHERE s.id = {student_id}"
                
                elif 'my academic' in user_query.lower():
                    if 'record' in user_query.lower():
                        sql_query = f"SELECT gpa, attendance, role, created_date FROM Students s WHERE s.id = {student_id}"
                    elif 'standing' in user_query.lower():
                        sql_query = f"SELECT gpa, attendance, role, created_date FROM Students s WHERE s.id = {student_id}"
                    elif 'details' in user_query.lower():
                        sql_query = f"SELECT gpa, attendance, role, created_date FROM Students s WHERE s.id = {student_id}"
                
                elif 'my course' in user_query.lower():
                    if 'materials' in user_query.lower():
                        sql_query = f"SELECT i.*, b.title, b.author FROM Issued i JOIN Books b ON i.book_id = b.id WHERE i.student_id = {student_id} ORDER BY i.issue_date DESC"
                    elif 'information' in user_query.lower():
                        sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                
                elif 'my enrollment' in user_query.lower():
                    if 'status' in user_query.lower():
                        sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                    elif 'details' in user_query.lower():
                        sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                
                elif 'my class' in user_query.lower():
                    if 'schedule' in user_query.lower():
                        sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                    elif 'information' in user_query.lower():
                        sql_query = f"SELECT * FROM Students WHERE id = {student_id}"
                
                elif 'my semester' in user_query.lower():
                    if 'results' in user_query.lower():
                        sql_query = f"SELECT gpa, attendance, role, created_date FROM Students s WHERE s.id = {student_id}"
                    elif 'performance' in user_query.lower():
                        sql_query = f"SELECT gpa, attendance, role, created_date FROM Students s WHERE s.id = {student_id}"
                    elif 'grades' in user_query.lower():
                        sql_query = f"SELECT gpa, attendance, role, created_date FROM Students s WHERE s.id = {student_id}"
        
        print(f"[EXECUTING SQL] {sql_query}")
        results = conn.execute(sql_query).fetchall()
        conn.close()
        
        data = [dict(row) for row in results]
        
        # Extract columns dynamically
        if data:
            columns = list(data[0].keys())
        else:
            # Get columns from table info
            if 'books' in sql_query.lower():
                columns = ['id', 'title', 'author', 'isbn', 'genre', 'status', 'created_date']
            elif 'users' in sql_query.lower():
                columns = ['id', 'username', 'email', 'role', 'created_date']
            elif 'students' in sql_query.lower():
                columns = ['id', 'roll_number', 'name', 'branch', 'year', 'email', 'phone', 'role', 'gpa']
            elif 'faculty' in sql_query.lower():
                columns = ['id', 'name', 'email', 'department', 'created_date']
            elif 'fines' in sql_query.lower():
                columns = ['id', 'student_id', 'amount', 'status', 'due_date', 'created_date']
            elif 'issued' in sql_query.lower():
                columns = ['id', 'student_id', 'book_id', 'issue_date', 'due_date', 'return_date']
            else:
                columns = ['id', 'name', 'created_date']
        
        print(f"📊 Returning {len(data)} rows with columns: {columns}")
        
        response_data = {
            'success': True,
            'data': data,
            'columns': columns,
            'sql': sql_query,
            'user_role': user_role,
            'student_id': student_id
        }
        
        print("✅ Query completed successfully")
        return jsonify(response_data)
        
    except Exception as e:
        print(f"❌ Query execution failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Query execution failed: {str(e)}'}), 500

# API endpoints
@app.route('/api/user-info')
def api_user_info():
    """Get user information"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    return jsonify({
        'username': user_id,
        'role': user_role,
        'student_id': session.get('student_id')
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
