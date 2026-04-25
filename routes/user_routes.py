from flask import Blueprint, request

from routes.common import json_response, require_client_id
from services.user_fund_profit_service import get_user_portfolio
from services.user_fund_service import (
    add_or_update_user_fund,
    bootstrap_user_funds,
    create_group,
    delete_group,
    delete_user_fund,
    get_user_snapshot,
    list_groups_with_counts,
    move_user_fund,
    rename_group,
    update_user_fund_position_snapshot,
)


user_bp = Blueprint('user_api', __name__)


@user_bp.route('/api/user/funds-meta', methods=['GET'])
def get_user_funds_meta():
    client_id, error = require_client_id()
    if error:
        return error
    return json_response(get_user_snapshot(client_id))


@user_bp.route('/api/user/bootstrap', methods=['POST'])
def bootstrap_user_data():
    client_id, error = require_client_id()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    return json_response(bootstrap_user_funds(client_id, data.get('codes') or []))


@user_bp.route('/api/user/groups', methods=['GET'])
def get_user_groups():
    client_id, error = require_client_id()
    if error:
        return error
    return json_response(list_groups_with_counts(client_id))


@user_bp.route('/api/user/groups', methods=['POST'])
def create_user_group():
    client_id, error = require_client_id()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        return json_response(create_group(client_id, data.get('name')))
    except ValueError as exc:
        return json_response({'error': str(exc)}, 400)


@user_bp.route('/api/user/groups/<int:group_id>', methods=['PUT'])
def update_user_group(group_id):
    client_id, error = require_client_id()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        return json_response(rename_group(client_id, group_id, data.get('name')))
    except ValueError as exc:
        return json_response({'error': str(exc)}, 400)


@user_bp.route('/api/user/groups/<int:group_id>', methods=['DELETE'])
def remove_user_group(group_id):
    client_id, error = require_client_id()
    if error:
        return error
    try:
        return json_response(delete_group(client_id, group_id))
    except ValueError as exc:
        return json_response({'error': str(exc)}, 400)


@user_bp.route('/api/user/funds', methods=['POST'])
def add_user_fund():
    client_id, error = require_client_id()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        return json_response(add_or_update_user_fund(client_id, data.get('code'), data.get('group_id')))
    except ValueError as exc:
        return json_response({'error': str(exc)}, 400)


@user_bp.route('/api/user/funds/<fund_code>/group', methods=['PUT'])
def update_user_fund_group(fund_code):
    client_id, error = require_client_id()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        return json_response(move_user_fund(client_id, fund_code, data.get('group_id')))
    except ValueError as exc:
        return json_response({'error': str(exc)}, 400)


@user_bp.route('/api/user/funds/<fund_code>/position', methods=['PUT'])
def update_user_fund_position(fund_code):
    client_id, error = require_client_id()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        return json_response(
            update_user_fund_position_snapshot(
                client_id,
                fund_code,
                data.get('holding_amount'),
                data.get('holding_profit'),
            )
        )
    except ValueError as exc:
        return json_response({'success': False, 'error': str(exc)}, 400)


@user_bp.route('/api/user/portfolio', methods=['GET'])
def get_user_portfolio_view():
    client_id, error = require_client_id()
    if error:
        return error
    return json_response(get_user_portfolio(client_id))


@user_bp.route('/api/user/funds/<fund_code>', methods=['DELETE'])
def remove_user_fund_view(fund_code):
    client_id, error = require_client_id()
    if error:
        return error
    return json_response({'deleted': delete_user_fund(client_id, fund_code)})
