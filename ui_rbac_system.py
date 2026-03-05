"""
🎨 ROLE-BASED UI/UX SYSTEM
Dynamic interface adaptation based on user roles and permissions
"""

from typing import Dict, List, Optional
from rbac_system_fixed import rbac
import json

class RoleBasedUI:
    """🎨 Dynamic UI system for role-based interfaces"""
    
    def __init__(self):
        self.ui_config = self._load_ui_configuration()
        
    def _load_ui_configuration(self) -> Dict:
        """📋 Load UI configuration for all roles"""
        return {
            'Student': {
                'theme': {
                    'primary_color': '#4CAF50',
                    'secondary_color': '#2196F3',
                    'accent_color': '#FF9800',
                    'background': '#f5f5f5',
                    'sidebar_color': '#2E7D32'
                },
                'layout': {
                    'sidebar_width': '250px',
                    'show_admin_panel': False,
                    'show_advanced_features': False,
                    'show_library_management': False
                },
                'components': {
                    'search_bar': {
                        'enabled': True,
                        'placeholder': 'Search books, authors, or topics...',
                        'suggestions': [
                            'My current books',
                            'My overdue books',
                            'My fines',
                            'Books by my department',
                            'Recommended for me'
                        ]
                    },
                    'quick_actions': [
                        {
                            'icon': '📚',
                            'label': 'My Books',
                            'url': '/my-books',
                            'permission': 'view_my_loans'
                        },
                        {
                            'icon': '💳',
                            'label': 'My Fines',
                            'url': '/my-fines',
                            'permission': 'view_my_fines'
                        },
                        {
                            'icon': '🔖',
                            'label': 'Reservations',
                            'url': '/reservations',
                            'permission': 'view_my_reservations'
                        },
                        {
                            'icon': '👤',
                            'label': 'Profile',
                            'url': '/profile',
                            'permission': 'view_my_profile'
                        }
                    ],
                    'dashboard_widgets': [
                        {
                            'type': 'current_books',
                            'title': 'Current Books',
                            'icon': '📚',
                            'permission': 'view_my_loans'
                        },
                        {
                            'type': 'overdue_alerts',
                            'title': 'Overdue Alerts',
                            'icon': '⚠️',
                            'permission': 'view_my_loans'
                        },
                        {
                            'type': 'fine_summary',
                            'title': 'Fine Summary',
                            'icon': '💳',
                            'permission': 'view_my_fines'
                        },
                        {
                            'type': 'reading_stats',
                            'title': 'Reading Statistics',
                            'icon': '📊',
                            'permission': 'view_my_statistics'
                        }
                    ]
                }
            },
            'Librarian': {
                'theme': {
                    'primary_color': '#2196F3',
                    'secondary_color': '#FF9800',
                    'accent_color': '#4CAF50',
                    'background': '#f8f9fa',
                    'sidebar_color': '#1565C0'
                },
                'layout': {
                    'sidebar_width': '280px',
                    'show_admin_panel': False,
                    'show_advanced_features': True,
                    'show_library_management': True
                },
                'components': {
                    'search_bar': {
                        'enabled': True,
                        'placeholder': 'Search books, students, or generate reports...',
                        'suggestions': [
                            'All overdue books',
                            'Books issued today',
                            'Student borrowing history',
                            'Circulation report',
                            'Library statistics'
                        ]
                    },
                    'quick_actions': [
                        {
                            'icon': '📚',
                            'label': 'Manage Books',
                            'url': '/manage-books',
                            'permission': 'manage_books'
                        },
                        {
                            'icon': '🔄',
                            'label': 'Circulation',
                            'url': '/circulation',
                            'permission': 'checkout_books'
                        },
                        {
                            'icon': '👥',
                            'label': 'Students',
                            'url': '/students',
                            'permission': 'manage_student_accounts'
                        },
                        {
                            'icon': '📊',
                            'label': 'Reports',
                            'url': '/reports',
                            'permission': 'view_circulation_reports'
                        },
                        {
                            'icon': '🔖',
                            'label': 'Reservations',
                            'url': '/reservations',
                            'permission': 'manage_reservations'
                        },
                        {
                            'icon': '⚙️',
                            'label': 'Settings',
                            'url': '/settings',
                            'permission': 'library_analytics'
                        }
                    ],
                    'dashboard_widgets': [
                        {
                            'type': 'library_stats',
                            'title': 'Library Statistics',
                            'icon': '📊',
                            'permission': 'view_circulation_reports'
                        },
                        {
                            'type': 'circulation_chart',
                            'title': 'Circulation Trends',
                            'icon': '📈',
                            'permission': 'view_circulation_reports'
                        },
                        {
                            'type': 'overdue_books',
                            'title': 'Overdue Books',
                            'icon': '⚠️',
                            'permission': 'manage_overdue'
                        },
                        {
                            'type': 'popular_books',
                            'title': 'Popular Books',
                            'icon': '🔥',
                            'permission': 'view_popular_books'
                        },
                        {
                            'type': 'quick_checkout',
                            'title': 'Quick Checkout',
                            'icon': '⚡',
                            'permission': 'checkout_books'
                        },
                        {
                            'type': 'student_activity',
                            'title': 'Student Activity',
                            'icon': '👥',
                            'permission': 'view_user_statistics'
                        }
                    ]
                }
            },
            'Administrator': {
                'theme': {
                    'primary_color': '#9C27B0',
                    'secondary_color': '#F44336',
                    'accent_color': '#2196F3',
                    'background': '#fafafa',
                    'sidebar_color': '#6A1B9A'
                },
                'layout': {
                    'sidebar_width': '300px',
                    'show_admin_panel': True,
                    'show_advanced_features': True,
                    'show_library_management': True
                },
                'components': {
                    'search_bar': {
                        'enabled': True,
                        'placeholder': 'Search anything: users, roles, departments, reports...',
                        'suggestions': [
                            'User management',
                            'Role assignments',
                            'System configuration',
                            'Audit logs',
                            'Financial reports',
                            'Department statistics'
                        ]
                    },
                    'quick_actions': [
                        {
                            'icon': '👥',
                            'label': 'User Management',
                            'url': '/users',
                            'permission': 'manage_roles'
                        },
                        {
                            'icon': '🔐',
                            'label': 'Roles & Permissions',
                            'url': '/roles',
                            'permission': 'manage_roles'
                        },
                        {
                            'icon': '⚙️',
                            'label': 'System Config',
                            'url': '/config',
                            'permission': 'configure_system'
                        },
                        {
                            'icon': '🏛️',
                            'label': 'Departments',
                            'url': '/departments',
                            'permission': 'manage_departments'
                        },
                        {
                            'icon': '👨‍🏫',
                            'label': 'Faculty',
                            'url': '/faculty',
                            'permission': 'manage_faculty_records'
                        },
                        {
                            'icon': '📊',
                            'label': 'Reports',
                            'url': '/reports',
                            'permission': 'view_institutional_metrics'
                        },
                        {
                            'icon': '🔍',
                            'label': 'Audit Logs',
                            'url': '/audit',
                            'permission': 'audit_trail'
                        },
                        {
                            'icon': '💰',
                            'label': 'Budgets',
                            'url': '/budgets',
                            'permission': 'manage_budgets'
                        }
                    ],
                    'dashboard_widgets': [
                        {
                            'type': 'system_overview',
                            'title': 'System Overview',
                            'icon': '🖥️',
                            'permission': 'view_institutional_metrics'
                        },
                        {
                            'type': 'user_statistics',
                            'title': 'User Statistics',
                            'icon': '👥',
                            'permission': 'view_institutional_metrics'
                        },
                        {
                            'type': 'role_distribution',
                            'title': 'Role Distribution',
                            'icon': '🎭',
                            'permission': 'manage_roles'
                        },
                        {
                            'type': 'activity_monitor',
                            'title': 'Activity Monitor',
                            'icon': '📊',
                            'permission': 'audit_trail'
                        },
                        {
                            'type': 'financial_overview',
                            'title': 'Financial Overview',
                            'icon': '💰',
                            'permission': 'manage_budgets'
                        },
                        {
                            'type': 'system_health',
                            'title': 'System Health',
                            'icon': '🏥',
                            'permission': 'system_maintenance'
                        },
                        {
                            'type': 'security_alerts',
                            'title': 'Security Alerts',
                            'icon': '🚨',
                            'permission': 'manage_security'
                        },
                        {
                            'type': 'performance_metrics',
                            'title': 'Performance Metrics',
                            'icon': '⚡',
                            'permission': 'performance_monitoring'
                        }
                    ]
                }
            }
        }
    
    def get_user_ui_config(self, user_id: str) -> Dict:
        """🎨 Get UI configuration for specific user"""
        role = rbac.get_user_role(user_id)
        if not role:
            return self.ui_config['Student']  # Default to Student
        
        # Get user permissions
        permissions = rbac.get_user_permissions(user_id)
        
        # Filter components based on permissions
        config = self.ui_config.get(role, self.ui_config['Student'])
        
        # Filter quick actions based on permissions
        if 'components' in config and 'quick_actions' in config['components']:
            config['components']['quick_actions'] = [
                action for action in config['components']['quick_actions']
                if action.get('permission') is None or action['permission'] in permissions
            ]
        
        # Filter dashboard widgets based on permissions
        if 'components' in config and 'dashboard_widgets' in config['components']:
            config['components']['dashboard_widgets'] = [
                widget for widget in config['components']['dashboard_widgets']
                if widget.get('permission') is None or widget['permission'] in permissions
            ]
        
        return config
    
    def generate_theme_css(self, user_id: str) -> str:
        """🎨 Generate CSS theme for user"""
        config = self.get_user_ui_config(user_id)
        theme = config.get('theme', {})
        
        css = f"""
        :root {{
            --primary-color: {theme.get('primary_color', '#4CAF50')};
            --secondary-color: {theme.get('secondary_color', '#2196F3')};
            --accent-color: {theme.get('accent_color', '#FF9800')};
            --background-color: {theme.get('background', '#f5f5f5')};
            --sidebar-color: {theme.get('sidebar_color', '#2E7D32')};
            --sidebar-width: {config.get('layout', {}).get('sidebar_width', '250px')};
        }}
        
        .role-badge {{
            background: var(--primary-color);
            color: white;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 0.8em;
            font-weight: bold;
        }}
        
        .sidebar {{
            background: var(--sidebar-color);
            width: var(--sidebar-width);
        }}
        
        .dashboard {{
            background: var(--background-color);
        }}
        
        .btn-primary {{
            background: var(--primary-color);
            border-color: var(--primary-color);
        }}
        
        .btn-secondary {{
            background: var(--secondary-color);
            border-color: var(--secondary-color);
        }}
        
        .accent-text {{
            color: var(--accent-color);
        }}
        """
        
        return css
    
    def generate_navigation_menu(self, user_id: str) -> List[Dict]:
        """📋 Generate navigation menu for user"""
        config = self.get_user_ui_config(user_id)
        return config.get('components', {}).get('quick_actions', [])
    
    def generate_dashboard_widgets(self, user_id: str) -> List[Dict]:
        """📊 Generate dashboard widgets for user"""
        config = self.get_user_ui_config(user_id)
        return config.get('components', {}).get('dashboard_widgets', [])
    
    def get_search_config(self, user_id: str) -> Dict:
        """🔍 Get search configuration for user"""
        config = self.get_user_ui_config(user_id)
        return config.get('components', {}).get('search_bar', {
            'enabled': True,
            'placeholder': 'Search...',
            'suggestions': []
        })
    
    def should_show_admin_panel(self, user_id: str) -> bool:
        """🏢 Check if admin panel should be shown"""
        config = self.get_user_ui_config(user_id)
        return config.get('layout', {}).get('show_admin_panel', False)
    
    def should_show_advanced_features(self, user_id: str) -> bool:
        """🔧 Check if advanced features should be shown"""
        config = self.get_user_ui_config(user_id)
        return config.get('layout', {}).get('show_advanced_features', False)
    
    def get_role_badge_class(self, user_id: str) -> str:
        """🎭 Get CSS class for role badge"""
        role = rbac.get_user_role(user_id)
        return f"role-{role.lower()}" if role else "role-unknown"
    
    def get_user_permissions_summary(self, user_id: str) -> Dict:
        """📋 Get user permissions summary for UI display"""
        permissions = rbac.get_user_permissions(user_id)
        accessible_tables = rbac.get_accessible_tables(user_id)
        role = rbac.get_user_role(user_id)
        
        return {
            'role': role,
            'permission_count': len(permissions),
            'table_count': len(accessible_tables),
            'permissions': list(permissions)[:10],  # Show first 10
            'accessible_tables': list(accessible_tables),
            'role_level': rbac.get_role_level(role) if role else 0
        }

# Global UI system instance
ui_system = RoleBasedUI()
