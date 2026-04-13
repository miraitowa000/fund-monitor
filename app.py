from flask import Flask, jsonify, render_template, request

from core.runtime import register_watched_codes
from services.fund_service import (
    fetch_funds_parallel,
    get_fund_details,
    start_background_refresh_thread,
)
from services.index_service import get_indexes


app = Flask(__name__, static_folder='static', template_folder='templates')

# Avoid conflict with Vue template syntax
app.jinja_env.variable_start_string = '{%{'
app.jinja_env.variable_end_string = '}%}'

start_background_refresh_thread()


def _add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


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


if __name__ == '__main__':
    print('启动基金监控服务...')
    print('请在浏览器访问 http://127.0.0.1:5000')
