"""
🔐 ROLE-BASED ACCESS CONTROL (RBAC) SYSTEM
Comprehensive permissions framework for Speak2DB
"""

import sqlite3
import re
from typing import Dict, List, Set, Tuple, Optional
from functools import wraps
from flask import session, jsonify

class RBACSystem:
    """🛡️ Role-Based Access Control System"""
    
    def __init__(self, db_path: str = "library_main.db"):
        self.db_path = db_path
        self.roles = {
            'Student': 1,
            'Faculty': 2,
            'Librarian': 2, 
            'Administrator': 3
        }
        self.permissions = self._define_permissions()
        
    def _define_permissions(self) -> Dict[str, Dict[str, Set[str]]]:
        """📋 Define comprehensive permissions matrix"""
        return {
            'Student': {
                # 📚 Library Access
                'library_access': {
                    'search_books', 'view_book_details', 'check_availability',
                    'view_catalog', 'browse_categories'
                },
                # 📖 Personal Borrowing
                'personal_borrowing': {
                    'view_my_loans', 'view_my_history', 'view_my_reservations',
                    'renew_my_books', 'reserve_books', 'view_due_dates'
                },
                # 💳 Financial Management
                'financial_management': {
                    'view_my_fines', 'view_my_payments', 'view_fine_details'
                },
                # 👤 Account Management
                'account_management': {
                    'view_my_profile', 'update_my_profile', 'view_my_academic_info'
                },
                # 📊 Personal Analytics
                'personal_analytics': {
                    'view_my_statistics', 'view_my_reading_history',
                    'view_my_recommendations', 'view_my_borrowing_patterns'
                }
            },
            'Librarian': {
                # 📚 Library Operations (inherits all Student permissions)
                'library_operations': {
                    'manage_books', 'add_books', 'edit_books', 'delete_books',
                    'manage_inventory', 'process_acquisitions', 'catalog_maintenance',
                    'manage_weeding', 'manage_special_collections'
                },
                # 🔄 Circulation Management
                'circulation_management': {
                    'checkout_books', 'checkin_books', 'manage_renewals',
                    'manage_reservations', 'manage_overdue', 'calculate_fines',
                    'process_payments'
                },
                # 👥 User Management
                'user_management': {
                    'manage_student_accounts', 'manage_faculty_accounts',
                    'manage_memberships', 'set_permissions', 'suspend_accounts'
                },
                # 📊 Library Analytics
                'library_analytics': {
                    'view_circulation_reports', 'view_popular_books',
                    'view_user_statistics', 'view_inventory_reports',
                    'view_performance_metrics', 'export_reports'
                },
                # 🔧 System Operations
                'system_operations': {
                    'manage_interlibrary_loans', 'manage_book_repairs',
                    'process_lost_books', 'manage_digital_resources'
                }
            },
            'Faculty': {
                # 👨‍🏫 Faculty access mirrors librarian-grade read/analytics access
                'library_operations': {
                    'manage_books', 'add_books', 'edit_books', 'delete_books',
                    'manage_inventory', 'process_acquisitions', 'catalog_maintenance',
                    'manage_weeding', 'manage_special_collections'
                },
                'circulation_management': {
                    'checkout_books', 'checkin_books', 'manage_renewals',
                    'manage_reservations', 'manage_overdue', 'calculate_fines',
                    'process_payments'
                },
                'user_management': {
                    'manage_student_accounts', 'manage_faculty_accounts',
                    'manage_memberships', 'set_permissions', 'suspend_accounts'
                },
                'library_analytics': {
                    'view_circulation_reports', 'view_popular_books',
                    'view_user_statistics', 'view_inventory_reports',
                    'view_performance_metrics', 'export_reports'
                },
                'system_operations': {
                    'manage_interlibrary_loans', 'manage_book_repairs',
                    'process_lost_books', 'manage_digital_resources'
                }
            },
            'Administrator': {
                # 🔐 System Administration (inherits all Librarian permissions)
                'system_administration': {
                    'manage_roles', 'configure_system', 'manage_database',
                    'manage_security', 'manage_integrations', 'system_maintenance'
                },
                # 👨‍🏫 Faculty Management
                'faculty_management': {
                    'manage_faculty_records', 'manage_departments',
                    'track_performance', 'manage_research', 'manage_workload'
                },
                # 🏛️ Department Administration
                'department_administration': {
                    'manage_departments', 'manage_budgets', 'manage_programs',
                    'handle_accreditation', 'coordinate_departments'
                },
                # 💰 Financial Oversight
                'financial_oversight': {
                    'manage_budgets', 'financial_reporting', 'manage_expenses',
                    'manage_grants', 'manage_scholarships', 'financial_planning'
                },
                # 📊 Enterprise Analytics
                'enterprise_analytics': {
                    'view_institutional_metrics', 'strategic_planning',
                    'compliance_reporting', 'executive_dashboards',
                    'predictive_analytics'
                },
                # ⚙️ Technical Control
                'technical_control': {
                    'system_maintenance', 'data_migration', 'api_management',
                    'performance_monitoring', 'audit_trail'
                },
                # 🔒 Security Administration
                'security_administration': {
                    'manage_security_policies', 'configure_firewall', 'manage_encryption',
                    'security_audit', 'incident_response', 'backup_management',
                    'access_control', 'session_management', 'token_management'
                },
                # 🗄️ Database Administration
                'database_administration': {
                    'create_databases', 'drop_databases', 'backup_databases',
                    'restore_databases', 'migrate_data', 'schema_management',
                    'query_optimization', 'index_management', 'purge_logs'
                },
                # 👥 Advanced User Management
                'advanced_user_management': {
                    'bulk_user_operations', 'user_import_export', 'account_suspension',
                    'role_modification', 'permission_revocation', 'user_deletion'
                },
                # 🏛️ System Configuration
                'system_configuration': {
                    'modify_system_settings', 'configure_integrations', 'manage_modules',
                    'custom_permissions', 'system_diagnostics', 'emergency_controls'
                },
                # 📊 System Monitoring
                'system_monitoring': {
                    'view_system_logs', 'monitor_performance', 'resource_usage',
                    'error_tracking', 'security_alerts', 'compliance_monitoring'
                }
            }
        }
    
    def get_user_role(self, user_id: str) -> Optional[str]:
        """👤 Get user role from database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # First check UserRoles table for explicit role assignment
            cursor.execute("""
                SELECT r.name FROM UserRoles ur
                JOIN Roles r ON ur.role_id = r.id
                WHERE ur.user_id = ? AND ur.status = 'Active'
                ORDER BY r.level DESC
                LIMIT 1
            """, (user_id,))
            result = cursor.fetchone()
            
            if result:
                role_name = result[0]
                # Map role names to standard format
                role_mapping = {
                    'Admin': 'Administrator'
                }
                return role_mapping.get(role_name, role_name)
            
            # Fallback to checking Users table
            cursor.execute("SELECT role FROM Users WHERE username = ? OR email = ?", 
                         (user_id, user_id))
            result = cursor.fetchone()
            
            if result:
                role_name = result[0]
                role_mapping = {
                    'Admin': 'Administrator'
                }
                return role_mapping.get(role_name, role_name)
            
            # Check in Students table
            cursor.execute("SELECT role FROM Students WHERE roll_number = ? OR email = ?", 
                         (user_id, user_id))
            result = cursor.fetchone()
            
            if result:
                return result[0]
            
            # Check in Faculty table
            cursor.execute("SELECT 'Librarian' as role FROM Faculty WHERE email = ?", (user_id,))
            result = cursor.fetchone()
            
            if result:
                return result[0]
                
            return None
            
        except Exception as e:
            print(f"❌ Error getting user role: {e}")
            return None
        finally:
            conn.close()
    
    def get_user_permissions(self, user_id: str) -> Set[str]:
        """🔑 Get all permissions for a user"""
        role = self.get_user_role(user_id)
        if not role:
            return set()
        
        permissions = set()
        db_permissions = self._get_db_role_permissions(role)
        
        # Add role-specific permissions
        if role in self.permissions:
            for category_perms in self.permissions[role].values():
                permissions.update(category_perms)
        
        # Add inherited permissions (Student < Librarian/Faculty < Administrator)
        if role in ('Librarian', 'Faculty'):
            # Inherit all Student permissions
            for category_perms in self.permissions['Student'].values():
                permissions.update(category_perms)
        elif role == 'Administrator':
            # Inherit all Student and Librarian permissions
            for base_role in ['Student', 'Librarian', 'Faculty']:
                for category_perms in self.permissions[base_role].values():
                    permissions.update(category_perms)
            # Add admin permissions
            for category_perms in self.permissions['Administrator'].values():
                permissions.update(category_perms)

        # Merge DB-backed role permissions for admin-managed overrides/extensions
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            role_scope = 'Librarian' if role == 'Faculty' else role
            cursor.execute(
                '''
                SELECT p.name
                FROM Roles r
                JOIN RolePermissions rp ON rp.role_id = r.id
                JOIN Permissions p ON p.id = rp.permission_id
                WHERE r.name = ?
                ''',
                (role_scope,),
            )
            permissions.update(row[0] for row in cursor.fetchall())
        except Exception as e:
            print(f"❌ Error getting DB permissions: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass
        
        return permissions

    def _get_db_role_permissions(self, role: str) -> Set[str]:
        """Read DB-backed permissions assigned to a role."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.name
                FROM Permissions p
                JOIN RolePermissions rp ON rp.permission_id = p.id
                JOIN Roles r ON r.id = rp.role_id
                WHERE r.name = ?
            """, (role,))
            rows = cursor.fetchall()
            return {row[0] for row in rows}
        except Exception:
            return set()
        finally:
            try:
                conn.close()
            except Exception:
                pass
    
    def has_permission(self, user_id: str, permission: str) -> bool:
        """✅ Check if user has specific permission"""
        user_permissions = self.get_user_permissions(user_id)
        return permission in user_permissions
    
    def has_any_permission(self, user_id: str, permissions: List[str]) -> bool:
        """✅ Check if user has any of the specified permissions"""
        user_permissions = self.get_user_permissions(user_id)
        return any(perm in user_permissions for perm in permissions)
    
    def has_all_permissions(self, user_id: str, permissions: List[str]) -> bool:
        """✅ Check if user has all specified permissions"""
        user_permissions = self.get_user_permissions(user_id)
        return all(perm in user_permissions for perm in permissions)
    
    def get_role_level(self, role: str) -> int:
        """📊 Get hierarchical level of role"""
        return self.roles.get(role, 0)
    
    def can_access_role_level(self, user_id: str, required_level: int) -> bool:
        """🔐 Check if user can access certain role level"""
        role = self.get_user_role(user_id)
        if not role:
            return False
        return self.get_role_level(role) >= required_level
    
    def get_accessible_tables(self, user_id: str) -> Set[str]:
        """📊 Get tables user can access based on role"""
        role = self.get_user_role(user_id)
        if not role:
            return set()
        
        # Define table access by role
        table_access = {
            'Student': {
                'Books', 'Issued', 'Fines', 'Reservations', 'Students'
            },
            'Faculty': {
                'Books', 'Issued', 'Fines', 'Reservations', 'Students',
                'Users', 'Publishers', 'Departments', 'QueryHistory',
                'SpecialPermissions', 'Faculty'
            },
            'Librarian': {
                'Books', 'Issued', 'Fines', 'Reservations', 'Students',
                'Users', 'Publishers', 'Departments', 'QueryHistory',
                'SpecialPermissions', 'Faculty'
            },
            'Administrator': {
                # Administration and monitoring tables
                'Books', 'Issued', 'Fines', 'Reservations', 'Students',
                'Users', 'Publishers', 'Departments', 'QueryHistory',
                'SpecialPermissions', 'Faculty', 'ActivityLogs', 'AuditLog',
                'AuditTrail', 'DataAccessLog', 'FailedLoginAttempts',
                'PermissionCache', 'Permissions', 'ResourceAccess',
                'RolePermissions', 'Roles', 'SecurityAlerts', 'SecurityLog',
                'SecuritySettings', 'SessionLog', 'SessionSecurity',
                'SpecialPermissions', 'TwoFactorAuth', 'UserRoles',
                'PasswordResetTokens', 'IPReputation'
            }
        }

        accessible = set(table_access.get(role, set()))

        # If DB-managed table permissions exist, use them as the effective list.
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            role_scope = 'Librarian' if role == 'Faculty' else role
            role_permission_count = cursor.execute(
                '''
                SELECT COUNT(*)
                FROM Roles r
                JOIN RolePermissions rp ON rp.role_id = r.id
                WHERE r.name = ?
                ''',
                (role_scope,),
            ).fetchone()[0]
            cursor.execute(
                '''
                SELECT p.name
                FROM Roles r
                JOIN RolePermissions rp ON rp.role_id = r.id
                JOIN Permissions p ON p.id = rp.permission_id
                WHERE r.name = ? AND p.category = 'table_access'
                ''',
                (role_scope,),
            )
            table_permissions = set()
            for row in cursor.fetchall():
                permission_name = row[0]
                if ':' in permission_name:
                    table_permissions.add(permission_name.split(':', 1)[1])
            if table_permissions:
                accessible = table_permissions
            elif role_permission_count:
                accessible = set()
        except Exception as e:
            print(f"❌ Error getting table permissions: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return accessible
    
    def get_query_filter(self, user_id: str, table: str) -> Optional[str]:
        """🔍 Get row-level security filter for queries"""
        role = self.get_user_role(user_id)
        if not role:
            return None
        
        # Student-specific filters
        if role == 'Student':
            if table in ['Issued', 'Fines', 'Reservations']:
                return f"student_id = (SELECT id FROM Students WHERE roll_number = '{user_id}' OR email = '{user_id}')"
            elif table == 'Students':
                return f"roll_number = '{user_id}' OR email = '{user_id}'"
        
        # Librarian-specific filters
        elif role == 'Librarian':
            # Librarians can see all student data but not admin data
            pass  # No additional filtering needed
        
        # Administrator has full access
        elif role == 'Administrator':
            pass  # No filtering needed
        
        return None
    
    def validate_query_access(self, user_id: str, sql_query: str) -> Tuple[bool, str]:
        """🔍 Validate if user can execute the SQL query"""
        try:
            # Extract table names from query
            tables = self._extract_tables_from_query(sql_query)
            accessible_tables = self.get_accessible_tables(user_id)
            
            # Check if all tables are accessible
            for table in tables:
                if table not in accessible_tables:
                    return False, f"Access denied to table: {table}"
            
            # Additional validation based on role
            role = self.get_user_role(user_id)
            if not self.has_permission(user_id, 'execute_queries'):
                return False, "Role does not have execute_queries permission"
            if role == 'Student':
                # Students can only do SELECT queries
                if not sql_query.strip().upper().startswith('SELECT'):
                    return False, "Students can only perform SELECT queries"
            
            return True, "Query access validated"
            
        except Exception as e:
            return False, f"Query validation error: {str(e)}"
    
    def _extract_tables_from_query(self, sql_query: str) -> Set[str]:
        """📋 Extract table names from SQL query"""
        tables = set()
        
        # Find FROM and JOIN clauses
        from_pattern = r'\bFROM\s+(\w+)'
        join_pattern = r'\bJOIN\s+(\w+)'
        
        from_matches = re.findall(from_pattern, sql_query, re.IGNORECASE)
        join_matches = re.findall(join_pattern, sql_query, re.IGNORECASE)
        
        tables.update(from_matches)
        tables.update(join_matches)
        
        return tables
    
    def get_permission_summary(self, user_id: str) -> Dict:
        """📊 Get complete permission summary for user"""
        role = self.get_user_role(user_id)
        permissions = self.get_user_permissions(user_id)
        accessible_tables = self.get_accessible_tables(user_id)
        
        return {
            'user_id': user_id,
            'role': role,
            'role_level': self.get_role_level(role) if role else 0,
            'permissions': list(permissions),
            'permission_count': len(permissions),
            'accessible_tables': list(accessible_tables),
            'table_count': len(accessible_tables)
        }

# Global RBAC instance
rbac = RBACSystem()

# Decorator functions for Flask routes
def require_permission(permission):
    """🔐 Decorator to require specific permission"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_id = session.get('user_id') or session.get('student_id')
            if not user_id:
                return jsonify({'error': 'Not authenticated'}), 401
            
            if not rbac.has_permission(user_id, permission):
                return jsonify({'error': f'Permission denied: {permission} required'}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def require_role(required_role):
    """🔐 Decorator to require specific role"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_id = session.get('user_id') or session.get('student_id')
            if not user_id:
                return jsonify({'error': 'Not authenticated'}), 401
            
            user_role = rbac.get_user_role(user_id)
            if user_role != required_role:
                return jsonify({'error': f'Access denied: {required_role} role required'}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def require_min_role(min_role_level):
    """🔐 Decorator to require minimum role level"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user_id = session.get('user_id') or session.get('student_id')
            if not user_id:
                return jsonify({'error': 'Not authenticated'}), 401
            
            if not rbac.can_access_role_level(user_id, min_role_level):
                return jsonify({'error': 'Access denied: insufficient role level'}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def apply_row_level_filter(user_id: str, sql_query: str) -> str:
    """🔍 Apply row-level security filters to SQL query"""
    try:
        tables = rbac._extract_tables_from_query(sql_query)
        filters = []
        
        for table in tables:
            filter_condition = rbac.get_query_filter(user_id, table)
            if filter_condition:
                filters.append(filter_condition)
        
        if filters:
            # Add WHERE clause if not exists
            if 'WHERE' not in sql_query.upper():
                sql_query += f" WHERE {' AND '.join(filters)}"
            else:
                sql_query += f" AND {' AND '.join(filters)}"
        
        return sql_query
        
    except Exception as e:
        print(f"❌ Error applying row-level filter: {e}")
        return sql_query

if __name__ == "__main__":
    # Test the RBAC system
    print("🔐 Testing RBAC System...")
    
    # Test user permissions
    test_users = ['student', 'librarian', 'admin']
    
    for user in test_users:
        print(f"\n👤 User: {user}")
        summary = rbac.get_permission_summary(user)
        print(f"🎭 Role: {summary['role']}")
        print(f"📊 Permissions: {summary['permission_count']}")
        print(f"📋 Tables: {summary['table_count']}")
        print(f"🔑 Sample Permissions: {summary['permissions'][:5]}")
    
    print("\n✅ RBAC System test completed!")
