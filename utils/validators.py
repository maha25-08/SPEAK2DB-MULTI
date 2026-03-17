"""Validation helpers for SPEAK2DB routes and services."""
from typing import Tuple

from services.rbac_service import ROLE_CHOICES, normalize_role


def validate_managed_user_form(form_data, existing_user: dict = None) -> Tuple[dict, str]:
    """Validate and normalize admin user-management payloads."""
    username = form_data.get('username', '').strip()
    name = form_data.get('name', '').strip()
    email = form_data.get('email', '').strip().lower()
    password = form_data.get('password', '').strip()
    role = normalize_role(form_data.get('role', '').strip())

    normalized = {
        'username': username,
        'name': name,
        'email': email,
        'password': password,
        'role': role,
        'branch': form_data.get('branch', '').strip(),
        'year': form_data.get('year', '').strip(),
        'phone': form_data.get('phone', '').strip(),
        'department': form_data.get('department', '').strip(),
        'designation': form_data.get('designation', '').strip(),
    }

    if not username:
        return normalized, 'Username is required.'
    if not name:
        return normalized, 'Name is required.'
    if not email or '@' not in email:
        return normalized, 'A valid email address is required.'
    if role not in ROLE_CHOICES:
        return normalized, 'Please choose a supported role.'
    if existing_user is None and not password:
        normalized['password'] = 'pass'
    if role == 'Student' and not normalized['year']:
        normalized['year'] = '1'
    if role == 'Student' and not normalized['branch']:
        normalized['branch'] = 'GEN'
    if role in ('Faculty', 'Librarian') and not normalized['department']:
        normalized['department'] = 'General'
    if role in ('Faculty', 'Librarian') and not normalized['designation']:
        normalized['designation'] = 'Librarian' if role == 'Librarian' else 'Faculty'
    if existing_user is not None and not normalized['password']:
        normalized['password'] = ''
    return normalized, ''


def validate_query_result_limit(raw_value: str, default_limit: int) -> Tuple[str, str]:
    """Normalize and validate the admin-configurable max query result limit."""
    normalized = (raw_value or str(default_limit)).strip() or str(default_limit)
    if not normalized.isdigit() or int(normalized) <= 0:
        return normalized, 'Max query result limit must be a positive number greater than zero.'
    return normalized, ''
