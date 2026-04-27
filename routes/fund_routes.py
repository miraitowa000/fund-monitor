from flask import Blueprint, request

from core.runtime import register_watched_codes
from routes.common import json_response
from services.fund_service import (
    fetch_funds_parallel,
    get_fund_details,
    get_fund_networth_history,
    search_funds,
)
from services.index_service import get_indexes


fund_bp = Blueprint('fund_api', __name__)


@fund_bp.route('/api/funds', methods=['POST'])
def get_funds():
    data = request.get_json()
    if not data or 'codes' not in data:
        return json_response({'error': 'Missing "codes" parameter'}, 400)

    codes = data['codes']
    register_watched_codes(codes)
    return json_response(fetch_funds_parallel(codes))


@fund_bp.route('/api/funds', methods=['OPTIONS'])
def options_funds():
    return json_response({'status': 'ok'})


@fund_bp.route('/api/indexes', methods=['GET'])
def api_indexes():
    return json_response(get_indexes())


@fund_bp.route('/api/fund/<fund_code>', methods=['GET'])
def get_fund_detail(fund_code):
    return json_response(get_fund_details(fund_code))


@fund_bp.route('/api/fund/<fund_code>/history', methods=['GET'])
def get_fund_history(fund_code):
    days = request.args.get('days', default=30, type=int)
    days = max(30, min(days, 365))
    return json_response(get_fund_networth_history(fund_code, days=days))


@fund_bp.route('/api/fund/search', methods=['GET'])
def api_search_funds():
    keyword = request.args.get('q', default='', type=str)
    limit = request.args.get('limit', default=10, type=int)
    return json_response(search_funds(keyword, limit=limit))
