from datetime import datetime

from services.fund_service import fetch_funds_parallel
from services.user_fund_service import list_user_funds


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_money(value):
    return round(float(value), 2)


def _round_rate(value):
    return round(float(value), 4)


def _round_shares(value):
    return round(float(value), 6)


def _round_nav(value):
    return round(float(value), 4)


def _build_quote_map(quotes):
    result = {}
    for item in quotes or []:
        code = str((item or {}).get('code') or '').zfill(6)
        if code:
            result[code] = item or {}
    return result


def _pick_current_nav(quote):
    if not quote:
        return None, None, None
    if quote.get('nav_confirmed') and quote.get('confirmed_nav') not in (None, '', '-'):
        return _to_float(quote.get('confirmed_nav')), quote.get('confirmed_date') or quote.get('jzrq'), 'confirmed'
    nav = _to_float(quote.get('gsz'))
    return nav, quote.get('display_date') or quote.get('gztime'), 'estimated'


def _should_freeze_snapshot_values(meta, current_nav_date, current_nav_source):
    position_updated_at = str(meta.get('position_updated_at') or '').split(' ')[0]
    current_date = str(current_nav_date or '').split(' ')[0]
    if not position_updated_at or not current_date:
        return False
    return (
        position_updated_at == current_date
        and current_nav_source != 'confirmed'
    )


def _build_position_item(meta, quote, total_holding_amount=0.0):
    current_nav, current_nav_date, current_nav_source = _pick_current_nav(quote)
    previous_nav = _to_float((quote or {}).get('dwjz'))
    daily_change_pct = _to_float(
        (quote or {}).get('confirmed_change') if (quote or {}).get('nav_confirmed') else (quote or {}).get('gszzl')
    )

    item = {
        'code': meta.get('code'),
        'name': (quote or {}).get('name') or meta.get('code'),
        'group_id': meta.get('group_id'),
        'group_name': meta.get('group_name') or '',
        'has_position': bool(meta.get('has_position')),
        'current_nav': _round_nav(current_nav) if current_nav is not None else None,
        'current_nav_date': str(current_nav_date or '').split(' ')[0] or None,
        'current_nav_source': current_nav_source if current_nav is not None else None,
        'previous_nav': _round_nav(previous_nav) if previous_nav is not None else None,
        'daily_change_pct': round(daily_change_pct, 2) if daily_change_pct is not None else None,
        'holding_amount': None,
        'holding_profit': None,
        'holding_profit_rate': None,
        'daily_profit': None,
        'daily_profit_rate': None,
        'cost_amount': meta.get('cost_amount'),
        'holding_shares': meta.get('holding_shares'),
        'avg_cost_nav': meta.get('avg_cost_nav'),
        'snapshot_holding_amount': meta.get('snapshot_holding_amount'),
        'snapshot_holding_profit': meta.get('snapshot_holding_profit'),
        'snapshot_nav': meta.get('snapshot_nav'),
        'snapshot_date': meta.get('snapshot_date'),
        'position_updated_at': meta.get('position_updated_at'),
        'position_ratio': None,
    }

    if not item['has_position']:
        return item

    shares = _to_float(meta.get('holding_shares'))
    cost_amount = _to_float(meta.get('cost_amount'))
    if shares is None or shares <= 0 or cost_amount is None or cost_amount <= 0 or current_nav is None or current_nav <= 0:
        item['has_position'] = False
        return item

    live_holding_amount = shares * current_nav
    live_holding_profit = live_holding_amount - cost_amount
    live_holding_profit_rate = live_holding_profit / cost_amount if cost_amount > 0 else None
    previous_holding_amount = shares * previous_nav if previous_nav is not None else None
    daily_profit = shares * (current_nav - previous_nav) if previous_nav is not None else None
    daily_profit_rate = (daily_profit / previous_holding_amount) if (daily_profit is not None and previous_holding_amount and previous_holding_amount > 0) else None

    if _should_freeze_snapshot_values(meta, current_nav_date, current_nav_source):
        display_holding_amount = _to_float(meta.get('snapshot_holding_amount'))
        display_holding_profit = _to_float(meta.get('snapshot_holding_profit'))
        display_holding_profit_rate = (display_holding_profit / cost_amount) if (display_holding_profit is not None and cost_amount > 0) else None
    else:
        display_holding_amount = live_holding_amount
        display_holding_profit = live_holding_profit
        display_holding_profit_rate = live_holding_profit_rate

    item['holding_amount'] = _round_money(display_holding_amount) if display_holding_amount is not None else None
    item['holding_profit'] = _round_money(display_holding_profit) if display_holding_profit is not None else None
    item['holding_profit_rate'] = _round_rate(display_holding_profit_rate) if display_holding_profit_rate is not None else None
    item['daily_profit'] = _round_money(daily_profit) if daily_profit is not None else None
    item['daily_profit_rate'] = _round_rate(daily_profit_rate) if daily_profit_rate is not None else None
    item['cost_amount'] = _round_money(cost_amount)
    item['holding_shares'] = _round_shares(shares)
    item['avg_cost_nav'] = _round_nav(meta.get('avg_cost_nav')) if meta.get('avg_cost_nav') is not None else None

    if total_holding_amount > 0:
        item['position_ratio'] = _round_rate((display_holding_amount or 0.0) / total_holding_amount)

    return item


def get_user_portfolio(client_id):
    user_funds = list_user_funds(client_id)
    codes = [item['code'] for item in user_funds]
    quotes = fetch_funds_parallel(codes) if codes else []
    quote_map = _build_quote_map(quotes)

    items = []
    total_holding_amount = 0.0
    total_daily_profit = 0.0
    total_holding_profit = 0.0
    total_previous_holding_amount = 0.0
    position_fund_count = 0

    for meta in user_funds:
        code = str(meta.get('code') or '').zfill(6)
        quote = quote_map.get(code, {})
        item = _build_position_item(meta, quote)
        items.append(item)
        if item.get('has_position') and item.get('holding_amount') is not None:
            total_holding_amount += item['holding_amount']
            total_holding_profit += item['holding_profit'] or 0.0
            total_daily_profit += item['daily_profit'] or 0.0
            shares = _to_float(item.get('holding_shares'))
            previous_nav = _to_float(item.get('previous_nav'))
            if shares is not None and shares > 0 and previous_nav is not None and previous_nav > 0:
                total_previous_holding_amount += shares * previous_nav
            position_fund_count += 1

    if total_holding_amount > 0:
        for item in items:
            if item.get('has_position') and item.get('holding_amount') is not None:
                item['position_ratio'] = _round_rate(item['holding_amount'] / total_holding_amount)

    total_cost_amount = total_holding_amount - total_holding_profit
    total_holding_profit_rate = (total_holding_profit / total_cost_amount) if total_cost_amount > 0 else None
    total_daily_profit_rate = (total_daily_profit / total_previous_holding_amount) if total_previous_holding_amount > 0 else None

    nav_sources = {item.get('current_nav_source') for item in items if item.get('current_nav_source')}
    if len(nav_sources) > 1:
        nav_source = 'mixed'
    elif len(nav_sources) == 1:
        nav_source = nav_sources.pop()
    else:
        nav_source = None

    return {
        'success': True,
        'summary': {
            'total_holding_amount': _round_money(total_holding_amount),
            'total_daily_profit': _round_money(total_daily_profit),
            'total_daily_profit_rate': _round_rate(total_daily_profit_rate) if total_daily_profit_rate is not None else None,
            'total_holding_profit': _round_money(total_holding_profit),
            'total_holding_profit_rate': _round_rate(total_holding_profit_rate) if total_holding_profit_rate is not None else None,
            'position_fund_count': position_fund_count,
            'unpositioned_fund_count': max(len(user_funds) - position_fund_count, 0),
            'nav_source': nav_source,
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        },
        'items': items,
    }
