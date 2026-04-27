from flask import Blueprint, request

from routes.common import json_response, require_client_id
from services.dashboard_service import get_dashboard_bootstrap


dashboard_bp = Blueprint('dashboard_api', __name__)


@dashboard_bp.route('/api/dashboard/bootstrap', methods=['POST'])
def get_dashboard_bootstrap_view():
    client_id, error = require_client_id()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    return json_response(get_dashboard_bootstrap(client_id, data.get('codes') or []))
