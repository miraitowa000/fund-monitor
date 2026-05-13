from flask import Blueprint, request

from routes.common import get_client_id, json_response, require_client_id
from services.auth_service import get_auth_user_by_client_id, login_account, register_account


auth_bp = Blueprint('auth_api', __name__)


@auth_bp.route('/api/auth/me', methods=['GET'])
def get_auth_me():
    client_id = get_client_id()
    if not client_id:
        return json_response({'registered': False, 'user_type': 'anonymous'})
    user = get_auth_user_by_client_id(client_id)
    if not user:
        return json_response({'registered': False, 'user_type': 'anonymous'})
    return json_response(user)


@auth_bp.route('/api/auth/register', methods=['POST'])
def register_auth_account():
    client_id, error = require_client_id()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        user = register_account(client_id, data.get('account'), data.get('password'))
        return json_response({'success': True, 'user': user})
    except ValueError as exc:
        return json_response({'success': False, 'error': str(exc)}, 400)


@auth_bp.route('/api/auth/login', methods=['POST'])
def login_auth_account():
    data = request.get_json(silent=True) or {}
    try:
        user = login_account(data.get('account'), data.get('password'))
        return json_response({'success': True, 'user': user})
    except ValueError as exc:
        return json_response({'success': False, 'error': str(exc)}, 400)
