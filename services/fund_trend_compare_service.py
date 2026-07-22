from datetime import datetime, timedelta

from core.time_utils import timestamp_to_china_datetime
from services.fund_basic_service import get_pingzhongdata_snapshot
from services.user_fund_service import normalize_fund_code


RANGE_DAYS = {
    30: 30,
    90: 90,
    180: 180,
    365: 365,
}


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date_from_timestamp(value):
    try:
        return timestamp_to_china_datetime(float(value) / 1000).date()
    except Exception:
        return None


def _normalize_days(days):
    try:
        value = int(days or 90)
    except Exception:
        value = 90
    return RANGE_DAYS.get(value, 90)


def _fund_rows(snapshot, start_date, end_date):
    rows = []
    for item in snapshot.get('networth') or []:
        if not isinstance(item, dict):
            continue
        item_date = _date_from_timestamp(item.get('x'))
        value = _to_float(item.get('y'))
        if not item_date or value is None or value <= 0:
            continue
        if item_date < start_date or item_date > end_date:
            continue
        rows.append({'date': item_date.strftime('%Y-%m-%d'), 'raw': value})
    rows.sort(key=lambda row: row['date'])
    return rows


def _comparison_series(snapshot, start_date, end_date):
    result = []
    for series in snapshot.get('grand_total') or []:
        if not isinstance(series, dict):
            continue
        points = []
        for item in series.get('data') or []:
            if not isinstance(item, list) or len(item) < 2:
                continue
            item_date = _date_from_timestamp(item[0])
            value = _to_float(item[1])
            if not item_date or value is None:
                continue
            if item_date < start_date or item_date > end_date:
                continue
            points.append({'date': item_date.strftime('%Y-%m-%d'), 'raw': value})
        points.sort(key=lambda row: row['date'])
        if points:
            result.append({'name': str(series.get('name') or '').strip(), 'points': points})
    return result


def _normalize_from_nav(rows):
    if not rows:
        return []
    base = rows[0]['raw']
    if not base:
        return []
    return [
        {'date': row['date'], 'value': round(((row['raw'] - base) / base) * 100, 2)}
        for row in rows
    ]


def _normalize_from_percent(rows):
    if not rows:
        return []
    base = rows[0]['raw']
    return [
        {'date': row['date'], 'value': round(row['raw'] - base, 2)}
        for row in rows
    ]


def get_fund_trend_comparison(fund_code, days=90):
    code = normalize_fund_code(fund_code)
    days = _normalize_days(days)
    snapshot = get_pingzhongdata_snapshot(code)
    if not snapshot:
        return {'success': False, 'fund_code': code, 'days': days, 'series': [], 'error': '暂无走势数据'}

    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)
    fund_raw = _fund_rows(snapshot, start_date, end_date)
    if not fund_raw:
        return {'success': False, 'fund_code': code, 'days': days, 'series': [], 'error': '暂无基金走势数据'}

    # Align the comparison start with the first actual fund NAV date in this range.
    effective_start = datetime.strptime(fund_raw[0]['date'], '%Y-%m-%d').date()
    fund_raw = [row for row in fund_raw if row['date'] >= effective_start.strftime('%Y-%m-%d')]

    series = [{
        'key': 'fund',
        'name': '本基金',
        'data': _normalize_from_nav(fund_raw),
    }]

    comparison = _comparison_series(snapshot, effective_start, end_date)
    # Eastmoney's first Data_grandTotal line is commonly the fund itself or an unsuitable duplicate.
    visible_comparison = comparison[1:] if len(comparison) > 1 else comparison
    for index, item in enumerate(visible_comparison):
        name = item.get('name') or f'对比{index + 1}'
        points = _normalize_from_percent(item.get('points') or [])
        if points:
            series.append({
                'key': f'comparison_{index + 1}',
                'name': name,
                'data': points,
            })

    summary = {}
    for item in series:
        data = item.get('data') or []
        summary[item['key']] = data[-1]['value'] if data else None

    return {
        'success': True,
        'fund_code': code,
        'days': days,
        'series': series,
        'summary': summary,
    }
