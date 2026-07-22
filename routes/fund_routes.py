from concurrent.futures import as_completed

from flask import Blueprint, request

from core.runtime import FUNDS_EXECUTOR, register_watched_codes
from routes.common import json_response
from services.fund_service import (
    calculate_fund_performance,
    fetch_funds_parallel,
    get_fund_details,
    get_fund_networth_history,
    get_fund_trend_comparison,
    get_intraday_series,
    get_intraday_today_text,
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
    days = max(7, min(days, 380))
    return json_response(get_fund_networth_history(fund_code, days=days))


@fund_bp.route('/api/fund/<fund_code>/trend-comparison', methods=['GET'])
def get_fund_trend_comparison_view(fund_code):
    days = request.args.get('days', default=90, type=int)
    return json_response(get_fund_trend_comparison(fund_code, days=days))


@fund_bp.route('/api/funds/performance', methods=['POST'])
def get_funds_performance():
    data = request.get_json(silent=True) or {}
    raw_codes = data.get('codes') or []
    ranges = data.get('ranges') or [7, 30, 90, 180, 365]
    codes = []
    seen = set()
    for code in raw_codes:
        normalized = str(code or '').strip().zfill(6)
        if not normalized.isdigit() or len(normalized) != 6 or normalized in seen:
            continue
        seen.add(normalized)
        codes.append(normalized)
    codes = codes[:200]
    register_watched_codes(codes)

    futures = {
        FUNDS_EXECUTOR.submit(calculate_fund_performance, code, ranges): code
        for code in codes
    }
    result = {}
    for future in as_completed(futures):
        code = futures[future]
        try:
            result[code] = future.result()
        except Exception as exc:
            result[code] = {
                'code': code,
                'success': False,
                'ranges': {},
                'error': str(exc),
            }
    return json_response({'success': True, 'items': result})


@fund_bp.route('/api/funds/intraday-series', methods=['POST'])
def get_funds_intraday_series():
    data = request.get_json(silent=True) or {}
    raw_codes = data.get('codes') or []
    codes = []
    seen = set()
    for code in raw_codes:
        normalized = str(code or '').strip().zfill(6)
        if not normalized.isdigit() or len(normalized) != 6 or normalized in seen:
            continue
        seen.add(normalized)
        codes.append(normalized)
    codes = codes[:500]
    register_watched_codes(codes)
    day_text = data.get('date') or get_intraday_today_text()
    return json_response({
        'success': True,
        'date': day_text,
        'items': get_intraday_series(codes, day_text=day_text),
    })


@fund_bp.route('/api/fund/search', methods=['GET'])
def api_search_funds():
    keyword = request.args.get('q', default='', type=str)
    limit = request.args.get('limit', default=10, type=int)
    return json_response(search_funds(keyword, limit=limit))
