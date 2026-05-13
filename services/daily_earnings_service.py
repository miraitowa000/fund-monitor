from datetime import datetime, timedelta

from sqlalchemy import select

from core.db import session_scope
from core.models import FundTransaction
from services.fund_detail_service import get_fund_networth_history
from services.fund_transaction_service import (
    BUY,
    CONFIRMED,
    CONVERT_IN,
    CONVERT_OUT,
    SELL,
    SIP_BUY,
    _to_float,
)
from services.trading_calendar_service import format_date, parse_date
from services.user_fund_service import normalize_fund_code


POSITION_IN_TYPES = {BUY, SIP_BUY, CONVERT_IN}
POSITION_OUT_TYPES = {SELL, CONVERT_OUT}


def _round_money(value):
    return round(float(value), 2)


def _round_rate(value):
    return round(float(value), 4)


def _date_range(start_date, end_date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _normalize_range(start, end):
    today = datetime.now().date()
    end_date = parse_date(end) if end else today
    start_date = parse_date(start) if start else end_date - timedelta(days=30)
    if start_date > end_date:
        raise ValueError('start must be before end')
    if (end_date - start_date).days > 370:
        raise ValueError('date range cannot exceed 370 days')
    return start_date, end_date


def _fetch_confirmed_transactions(user_id, start_date, end_date):
    start_text = format_date(start_date - timedelta(days=370))
    end_text = format_date(end_date)
    with session_scope() as session:
        return session.execute(
            select(FundTransaction)
            .where(
                FundTransaction.user_id == user_id,
                FundTransaction.status == CONFIRMED,
                FundTransaction.nav_date <= end_text,
                FundTransaction.nav_date >= start_text,
            )
            .order_by(FundTransaction.nav_date.asc(), FundTransaction.id.asc())
        ).scalars().all()


def _build_nav_map(fund_code, start_date, end_date):
    days = max((end_date - start_date).days + 8, 30)
    history = get_fund_networth_history(fund_code, days=days)
    items = history.get('data') if history.get('success') else []
    return {
        str(item.get('date')): _to_float(item.get('value'))
        for item in items or []
        if item.get('date') and _to_float(item.get('value')) is not None
    }


def _transaction_delta(tx):
    shares = _to_float(tx.shares, 0.0) or 0.0
    if tx.transaction_type in POSITION_IN_TYPES:
        return shares
    if tx.transaction_type in POSITION_OUT_TYPES:
        return -shares
    return 0.0


def get_daily_earnings(user_id, start=None, end=None):
    start_date, end_date = _normalize_range(start, end)
    transactions = _fetch_confirmed_transactions(user_id, start_date, end_date)
    fund_codes = sorted({normalize_fund_code(tx.fund_code) for tx in transactions if tx.fund_code})
    nav_maps = {
        code: _build_nav_map(code, start_date - timedelta(days=8), end_date)
        for code in fund_codes
    }

    tx_by_date = {}
    for tx in transactions:
        nav_date = str(tx.nav_date or tx.trade_date or '')[:10]
        if not nav_date:
            continue
        tx_by_date.setdefault(nav_date, []).append(tx)

    shares_by_code = {code: 0.0 for code in fund_codes}
    previous_nav_by_code = {}
    days = []

    replay_start = min(start_date, min((parse_date(str(tx.nav_date or tx.trade_date)[:10]) for tx in transactions), default=start_date))
    for current in _date_range(replay_start, end_date):
        date_text = format_date(current)
        previous_shares = dict(shares_by_code)

        day_profit = 0.0
        day_base_amount = 0.0
        item_rows = []
        has_profit = False

        if current >= start_date:
            for code in fund_codes:
                nav = nav_maps.get(code, {}).get(date_text)
                prev_nav = previous_nav_by_code.get(code)
                shares = previous_shares.get(code, 0.0) or 0.0
                if nav is None:
                    continue
                if prev_nav is not None and shares > 0:
                    profit = shares * (nav - prev_nav)
                    base_amount = shares * prev_nav
                    day_profit += profit
                    day_base_amount += base_amount
                    has_profit = True
                    item_rows.append({
                        'code': code,
                        'shares': round(shares, 6),
                        'nav': round(nav, 4),
                        'previous_nav': round(prev_nav, 4),
                        'profit': _round_money(profit),
                        'base_amount': _round_money(base_amount),
                        'rate': _round_rate(profit / base_amount) if base_amount > 0 else None,
                    })

        for tx in tx_by_date.get(date_text, []):
            code = normalize_fund_code(tx.fund_code)
            shares_by_code[code] = max((shares_by_code.get(code, 0.0) or 0.0) + _transaction_delta(tx), 0.0)

        for code in fund_codes:
            nav = nav_maps.get(code, {}).get(date_text)
            if nav is not None:
                previous_nav_by_code[code] = nav

        if current >= start_date and has_profit:
            days.append({
                'date': date_text,
                'profit': _round_money(day_profit),
                'rate': _round_rate(day_profit / day_base_amount) if day_base_amount > 0 else None,
                'base_amount': _round_money(day_base_amount) if day_base_amount > 0 else 0,
                'items': item_rows,
            })

    total_profit = sum(item['profit'] for item in days)
    total_base = sum(item.get('base_amount') or 0 for item in days)
    return {
        'success': True,
        'start': format_date(start_date),
        'end': format_date(end_date),
        'summary': {
            'total_profit': _round_money(total_profit),
            'total_rate': _round_rate(total_profit / total_base) if total_base > 0 else None,
            'profit_days': len([item for item in days if item['profit'] > 0]),
            'loss_days': len([item for item in days if item['profit'] < 0]),
            'flat_days': len([item for item in days if item['profit'] == 0]),
        },
        'days': sorted(days, key=lambda item: item['date'], reverse=True),
    }
