"""RBAC and role helper functions for SPEAK2DB."""
import re
from typing import Tuple

ROLE_CHOICES = ('Student', 'Faculty', 'Librarian', 'Administrator')
ROLE_PERMISSION_SCOPE = {
    'Student': 'Student',
    'Faculty': 'Librarian',
    'Librarian': 'Librarian',
    'Administrator': 'Administrator',
}


def normalize_role(role: str) -> str:
    """Normalize database and session role names."""
    role = (role or '').strip()
    mapping = {
        'Admin': 'Administrator',
        'Administrator': 'Administrator',
        'Faculty': 'Faculty',
        'Librarian': 'Librarian',
        'Student': 'Student',
    }
    return mapping.get(role, role or 'Student')


def role_permission_scope(role: str) -> str:
    """Return the RBAC/permission scope used for a UI role."""
    return ROLE_PERMISSION_SCOPE.get(normalize_role(role), 'Student')


def extract_tables_from_sql(sql_query: str) -> set:
    """Return tables referenced by FROM/JOIN clauses."""
    tables = set()
    if not sql_query:
        return tables
    tables.update(re.findall(r'\bFROM\s+(\w+)', sql_query, re.IGNORECASE))
    tables.update(re.findall(r'\bJOIN\s+(\w+)', sql_query, re.IGNORECASE))
    return tables


def get_role_permission_config(conn, role_name: str) -> dict:
    """Fetch DB-backed permissions for a role scope."""
    role_scope = role_permission_scope(role_name)
    permissions = [
        dict(row)
        for row in conn.execute(
            '''
            SELECT p.id, p.name, p.category, p.description
            FROM Roles r
            JOIN RolePermissions rp ON rp.role_id = r.id
            JOIN Permissions p ON p.id = rp.permission_id
            WHERE r.name = ?
            ORDER BY p.category, p.name
            ''',
            (role_scope,),
        ).fetchall()
    ]
    return {
        'permissions': permissions,
        'permission_names': {perm['name'] for perm in permissions},
        'table_access': {
            perm['name'].split(':', 1)[1]
            for perm in permissions
            if perm['category'] == 'table_access' and ':' in perm['name']
        },
    }


def role_can_execute_queries(conn, role_name: str) -> bool:
    """Check role-level query permission."""
    config = get_role_permission_config(conn, role_name)
    if role_permission_scope(role_name) in {'Student', 'Librarian', 'Administrator'}:
        return 'execute_queries' in config['permission_names']
    return True


def role_can_use_ai_queries(conn, role_name: str) -> bool:
    """Check whether a role may use AI-assisted query generation."""
    config = get_role_permission_config(conn, role_name)
    if role_permission_scope(role_name) in {'Student', 'Librarian', 'Administrator'}:
        return 'use_ai_queries' in config['permission_names']
    return True


def role_allows_tables(conn, role_name: str, sql_query: str) -> Tuple[bool, str]:
    """Enforce DB-configured table access rules for a role when configured."""
    config = get_role_permission_config(conn, role_name)
    allowed_tables = config['table_access']
    query_tables = extract_tables_from_sql(sql_query)
    if not allowed_tables:
        if config['permissions'] and query_tables:
            return False, f"Role {normalize_role(role_name)} has no table access permissions configured"
        return True, ''
    for table in query_tables:
        if table not in allowed_tables:
            return False, f"Role {normalize_role(role_name)} cannot access table {table}"
    return True, ''
