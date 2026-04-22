import os

from flask import Flask, jsonify, render_template, request

from core.runtime import register_watched_codes
from core.settings import build_mysql_uri
from services.fund_service import (
    fetch_funds_parallel,
    get_fund_details,
    get_fund_networth_history,
    start_background_refresh_thread,
)
from services.index_service import get_indexes
from services.user_fund_profit_service import get_user_portfolio
from services.user_fund_service import (
    add_or_update_user_fund,
    bootstrap_user_funds,
    create_group,
    delete_group,
    delete_user_fund,
    get_user_snapshot,
    init_database,
    list_groups_with_counts,
    move_user_fund,
    rename_group,
    update_user_fund_position_snapshot,
)


app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['DB_URI'] = build_mysql_uri()
app.config['DB_URI_MASKED'] = build_mysql_uri(mask_password=True)

init_database()
start_background_refresh_thread()


def _add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Client-Id')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


def _get_client_id():
    client_id = request.headers.get('X-Client-Id', '').strip()
    return client_id or None


def _require_client_id():
    client_id = _get_client_id()
    if not client_id:
        return None, (_add_cors_headers(jsonify({'error': 'Missing X-Client-Id header'})), 400)
    return client_id, None


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/health', methods=['GET'])
def health():
    return 'ok', 200


@app.route('/api/funds', methods=['POST'])
def get_funds():
    data = request.get_json()
    if not data or 'codes' not in data:
        return jsonify({'error': 'Missing "codes" parameter'}), 400

    codes = data['codes']
    register_watched_codes(codes)
    results = fetch_funds_parallel(codes)
    return _add_cors_headers(jsonify(results))


@app.route('/api/funds', methods=['OPTIONS'])
def options_funds():
    return _add_cors_headers(jsonify({'status': 'ok'}))


@app.route('/api/indexes', methods=['GET'])
def api_indexes():
    response = jsonify(get_indexes())
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response


@app.route('/api/fund/<fund_code>', methods=['GET'])
def get_fund_detail(fund_code):
    response = jsonify(get_fund_details(fund_code))
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response


@app.route('/api/fund/<fund_code>/history', methods=['GET'])
def get_fund_history(fund_code):
    days = request.args.get('days', default=30, type=int)
    days = max(30, min(days, 365))
    response = jsonify(get_fund_networth_history(fund_code, days=days))
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response


@app.route('/api/user/funds-meta', methods=['GET'])
def get_user_funds_meta():
    client_id, error = _require_client_id()
    if error:
        return error
    return _add_cors_headers(jsonify(get_user_snapshot(client_id)))


@app.route('/api/user/bootstrap', methods=['POST'])
def bootstrap_user_data():
    client_id, error = _require_client_id()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    return _add_cors_headers(jsonify(bootstrap_user_funds(client_id, data.get('codes') or [])))


@app.route('/api/user/groups', methods=['GET'])
def get_user_groups():
    client_id, error = _require_client_id()
    if error:
        return error
    return _add_cors_headers(jsonify(list_groups_with_counts(client_id)))


@app.route('/api/user/groups', methods=['POST'])
def create_user_group():
    client_id, error = _require_client_id()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        group = create_group(client_id, data.get('name'))
        return _add_cors_headers(jsonify(group))
    except ValueError as exc:
        return _add_cors_headers(jsonify({'error': str(exc)})), 400


@app.route('/api/user/groups/<int:group_id>', methods=['PUT'])
def update_user_group(group_id):
    client_id, error = _require_client_id()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        result = rename_group(client_id, group_id, data.get('name'))
        return _add_cors_headers(jsonify(result))
    except ValueError as exc:
        return _add_cors_headers(jsonify({'error': str(exc)})), 400


@app.route('/api/user/groups/<int:group_id>', methods=['DELETE'])
def remove_user_group(group_id):
    client_id, error = _require_client_id()
    if error:
        return error
    try:
        result = delete_group(client_id, group_id)
        return _add_cors_headers(jsonify(result))
    except ValueError as exc:
        return _add_cors_headers(jsonify({'error': str(exc)})), 400


@app.route('/api/user/funds', methods=['POST'])
def add_user_fund():
    client_id, error = _require_client_id()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        result = add_or_update_user_fund(client_id, data.get('code'), data.get('group_id'))
        return _add_cors_headers(jsonify(result))
    except ValueError as exc:
        return _add_cors_headers(jsonify({'error': str(exc)})), 400


@app.route('/api/user/funds/<fund_code>/group', methods=['PUT'])
def update_user_fund_group(fund_code):
    client_id, error = _require_client_id()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        result = move_user_fund(client_id, fund_code, data.get('group_id'))
        return _add_cors_headers(jsonify(result))
    except ValueError as exc:
        return _add_cors_headers(jsonify({'error': str(exc)})), 400


@app.route('/api/user/funds/<fund_code>/position', methods=['PUT'])
def update_user_fund_position(fund_code):
    client_id, error = _require_client_id()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    try:
        result = update_user_fund_position_snapshot(
            client_id,
            fund_code,
            data.get('holding_amount'),
            data.get('holding_profit'),
        )
        return _add_cors_headers(jsonify(result))
    except ValueError as exc:
        return _add_cors_headers(jsonify({'success': False, 'error': str(exc)})), 400


@app.route('/api/user/portfolio', methods=['GET'])
def get_user_portfolio_view():
    client_id, error = _require_client_id()
    if error:
        return error
    return _add_cors_headers(jsonify(get_user_portfolio(client_id)))


@app.route('/api/user/funds/<fund_code>', methods=['DELETE'])
def remove_user_fund(fund_code):
    client_id, error = _require_client_id()
    if error:
        return error
    deleted = delete_user_fund(client_id, fund_code)
    return _add_cors_headers(jsonify({'deleted': deleted}))


if __name__ == '__main__':
    debug_enabled = os.getenv('FLASK_DEBUG', '1').strip().lower() not in ('0', 'false', 'no')
    print('启动基金监控服务...')
    print('请在浏览器访问 http://127.0.0.1:5000')
    print(f'调试模式: {"on" if debug_enabled else "off"}')
    app.run(
        host='127.0.0.1',
        port=5000,
        debug=debug_enabled,
        use_reloader=debug_enabled,
    )
