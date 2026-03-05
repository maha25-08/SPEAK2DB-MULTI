import sqlite3
from datetime import datetime, timedelta
import random

def create_individual_student_dashboards():
    """Create individual dashboard pages for each student"""
    
    # Connect to database
    conn = sqlite3.connect('library_main.db')
    cursor = conn.cursor()
    
    print('🎯 CREATING INDIVIDUAL STUDENT DASHBOARDS')
    print('=' * 60)
    
    # Get all students
    cursor.execute("SELECT id, name, roll_number, branch FROM Students")
    students = cursor.fetchall()
    print(f'Found {len(students)} students')
    
    # Create individual dashboard HTML files
    for i, (student_id, name, roll_number, branch) in enumerate(students, 1):
        print(f'\n📝 Creating dashboard for Student {i}: {name} ({roll_number}) - {branch}')
        
        # Get student-specific data
        cursor.execute("""
            SELECT i.*, b.title, b.author 
            FROM Issued i 
            JOIN Books b ON i.book_id = b.id 
            WHERE i.student_id = ? 
            ORDER BY i.issue_date DESC
        """, (student_id,))
        borrowing_history = cursor.fetchall()
        
        cursor.execute("""
            SELECT i.*, b.title, b.author, i.due_date
            FROM Issued i 
            JOIN Books b ON i.book_id = b.id 
            WHERE i.student_id = ? AND i.return_date IS NULL 
            ORDER BY i.due_date ASC
        """, (student_id,))
        current_books = cursor.fetchall()
        
        cursor.execute("""
            SELECT f.* 
            FROM Fines f 
            WHERE f.student_id = ? 
            ORDER BY f.issue_date DESC
        """, (student_id,))
        fines = cursor.fetchall()
        
        cursor.execute("""
            SELECT r.*, b.title, b.author
            FROM Reservations r 
            JOIN Books b ON r.book_id = b.id 
            WHERE r.student_id = ? 
            ORDER BY r.reservation_date DESC
        """, (student_id,))
        reservations = cursor.fetchall()
        
        # Calculate statistics
        total_borrowed = len(borrowing_history)
        current_borrowed = len(current_books)
        total_fines = len(fines)
        unpaid_fines = len([f for f in fines if f[4] == 'Unpaid'])  # status is at index 4
        pending_requests = len(reservations)
        
        stats = {
            'total_borrowed': total_borrowed,
            'current_borrowed': current_borrowed,
            'total_fines': total_fines,
            'unpaid_fines': unpaid_fines,
            'pending_requests': pending_requests
        }
        
        # Create individual dashboard HTML
        dashboard_html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{name} - Student Dashboard | Speak2DB</title>
    <link rel="stylesheet" href="/static/css/student-dashboard.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <!-- Particles Background -->
    <div class="particles" id="particles"></div>
    
    <!-- Dashboard Container -->
    <div class="dashboard-container">
        <!-- Header -->
        <header class="dashboard-header">
            <div class="header-left">
                <h1 class="brand-title">🗃️ Speak2DB</h1>
                <span class="header-subtitle">Student Dashboard</span>
            </div>
            <div class="header-center">
                <div class="student-info">
                    <div class="student-avatar">
                        <span class="avatar-icon">👤</span>
                    </div>
                    <div class="student-details">
                        <div class="student-name">{name}</div>
                        <div class="student-meta">{roll_number} | {branch}</div>
                    </div>
                </div>
            </div>
            <div class="header-right">
                <button class="header-btn" onclick="window.location.href='/minimal'">🔍 Query</button>
                <button class="header-btn" onclick="window.location.href='/logout'">🚪 Logout</button>
            </div>
        </header>
        
        <!-- Main Content -->
        <main class="dashboard-main">
            <!-- Statistics Cards -->
            <section class="stats-section">
                <div class="stats-grid">
                    <div class="stat-card stat-primary">
                        <div class="stat-icon">📚</div>
                        <div class="stat-content">
                            <div class="stat-number">{total_borrowed}</div>
                            <div class="stat-label">Total Books Borrowed</div>
                        </div>
                    </div>
                    
                    <div class="stat-card stat-success">
                        <div class="stat-icon">📖</div>
                        <div class="stat-content">
                            <div class="stat-number">{current_borrowed}</div>
                            <div class="stat-label">Currently Borrowed</div>
                        </div>
                    </div>
                    
                    <div class="stat-card stat-warning">
                        <div class="stat-icon">💰</div>
                        <div class="stat-content">
                            <div class="stat-number">{unpaid_fines}</div>
                            <div class="stat-label">Unpaid Fines</div>
                        </div>
                    </div>
                    
                    <div class="stat-card stat-info">
                        <div class="stat-icon">📋</div>
                        <div class="stat-content">
                            <div class="stat-number">{pending_requests}</div>
                            <div class="stat-label">Book Requests</div>
                        </div>
                    </div>
                </div>
            </section>
            
            <!-- Current Borrowed Books -->
            <section class="current-books-section" id="current-books">
                <div class="section-header">
                    <h2>📖 Currently Borrowed Books</h2>
                    <div class="section-count">{current_borrowed} books</div>
                </div>
                <div class="books-grid">
        """
        
        # Add current books
        if current_books:
            for book in current_books:
                dashboard_html += f"""
                    <div class="book-card current-book">
                        <div class="book-cover">
                            <span class="book-icon">📚</span>
                        </div>
                        <div class="book-info">
                            <h3 class="book-title">{book[7]}</h3>
                            <p class="book-author">by {book[8]}</p>
                            <div class="book-meta">
                                <span class="book-isbn">Book ID: {book[2]}</span>
                                <span class="due-date">Due: {book[4]}</span>
                            </div>
                        </div>
                        <div class="book-status">
                            <span class="status-badge status-current">Borrowed</span>
                        </div>
                    </div>
        """
        else:
            dashboard_html += """
                    <div class="empty-state">
                        <span class="empty-icon">📚</span>
                        <p>No books currently borrowed</p>
                    </div>
        """
        
        dashboard_html += """
                </div>
            </section>
            
            <!-- Borrowing History -->
            <section class="history-section" id="borrowing-history">
                <div class="section-header">
                    <h2>📚 Borrowing History</h2>
                    <div class="section-count">{total_borrowed} total</div>
                </div>
                <div class="history-table-wrapper">
                    <table class="history-table">
                        <thead>
                            <tr>
                                <th>Book Title</th>
                                <th>Author</th>
                                <th>Issue Date</th>
                                <th>Return Date</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
        """
        
        # Add borrowing history
        if borrowing_history:
            for record in borrowing_history:
                return_status = record[5] if record[5] else 'Not returned'
                dashboard_html += f"""
                            <tr class="history-row">
                                <td class="book-title-cell">{record[7]}</td>
                                <td>{record[8]}</td>
                                <td>{record[3]}</td>
                                <td>{return_status}</td>
                                <td>
        """
                if record[5]:
                    dashboard_html += f"""
                                    <span class="status-badge status-returned">Returned</span>
                                </td>
                            </tr>
        """
                else:
                    dashboard_html += f"""
                                    <span class="status-badge status-current">Borrowed</span>
                                </td>
                            </tr>
        """
        else:
            dashboard_html += """
                            <tr>
                                <td colspan="5" class="empty-cell">
                                    <div class="empty-state">
                                        <p>No borrowing history available</p>
                                    </div>
                                </td>
                            </tr>
        """
        
        dashboard_html += """
                        </tbody>
                    </table>
                </div>
            </section>
            
            <!-- Fines Section -->
            <section class="fines-section" id="fines">
                <div class="section-header">
                    <h2>💰 Fines & Payments</h2>
                    <div class="section-count">{total_fines} fines</div>
                </div>
                <div class="fines-grid">
        """
        
        # Add fines
        if fines:
            for fine in fines:
                status_class = "status-unpaid" if fine[4] == 'Unpaid' else "status-paid"
                dashboard_html += f"""
                    <div class="fine-card">
                        <div class="fine-header">
                            <span class="fine-amount">₹{fine[2]}</span>
                            <span class="fine-status {status_class}">
                                {fine[4]}
                            </span>
                        </div>
                        <div class="fine-details">
                            <p class="fine-reason">{fine[3]}</p>
                            <p class="fine-date">Issued: {fine[5]}</p>
                        </div>
                    </div>
        """
        else:
            dashboard_html += """
                    <div class="empty-state">
                        <span class="empty-icon">💰</span>
                        <p>No fines on record</p>
                    </div>
        """
        
        dashboard_html += """
                </div>
            </section>
            
            <!-- Book Requests Section -->
            <section class="requests-section" id="requests">
                <div class="section-header">
                    <h2>📋 Book Requests</h2>
                    <div class="section-count">{pending_requests} requests</div>
                </div>
                <div class="requests-grid">
        """
        
        # Add reservations
        if reservations:
            for request in reservations:
                dashboard_html += f"""
                    <div class="request-card">
                        <div class="request-header">
                            <span class="request-date">{request[3]}</span>
                            <span class="request-status status-pending">Pending</span>
                        </div>
                        <div class="request-details">
                            <h3 class="request-title">{request[5]}</h3>
                            <p class="request-author">by {request[6]}</p>
                        </div>
                    </div>
        """
        else:
            dashboard_html += """
                    <div class="empty-state">
                        <span class="empty-icon">📋</span>
                        <p>No book requests pending</p>
                    </div>
        """
        
        dashboard_html += """
                </div>
            </section>
        </main>
    </div>
    
    <!-- Toast Container -->
    <div id="toastContainer" class="toast-container"></div>
    
    <script>
        // Initialize particles
        function createParticles() {{
            const particlesContainer = document.getElementById('particles');
            for (let i = 0; i < 30; i++) {{
                const particle = document.createElement('div');
                particle.className = 'particle';
                particle.style.left = Math.random() * 100 + '%';
                particle.style.animationDelay = Math.random() * 10 + 's';
                particle.style.animationDuration = (10 + Math.random() * 10) + 's';
                particlesContainer.appendChild(particle);
            }}
        }}
        
        // Show toast notification
        function showToast(message, type = 'info') {{
            const toast = document.createElement('div');
            toast.className = `toast toast-${{type}}`;
            toast.textContent = message;
            document.getElementById('toastContainer').appendChild(toast);
            
            setTimeout(() => {{
                toast.classList.add('toast-hide');
                setTimeout(() => toast.remove(), 300);
            }}, 3000);
        }}
        
        // Initialize
        document.addEventListener('DOMContentLoaded', function() {{
            createParticles();
            
            // Animate stat cards on load
            const statCards = document.querySelectorAll('.stat-card');
            statCards.forEach((card, index) => {{
                setTimeout(() => {{
                    card.classList.add('animate-in');
                }}, index * 100);
            }});
            
            // Animate book cards on scroll
            const observerOptions = {{
                threshold: 0.1,
                rootMargin: '0px 0px -50px 0px'
            }};
            
            const observer = new IntersectionObserver((entries) => {{
                entries.forEach(entry => {{
                    if (entry.isIntersecting) {{
                        entry.target.classList.add('animate-in');
                    }}
                }});
            }}, observerOptions);
            
            document.querySelectorAll('.book-card, .fine-card, .request-card').forEach(card => {{
                observer.observe(card);
            }});
        }});
    </script>
</body>
</html>
        """
        
        # Write individual dashboard file
        filename = f"templates/student_dashboard_{roll_number.lower()}.html"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(dashboard_html)
        
        print(f"✅ Created: {filename}")
    
    conn.close()
    print(f'\n🎉 INDIVIDUAL DASHBOARDS CREATED: {len(students)} files')

if __name__ == "__main__":
    create_individual_student_dashboards()
