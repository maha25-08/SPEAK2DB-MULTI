"""
🔐 RBAC INTEGRATION SYSTEM
Integrates Role-Based Access Control with existing Speak2DB application
"""

import sqlite3
import json
from datetime import datetime
from flask import session, jsonify, redirect, url_for
from rbac_system_fixed import rbac, require_permission, require_role, require_min_role, apply_row_level_filter
from ollama_sql import generate_sql
from security.auth_utils import verify_stored_password

class RBACIntegration:
    """🔗 Integration layer for RBAC with existing application"""
    
    def __init__(self, db_path: str = "library_main.db"):
        self.db_path = db_path
        self.main_db = db_path
        
    def authenticate_user(self, username: str, password: str) -> tuple:
        """🔐 Authenticate user and return user_id and role"""
        try:
            conn = sqlite3.connect(self.main_db)
            cursor = conn.cursor()
            
            # Check in Users table first
            cursor.execute("SELECT username, password, role, email FROM Users WHERE username = ? OR email = ?", 
                         (username, username))
            user = cursor.fetchone()
            
            if user and verify_stored_password(user[1], password):
                user_id, role, email = user[0], user[2], user[3]
                user_type = 'user'
            else:
                conn.close()
                return None, None
            
            # Get enhanced role information
            enhanced_role = rbac.get_user_role(user_id)
            if enhanced_role:
                role = enhanced_role
            
            # Log successful login
            self._log_session_event(user_id, role, 'login', success=True)
            
            conn.close()
            
            return user_id, role
            
        except Exception as e:
            print(f"❌ Authentication error: {e}")
            return None, None
    
    def _log_session_event(self, user_id: str, role: str, action: str, success: bool = True, details: str = None):
        """📝 Log session events for audit trail"""
        try:
            conn = sqlite3.connect(self.main_db)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO SessionLog (user_id, user_role, session_id, login_time, status, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                user_id, role, session.get('session_id', 'unknown'), 
                datetime.now().isoformat(), 'Active' if success else 'Failed',
                session.get('ip_address', 'unknown'), session.get('user_agent', 'unknown')
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"❌ Session logging error: {e}")
    
    def validate_query_with_rbac(self, user_id: str, query: str) -> tuple[bool, str, str]:
        """🔍 Validate query using RBAC system"""
        try:
            # Get user role
            role = rbac.get_user_role(user_id)
            if not role:
                return False, "User role not found", ""
            
            # Validate query access
            can_execute, message = rbac.validate_query_access(user_id, query)
            if not can_execute:
                return False, message, ""
            
            # Generate SQL
            sql_query = generate_sql(query)
            
            # Apply row-level security
            filtered_sql = apply_row_level_filter(user_id, sql_query)
            
            # Log query for audit
            self._log_query_event(user_id, role, query, filtered_sql, True)
            
            return True, "Query validated and secured", filtered_sql
            
        except Exception as e:
            self._log_query_event(user_id, role if 'role' in locals() else 'unknown', query, "", False, str(e))
            return False, f"Query validation error: {str(e)}", ""
    
    def _log_query_event(self, user_id: str, role: str, query: str, sql_query: str, success: bool, error_msg: str = None):
        """📝 Log query events for audit trail"""
        try:
            conn = sqlite3.connect(self.main_db)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO QueryHistory (user_id, query, sql_query, success, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, query, sql_query, success, datetime.now().isoformat()))
            
            # Also log in AuditLog for security
            cursor.execute('''
                INSERT INTO AuditLog (user_id, user_role, action, resource_type, details, timestamp, success)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, role, 'QUERY_EXECUTION', 'SQL', f"Query: {query[:100]}", 
                  datetime.now().isoformat(), success))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"❌ Query logging error: {e}")
    
    def get_user_dashboard_data(self, user_id: str) -> dict:
        """📊 Get role-appropriate dashboard data"""
        try:
            role = rbac.get_user_role(user_id)
            if not role:
                return {'error': 'User role not found'}
            
            conn = sqlite3.connect(self.main_db)
            cursor = conn.cursor()
            
            dashboard_data = {
                'user_id': user_id,
                'role': role,
                'permissions': list(rbac.get_user_permissions(user_id)),
                'accessible_tables': list(rbac.get_accessible_tables(user_id))
            }
            
            if role == 'Student':
                # Student-specific dashboard data
                dashboard_data.update(self._get_student_dashboard(cursor, user_id))
            elif role == 'Librarian':
                # Librarian-specific dashboard data
                dashboard_data.update(self._get_librarian_dashboard(cursor))
            elif role == 'Administrator':
                # Administrator-specific dashboard data
                dashboard_data.update(self._get_administrator_dashboard(cursor))
            
            conn.close()
            return dashboard_data
            
        except Exception as e:
            print(f"❌ Dashboard data error: {e}")
            return {'error': str(e)}
    
    def _get_student_dashboard(self, cursor, user_id: str) -> dict:
        """📚 Get student dashboard data"""
        try:
            # Get student info
            cursor.execute("SELECT * FROM Students WHERE roll_number = ? OR email = ?", (user_id, user_id))
            student = cursor.fetchone()
            
            if not student:
                return {'error': 'Student not found'}
            
            # Get current issued books
            cursor.execute('''
                SELECT i.*, b.title, b.author 
                FROM Issued i 
                JOIN Books b ON i.book_id = b.id 
                WHERE i.student_id = ? AND i.return_date IS NULL
                ORDER BY i.due_date ASC
            ''', (student[0],))
            current_books = cursor.fetchall()
            
            # Get fines
            cursor.execute('''
                SELECT * FROM Fines WHERE student_id = ? AND status = 'Unpaid'
                ORDER BY issue_date DESC
            ''', (student[0],))
            unpaid_fines = cursor.fetchall()
            
            # Get reservations
            cursor.execute('''
                SELECT r.*, b.title, b.author 
                FROM Reservations r 
                JOIN Books b ON r.book_id = b.id 
                WHERE r.student_id = ? AND r.status = 'Active'
                ORDER BY r.reservation_date ASC
            ''', (student[0],))
            reservations = cursor.fetchall()
            
            return {
                'student_info': {
                    'id': student[0],
                    'roll_number': student[1],
                    'name': student[2],
                    'branch': student[3],
                    'year': student[4],
                    'email': student[5],
                    'gpa': student[7]
                },
                'current_books': current_books,
                'unpaid_fines': unpaid_fines,
                'reservations': reservations,
                'stats': {
                    'books_issued': len(current_books),
                    'unpaid_fines_count': len(unpaid_fines),
                    'active_reservations': len(reservations)
                }
            }
            
        except Exception as e:
            print(f"❌ Student dashboard error: {e}")
            return {'error': str(e)}
    
    def _get_librarian_dashboard(self, cursor) -> dict:
        """📚 Get librarian dashboard data"""
        try:
            # Get library statistics
            cursor.execute("SELECT COUNT(*) FROM Books")
            total_books = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM Books WHERE available_copies > 0")
            available_books = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM Issued WHERE return_date IS NULL")
            issued_books = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM Students")
            total_students = cursor.fetchone()[0]
            
            # Get overdue books
            cursor.execute('''
                SELECT COUNT(*) FROM Issued 
                WHERE return_date IS NULL AND date(due_date) < date('now')
            ''')
            overdue_books = cursor.fetchone()[0]
            
            # Get recent activity
            cursor.execute('''
                SELECT COUNT(*) FROM Issued 
                WHERE date(issue_date) = date('now')
            ''')
            today_issued = cursor.fetchone()[0]
            
            return {
                'library_stats': {
                    'total_books': total_books,
                    'available_books': available_books,
                    'issued_books': issued_books,
                    'overdue_books': overdue_books,
                    'total_students': total_students,
                    'today_issued': today_issued
                },
                'quick_actions': [
                    'checkout_book', 'checkin_book', 'manage_reservations',
                    'view_reports', 'manage_students', 'add_book'
                ]
            }
            
        except Exception as e:
            print(f"❌ Librarian dashboard error: {e}")
            return {'error': str(e)}
    
    def _get_administrator_dashboard(self, cursor) -> dict:
        """🏢 Get administrator dashboard data"""
        try:
            # Get system statistics
            cursor.execute("SELECT COUNT(*) FROM Users")
            total_users = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM Students")
            total_students = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM Faculty")
            total_faculty = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM Departments")
            total_departments = cursor.fetchone()[0]
            
            # Get role distribution
            cursor.execute('''
                SELECT ur.role_id, r.name, COUNT(*) as count
                FROM UserRoles ur
                JOIN Roles r ON ur.role_id = r.id
                GROUP BY ur.role_id, r.name
            ''')
            role_distribution = cursor.fetchall()
            
            # Get recent system activity
            cursor.execute('''
                SELECT COUNT(*) FROM AuditLog 
                WHERE date(timestamp) = date('now')
            ''')
            today_activities = cursor.fetchone()[0]
            
            return {
                'system_stats': {
                    'total_users': total_users,
                    'total_students': total_students,
                    'total_faculty': total_faculty,
                    'total_departments': total_departments,
                    'today_activities': today_activities
                },
                'role_distribution': dict([(name, count) for _, name, count in role_distribution]),
                'quick_actions': [
                    'manage_users', 'manage_roles', 'system_config',
                    'view_reports', 'audit_logs', 'database_maintenance'
                ]
            }
            
        except Exception as e:
            print(f"❌ Administrator dashboard error: {e}")
            return {'error': str(e)}
    
    def check_route_permission(self, required_permission: str = None, required_role: str = None, min_role_level: int = None):
        """🔐 Decorator for route permission checking"""
        def decorator(f):
            def wrapped_function(*args, **kwargs):
                # Get user ID from session
                user_id = session.get('user_id') or session.get('student_id') or session.get('faculty_id')
                if not user_id:
                    return jsonify({'error': 'Not authenticated'}), 401
                
                # Check permission
                if required_permission and not rbac.has_permission(user_id, required_permission):
                    return jsonify({'error': f'Permission denied: {required_permission} required'}), 403
                
                # Check role
                if required_role:
                    user_role = rbac.get_user_role(user_id)
                    if user_role != required_role:
                        return jsonify({'error': f'Access denied: {required_role} role required'}), 403
                
                # Check role level
                if min_role_level and not rbac.can_access_role_level(user_id, min_role_level):
                    return jsonify({'error': 'Access denied: insufficient role level'}), 403
                
                return f(*args, **kwargs)
            return wrapped_function
        return decorator
    
    def get_accessible_menu_items(self, user_id: str) -> list:
        """📋 Get menu items based on user permissions"""
        try:
            role = rbac.get_user_role(user_id)
            permissions = rbac.get_user_permissions(user_id)
            
            menu_items = {
                'Student': [
                    {'name': 'Dashboard', 'url': '/dashboard', 'icon': 'dashboard', 'permission': None},
                    {'name': 'Search Books', 'url': '/search', 'icon': 'search', 'permission': 'search_books'},
                    {'name': 'My Books', 'url': '/my-books', 'icon': 'book', 'permission': 'view_my_loans'},
                    {'name': 'My Fines', 'url': '/my-fines', 'icon': 'payment', 'permission': 'view_my_fines'},
                    {'name': 'Profile', 'url': '/profile', 'icon': 'person', 'permission': 'view_my_profile'}
                ],
                'Librarian': [
                    {'name': 'Dashboard', 'url': '/dashboard', 'icon': 'dashboard', 'permission': None},
                    {'name': 'Manage Books', 'url': '/manage-books', 'icon': 'library_books', 'permission': 'manage_books'},
                    {'name': 'Circulation', 'url': '/circulation', 'icon': 'swap_horiz', 'permission': 'checkout_books'},
                    {'name': 'Students', 'url': '/students', 'icon': 'people', 'permission': 'manage_student_accounts'},
                    {'name': 'Reports', 'url': '/reports', 'icon': 'assessment', 'permission': 'view_circulation_reports'},
                    {'name': 'Reservations', 'url': '/reservations', 'icon': 'bookmark', 'permission': 'manage_reservations'}
                ],
                'Administrator': [
                    {'name': 'Dashboard', 'url': '/dashboard', 'icon': 'dashboard', 'permission': None},
                    {'name': 'User Management', 'url': '/users', 'icon': 'manage_accounts', 'permission': 'manage_roles'},
                    {'name': 'System Config', 'url': '/config', 'icon': 'settings', 'permission': 'configure_system'},
                    {'name': 'Departments', 'url': '/departments', 'icon': 'account_balance', 'permission': 'manage_departments'},
                    {'name': 'Faculty', 'url': '/faculty', 'icon': 'school', 'permission': 'manage_faculty_records'},
                    {'name': 'Audit Logs', 'url': '/audit', 'icon': 'security', 'permission': 'audit_trail'},
                    {'name': 'Reports', 'url': '/reports', 'icon': 'analytics', 'permission': 'view_institutional_metrics'}
                ]
            }
            
            # Filter menu items based on permissions
            if role in menu_items:
                accessible_items = []
                for item in menu_items[role]:
                    if item['permission'] is None or item['permission'] in permissions:
                        accessible_items.append(item)
                return accessible_items
            
            return []
            
        except Exception as e:
            print(f"❌ Menu generation error: {e}")
            return []
    
    def get_user_info(self, user_id: str) -> dict:
        """👤 Get comprehensive user information"""
        try:
            conn = sqlite3.connect(self.main_db)
            cursor = conn.cursor()
            
            # Check in Users table first
            cursor.execute("SELECT username, role, email FROM Users WHERE username = ?", (user_id,))
            user = cursor.fetchone()
            
            if user:
                username, role, email = user
                user_type = 'user'
            else:
                # Check in Students table
                cursor.execute("SELECT roll_number, name, email, role FROM Students WHERE roll_number = ? OR email = ?", 
                             (user_id, user_id))
                student = cursor.fetchone()
                
                if student:
                    roll_number, name, email, role = student
                    username = roll_number
                    user_type = 'student'
                else:
                    # Check in Faculty table
                    cursor.execute("SELECT name, email FROM Faculty WHERE email = ?", (user_id,))
                    faculty = cursor.fetchone()
                    
                    if faculty:
                        name, email = faculty
                        username = email
                        role = 'Librarian'
                        user_type = 'faculty'
                    else:
                        conn.close()
                        return {'error': 'User not found'}
            
            # Get enhanced role information
            enhanced_role = rbac.get_user_role(user_id)
            if enhanced_role:
                role = enhanced_role
            
            # Get user permissions
            permissions = rbac.get_user_permissions(user_id)
            
            conn.close()
            
            return {
                'user_id': user_id,
                'username': username,
                'role': role,
                'user_type': user_type,
                'email': email,
                'permissions': permissions,
                'display_name': username if user_type == 'user' else name if user_type == 'student' else email
            }
            
        except Exception as e:
            print(f"❌ User info error: {e}")
            return {'error': 'Failed to get user info'}
    
    def get_dashboard_data(self, user_id: str) -> dict:
        """📊 Get dashboard data based on user role"""
        try:
            user_info = self.get_user_info(user_id)
            role = user_info.get('role', 'Student')
            
            conn = sqlite3.connect(self.main_db)
            cursor = conn.cursor()
            
            dashboard_data = {
                'user_info': user_info,
                'role': role,
                'stats': {},
                'recent_activity': [],
                'quick_actions': []
            }
            
            if role == 'Student':
                # Student-specific data
                cursor.execute("SELECT COUNT(*) FROM Issued WHERE student_id = ?", (user_id,))
                issued_count = cursor.fetchone()[0]
                
                cursor.execute("""
                    SELECT COUNT(*) FROM Fines f 
                    WHERE f.student_id = ? AND f.status = 'unpaid'
                """, (user_id,))
                fine_count = cursor.fetchone()[0]
                
                dashboard_data['stats'] = {
                    'issued_books': issued_count,
                    'unpaid_fines': fine_count,
                    'total_books': 15  # From Books table
                }
                
                # Recent issued books
                cursor.execute("""
                    SELECT b.title, i.issue_date, i.due_date 
                    FROM Issued i 
                    JOIN Books b ON i.book_id = b.id 
                    WHERE i.student_id = ? 
                    ORDER BY i.issue_date DESC 
                    LIMIT 5
                """, (user_id,))
                recent_books = cursor.fetchall()
                
                dashboard_data['recent_activity'] = [
                    {'title': book[0], 'issued': book[1], 'due': book[2]} 
                    for book in recent_books
                ]
                
            elif role == 'Librarian':
                # Librarian-specific data
                cursor.execute("SELECT COUNT(*) FROM Books")
                total_books = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM Students")
                total_students = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM Issued WHERE return_date IS NULL")
                active_issues = cursor.fetchone()[0]
                
                dashboard_data['stats'] = {
                    'total_books': total_books,
                    'total_students': total_students,
                    'active_issues': active_issues
                }
                
            elif role == 'Administrator':
                # Admin-specific data
                cursor.execute("SELECT COUNT(*) FROM Users")
                total_users = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM SecurityLog WHERE timestamp >= date('now', '-7 days')")
                security_events = cursor.fetchone()[0]
                
                dashboard_data['stats'] = {
                    'total_users': total_users,
                    'security_events': security_events,
                    'system_health': 'Good'
                }
            
            conn.close()
            return dashboard_data
            
        except Exception as e:
            print(f"❌ Dashboard data error: {e}")
            return {'error': 'Failed to get dashboard data'}
    
    def get_ui_config(self, role: str) -> dict:
        """🎨 Get UI configuration based on user role"""
        try:
            # Import UI configuration
            from ui_rbac_system import RoleBasedUI
            ui_system = RoleBasedUI()
            # Get UI config for a sample user with this role
            sample_user_id = 'student' if role == 'Student' else 'librarian' if role == 'Librarian' else 'admin'
            return ui_system.get_user_ui_config(sample_user_id)
        except Exception as e:
            print(f"❌ UI config error: {e}")
            # Fallback basic configuration
            return {
                'theme': 'default',
                'layout': 'default',
                'components': ['dashboard', 'search', 'profile']
            }

# Global RBAC integration instance
rbac_integration = RBACIntegration()
