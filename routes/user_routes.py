from flask import Blueprint, request

from routes.common import json_response, require_client_id, require_registered_user
from services.dca_plan_service import (
    delete_dca_plan,
    get_dca_plan,
    run_due_dca_plans,
    save_dca_plan,
)
from services.daily_earnings_service import get_daily_earnings
from services.fund_conversion_service import (
    create_conversion,
    list_conversions,
    preview_conversion,
)
from services.fund_transaction_service import (
    create_fund_transaction,
    delete_fund_transaction,
    list_fund_transactions,
    preview_fund_transaction,
)
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


@user_bp.route('/api/user/funds/<fund_code>/transactions', methods=['GET'])
def get_user_fund_transactions(fund_code):
    _, user_id, error = require_registered_user()
    if error:
        return error
    try:
        return json_response(list_fund_transactions(user_id, fund_code))
    except ValueError as exc:
        return json_response({'success': False, 'error': str(exc)}, 400)


@user_bp.route('/api/user/funds/<fund_code>/transactions', methods=['POST'])
def create_user_fund_transaction(fund_code):
    _, user_id, error = require_registered_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        return json_response(create_fund_transaction(user_id, fund_code, data))
    except ValueError as exc:
        return json_response({'success': False, 'error': str(exc)}, 400)


@user_bp.route('/api/user/funds/<fund_code>/transactions/preview', methods=['POST'])
def preview_user_fund_transaction(fund_code):
    _, _, error = require_registered_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        return json_response(preview_fund_transaction(fund_code, data))
    except ValueError as exc:
        return json_response({'success': False, 'error': str(exc)}, 400)


@user_bp.route('/api/user/transactions/<int:transaction_id>', methods=['DELETE'])
def delete_user_fund_transaction(transaction_id):
    _, user_id, error = require_registered_user()
    if error:
        return error
    try:
        return json_response(delete_fund_transaction(user_id, transaction_id))
    except ValueError as exc:
        return json_response({'success': False, 'error': str(exc)}, 400)


@user_bp.route('/api/user/fund-conversions/preview', methods=['POST'])
def preview_user_fund_conversion():
    _, user_id, error = require_registered_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        return json_response(preview_conversion(user_id, data))
    except ValueError as exc:
        return json_response({'success': False, 'error': str(exc)}, 400)


@user_bp.route('/api/user/fund-conversions', methods=['POST'])
def create_user_fund_conversion():
    _, user_id, error = require_registered_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        return json_response(create_conversion(user_id, data))
    except ValueError as exc:
        return json_response({'success': False, 'error': str(exc)}, 400)


@user_bp.route('/api/user/funds/<fund_code>/conversions', methods=['GET'])
def list_user_fund_conversions(fund_code):
    _, user_id, error = require_registered_user()
    if error:
        return error
    try:
        return json_response(list_conversions(user_id, fund_code))
    except ValueError as exc:
        return json_response({'success': False, 'error': str(exc)}, 400)


@user_bp.route('/api/user/funds/<fund_code>/dca-plan', methods=['GET'])
def get_user_fund_dca_plan(fund_code):
    _, user_id, error = require_registered_user()
    if error:
        return error
    try:
        return json_response(get_dca_plan(user_id, fund_code))
    except ValueError as exc:
        return json_response({'success': False, 'error': str(exc)}, 400)


@user_bp.route('/api/user/funds/<fund_code>/dca-plan', methods=['POST'])
def save_user_fund_dca_plan(fund_code):
    _, user_id, error = require_registered_user()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        return json_response(save_dca_plan(user_id, fund_code, data))
    except ValueError as exc:
        return json_response({'success': False, 'error': str(exc)}, 400)


@user_bp.route('/api/user/funds/<fund_code>/dca-plan', methods=['DELETE'])
def delete_user_fund_dca_plan(fund_code):
    _, user_id, error = require_registered_user()
    if error:
        return error
    try:
        return json_response(delete_dca_plan(user_id, fund_code))
    except ValueError as exc:
        return json_response({'success': False, 'error': str(exc)}, 400)


@user_bp.route('/api/user/dca-plans/run', methods=['POST'])
def run_user_dca_plans():
    _, user_id, error = require_registered_user()
    if error:
        return error
    try:
        return json_response(run_due_dca_plans(user_id=user_id))
    except ValueError as exc:
        return json_response({'success': False, 'error': str(exc)}, 400)


@user_bp.route('/api/user/portfolio', methods=['GET'])
def get_user_portfolio_view():
    client_id, error = require_client_id()
    if error:
        return error
    return json_response(get_user_portfolio(client_id))


@user_bp.route('/api/user/earnings/daily', methods=['GET'])
def get_user_daily_earnings_view():
    _, user_id, error = require_registered_user()
    if error:
        return error
    try:
        return json_response(get_daily_earnings(
            user_id,
            request.args.get('start'),
            request.args.get('end'),
        ))
    except ValueError as exc:
        return json_response({'success': False, 'error': str(exc)}, 400)


@user_bp.route('/api/user/funds/<fund_code>', methods=['DELETE'])
def remove_user_fund_view(fund_code):
    client_id, error = require_client_id()
    if error:
        return error
    return json_response({'deleted': delete_user_fund(client_id, fund_code)})
