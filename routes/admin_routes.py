"""Admin route registration for SPEAK2DB."""
import logging
import sqlite3

from flask import flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash
from security.auth_utils import is_password_hash

logger = logging.getLogger(__name__)


def register_admin_routes(
    app,
    *,
    main_db_getter,
    default_query_limit,
    role_choices,
    require_admin,
    build_admin_dashboard_context,
    fetch_activity_logs,
    get_db_connection,
    get_user_with_details,
    normalize_role,
    role_permission_scope,
    set_setting,
    sync_role_profile_tables,
    validate_managed_user_form,
    validate_query_result_limit,
    log_activity,
    log_audit_event,
):
    """Register admin control-panel routes on the Flask app."""

    def _require_admin_session():
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return require_admin()

    @app.route('/user_management', endpoint='user_management_view')
    def user_management_view():
        redir = _require_admin_session()
        if redir:
            return redir
        return render_template('admin_dashboard.html', **build_admin_dashboard_context('users'))

    @app.route('/system_statistics', endpoint='system_statistics_view')
    def system_statistics_view():
        redir = _require_admin_session()
        if redir:
            return redir
        return render_template('admin_dashboard.html', **build_admin_dashboard_context('analytics'))

    @app.route('/admin/activity_logs', endpoint='admin_activity_logs')
    def admin_activity_logs():
        redir = _require_admin_session()
        if redir:
            return redir
        conn = get_db_connection(main_db_getter())
        try:
            return jsonify({'success': True, 'logs': fetch_activity_logs(conn, limit=100)})
        finally:
            conn.close()

    @app.route('/admin/add_user', methods=['POST'], endpoint='admin_add_user')
    def admin_add_user():
        redir = _require_admin_session()
        if redir:
            return redir
        payload, error = validate_managed_user_form(request.form)
        if error:
            flash(error, 'error')
            return redirect(url_for('user_management_view'))

        conn = sqlite3.connect(main_db_getter())
        conn.row_factory = sqlite3.Row
        try:
            password_to_store = generate_password_hash(payload['password'] or 'pass')
            conn.execute(
                'INSERT INTO Users (username, password, role, email) VALUES (?, ?, ?, ?)',
                (payload['username'], password_to_store, payload['role'], payload['email']),
            )
            sync_role_profile_tables(conn, payload)
            conn.commit()
            log_activity(session.get('user_id'), f"User created: {payload['username']} ({payload['role']})")
            log_audit_event(session.get('user_id'), session.get('role', 'Administrator'), 'USER_CREATE', 'USER', f"Created user {payload['username']} with role {payload['role']}", success=True)
            flash(f"User {payload['username']} created successfully.", 'success')
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            flash(f'Unable to create user: {exc}', 'error')
        finally:
            conn.close()
        return redirect(url_for('user_management_view'))

    @app.route('/admin/update_user/<int:user_id>', methods=['POST'], endpoint='admin_update_user')
    def admin_update_user(user_id: int):
        redir = _require_admin_session()
        if redir:
            return redir
        conn = sqlite3.connect(main_db_getter())
        conn.row_factory = sqlite3.Row
        try:
            existing_user = conn.execute('SELECT * FROM Users WHERE id = ?', (user_id,)).fetchone()
            if not existing_user:
                flash('User not found.', 'error')
                return redirect(url_for('user_management_view'))
            existing_details = get_user_with_details(conn, user_id) or dict(existing_user)
            payload, error = validate_managed_user_form(request.form, existing_details)
            if error:
                flash(error, 'error')
                return redirect(url_for('user_management_view'))
            new_password = existing_user['password']
            if payload['password']:
                new_password = generate_password_hash(payload['password'])
            elif not is_password_hash(existing_user['password']):
                new_password = generate_password_hash(existing_user['password'])
            conn.execute(
                'UPDATE Users SET username = ?, password = ?, role = ?, email = ? WHERE id = ?',
                (payload['username'], new_password, payload['role'], payload['email'], user_id),
            )
            sync_role_profile_tables(conn, payload)
            conn.commit()
            log_activity(session.get('user_id'), f"User updated: {payload['username']}")
            log_audit_event(session.get('user_id'), session.get('role', 'Administrator'), 'USER_UPDATE', 'USER', f"Updated user {payload['username']} ({payload['role']})", success=True)
            flash(f"User {payload['username']} updated.", 'success')
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            flash(f'Unable to update user: {exc}', 'error')
        finally:
            conn.close()
        return redirect(url_for('user_management_view'))

    @app.route('/admin/delete_user/<int:user_id>', methods=['POST'], endpoint='admin_delete_user')
    def admin_delete_user(user_id: int):
        redir = _require_admin_session()
        if redir:
            return redir
        conn = sqlite3.connect(main_db_getter())
        conn.row_factory = sqlite3.Row
        try:
            existing_user = conn.execute('SELECT * FROM Users WHERE id = ?', (user_id,)).fetchone()
            if not existing_user:
                flash('User not found.', 'error')
                return redirect(url_for('user_management_view'))
            username = existing_user['username']
            email = existing_user['email']
            conn.execute('DELETE FROM Students WHERE roll_number = ? OR lower(email) = lower(?)', (username, email))
            conn.execute('DELETE FROM Faculty WHERE lower(email) = lower(?)', (email,))
            conn.execute('DELETE FROM UserRoles WHERE user_id = ?', (username,))
            conn.execute('DELETE FROM Users WHERE id = ?', (user_id,))
            conn.commit()
            log_activity(session.get('user_id'), f'User deleted: {username}')
            log_audit_event(session.get('user_id'), session.get('role', 'Administrator'), 'USER_DELETE', 'USER', f'Deleted user {username}', success=True)
            flash(f'User {username} deleted.', 'success')
        finally:
            conn.close()
        return redirect(url_for('user_management_view'))

    @app.route('/admin/change_role/<int:user_id>', methods=['POST'], endpoint='admin_change_role')
    def admin_change_role(user_id: int):
        redir = _require_admin_session()
        if redir:
            return redir
        new_role = normalize_role(request.form.get('role', '').strip())
        if new_role not in role_choices:
            flash('Please choose a valid role.', 'error')
            return redirect(url_for('user_management_view'))
        conn = sqlite3.connect(main_db_getter())
        conn.row_factory = sqlite3.Row
        try:
            existing_user = conn.execute('SELECT * FROM Users WHERE id = ?', (user_id,)).fetchone()
            if not existing_user:
                flash('User not found.', 'error')
                return redirect(url_for('user_management_view'))
            details = get_user_with_details(conn, user_id) or dict(existing_user)
            details['role'] = new_role
            details['username'] = existing_user['username']
            details['email'] = request.form.get('email', details.get('email', existing_user['email']))
            details['name'] = request.form.get('name', details.get('name', existing_user['username']))
            details['department'] = request.form.get('department', details.get('department', ''))
            details['designation'] = request.form.get('designation', details.get('designation', ''))
            details['branch'] = request.form.get('branch', details.get('branch', ''))
            details['year'] = request.form.get('year', details.get('year', ''))
            details['phone'] = request.form.get('phone', details.get('student_phone') or details.get('faculty_phone') or '')
            conn.execute('UPDATE Users SET role = ? WHERE id = ?', (new_role, user_id))
            sync_role_profile_tables(conn, details)
            conn.commit()
            log_activity(session.get('user_id'), f"Role changed: {existing_user['username']} → {new_role}")
            log_audit_event(session.get('user_id'), session.get('role', 'Administrator'), 'ROLE_CHANGE', 'USER', f"Changed role for {existing_user['username']} to {new_role}", success=True)
            flash(f'Role updated to {new_role}.', 'success')
        finally:
            conn.close()
        return redirect(url_for('user_management_view'))

    @app.route('/admin/update_permissions/<role_name>', methods=['POST'], endpoint='admin_update_permissions')
    def admin_update_permissions(role_name: str):
        redir = _require_admin_session()
        if redir:
            return redir
        role_scope = role_permission_scope(role_name)
        selected_permission_ids = {
            int(permission_id)
            for permission_id in request.form.getlist('permission_ids')
            if str(permission_id).isdigit()
        }
        conn = sqlite3.connect(main_db_getter())
        conn.row_factory = sqlite3.Row
        try:
            role_row = conn.execute('SELECT id, name FROM Roles WHERE name = ?', (role_scope,)).fetchone()
            if not role_row:
                flash('Role not found.', 'error')
                return redirect(url_for('admin_dashboard_route'))
            conn.execute('DELETE FROM RolePermissions WHERE role_id = ?', (role_row['id'],))
            for permission_id in selected_permission_ids:
                conn.execute('INSERT INTO RolePermissions (role_id, permission_id) VALUES (?, ?)', (role_row['id'], permission_id))
            conn.commit()
            log_activity(session.get('user_id'), f'Permissions updated for {role_scope}')
            log_audit_event(session.get('user_id'), session.get('role', 'Administrator'), 'PERMISSIONS_UPDATE', 'ROLE', f'Updated permissions for role {role_scope}', success=True)
            flash(f'Permissions updated for {role_scope}.', 'success')
        finally:
            conn.close()
        return redirect(url_for('admin_dashboard_route'))

    @app.route('/admin/update_settings', methods=['POST'], endpoint='admin_update_settings')
    def admin_update_settings():
        redir = _require_admin_session()
        if redir:
            return redir
        max_limit, error = validate_query_result_limit(
            request.form.get('max_query_result_limit'),
            default_query_limit,
        )
        if error:
            flash(error, 'error')
            return redirect(url_for('admin_dashboard_route'))
        settings_payload = {
            'max_query_result_limit': max_limit,
            'voice_input_enabled': 'true' if request.form.get('voice_input_enabled') == 'on' else 'false',
            'ai_query_enabled': 'true' if request.form.get('ai_query_enabled') == 'on' else 'false',
            'ollama_sql_enabled': 'true' if request.form.get('ollama_sql_enabled') == 'on' else 'false',
        }
        for setting_name, setting_value in settings_payload.items():
            set_setting(setting_name, setting_value, updated_by=session.get('user_id'))
        log_activity(session.get('user_id'), 'System settings updated')
        log_audit_event(session.get('user_id'), session.get('role', 'Administrator'), 'SETTINGS_UPDATE', 'SYSTEM', f"Updated settings: {', '.join(settings_payload.keys())}", success=True)
        flash('System settings updated.', 'success')
        return redirect(url_for('admin_dashboard_route'))
