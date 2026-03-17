"""Query route registration for SPEAK2DB."""
import logging

from flask import jsonify, redirect, request, session, url_for

from services.query_service import execute_query_request

logger = logging.getLogger(__name__)


def register_query_routes(
    app,
    *,
    activity_logger,
    main_db_getter,
    get_db_connection,
    get_bool_setting,
    get_int_setting,
    log_audit_event,
    log_query_history,
    log_security_event,
    normalize_role,
):
    """Register query routes on the Flask app."""

    @app.route('/query', methods=['POST'], endpoint='query')
    def query():
        logger.info('Received /query request')
        body, status = execute_query_request(
            request.get_json(silent=True) or {},
            activity_logger,
            user_session=session,
            main_db=main_db_getter(),
            get_db_connection=get_db_connection,
            get_bool_setting=get_bool_setting,
            get_int_setting=get_int_setting,
            log_audit_event=log_audit_event,
            log_query_history=log_query_history,
            log_security_event=log_security_event,
            normalize_role=normalize_role,
        )
        return jsonify(body), status

    @app.route('/query', methods=['GET'], endpoint='query_page')
    def query_page():
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return redirect(url_for('index'))
