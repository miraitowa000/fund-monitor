import os
import threading
import time
from datetime import datetime, timedelta
from functools import lru_cache

from sqlalchemy import delete, select, func

from core.db import session_scope
from core.models import FundTransaction, User, UserFund
from services.dashboard_cache_service import invalidate_dashboard_bootstrap
from services.fund_detail_service import get_fund_networth_history
from services.fund_service import search_funds
from services.portfolio_cache_service import invalidate_user_portfolio
from services.snapshot_cache_service import invalidate_user_snapshot
from services.trading_calendar_service import format_date, is_trading_day, next_trading_day, parse_date, resolve_trade_date
from services.user_fund_service import normalize_fund_code


CONFIRMED = 'CONFIRMED'
PENDING = 'PENDING'
BUY = 'BUY'
SELL = 'SELL'
SIP_BUY = 'SIP_BUY'
CONVERT_IN = 'CONVERT_IN'
CONVERT_OUT = 'CONVERT_OUT'

_PENDING_CONFIRM_THREAD_STARTED = False
_PENDING_CONFIRM_THREAD_LOCK = threading.Lock()


def _round_money(value):
    return round(float(value), 2)


def _round_shares(value):
    return round(float(value), 6)


def _round_nav(value):
    return round(float(value), 4)


def _to_float(value, default=None):
    if value in (None, ''):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_type(value):
    raw = str(value or '').strip().upper()
    aliases = {
        'BUY': BUY,
        'ADD': BUY,
        'SIP_BUY': SIP_BUY,
        'DCA': SIP_BUY,
        'SELL': SELL,
        'REDUCE': SELL,
        'CONVERT_IN': CONVERT_IN,
        'CONVERT_OUT': CONVERT_OUT,
    }
    normalized = aliases.get(raw)
    if not normalized:
        raise ValueError('交易类型不正确')
    return normalized


def _normalize_date(value, field_name='交易日期'):
    raw = str(value or '').strip()
    try:
        datetime.strptime(raw, '%Y-%m-%d')
    except ValueError:
        raise ValueError(f'{field_name}格式必须为 YYYY-MM-DD')
    return raw


def _find_nav_by_date(fund_code, nav_date):
    if not nav_date:
        return None
    history = get_fund_networth_history(fund_code, days=365)
    for item in history.get('data') or []:
        if str(item.get('date')) == str(nav_date):
            return _to_float(item.get('value'))
    return None


def _history_days_for_start_date(start_date):
    start = parse_date(start_date)
    today = datetime.now().date()
    return max((today - start).days + 7, 30)


def _find_first_available_nav(fund_code, start_date, max_days=30, history_rows=None):
    if not start_date:
        return None

    start = parse_date(start_date)
    today = datetime.now().date()
    if start > today:
        return None

    end = min(start + timedelta(days=max(int(max_days or 30), 1) - 1), today)
    rows = history_rows
    if rows is None:
        history = get_fund_networth_history(fund_code, days=_history_days_for_start_date(start_date))
        rows = history.get('data') if history.get('success') else []

    best = None
    for item in rows or []:
        item_date_text = str(item.get('date') or '')[:10]
        if not item_date_text:
            continue
        try:
            item_date = parse_date(item_date_text)
        except ValueError:
            continue
        if item_date < start or item_date > end:
            continue
        nav = _to_float(item.get('value'))
        if nav is None or nav <= 0:
            continue
        if best is None or item_date < best[0]:
            best = (item_date, nav)

    if not best:
        return None
    return {'nav_date': format_date(best[0]), 'nav': best[1]}


@lru_cache(maxsize=512)
def _is_qdii_fund(fund_code):
    try:
        matches = search_funds(fund_code, limit=5)
    except Exception:
        matches = []
    code = normalize_fund_code(fund_code)
    for item in matches or []:
        if str(item.get('code') or '').zfill(6) != code:
            continue
        name = str(item.get('name') or '').upper()
        return 'QDII' in name
    return False


def _shift_trading_days(date_text, days):
    current = parse_date(date_text)
    for _ in range(max(int(days or 0), 0)):
        current = next_trading_day(current)
    return format_date(current)


def _today_text():
    return datetime.now().strftime('%Y-%m-%d')


def _can_confirm(nav, confirm_date):
    if not nav or nav <= 0:
        return False
    if not confirm_date:
        return True
    return _today_text() >= str(confirm_date)


def _resolve_confirm_date(fund_code, nav_date, payload):
    explicit = str(payload.get('confirm_date') or '').strip()[:10]
    if explicit:
        return _normalize_date(explicit, '确认日期')
    if _is_qdii_fund(fund_code):
        return _shift_trading_days(nav_date, 2)
    return _shift_trading_days(nav_date, 1)


def _resolve_explicit_confirm_date(payload):
    explicit = str(payload.get('confirm_date') or '').strip()[:10]
    if explicit:
        return _normalize_date(explicit, '确认日期')
    return None


def _calculate_transaction_fields(fund_code, payload, history_rows=None):
    code = normalize_fund_code(fund_code)
    if not code.isdigit() or len(code) != 6:
        raise ValueError('基金代码格式不正确')

    tx_type = _normalize_type(payload.get('type'))
    submitted_date = payload.get('submitted_date') or payload.get('date') or payload.get('trade_date')
    if submitted_date not in (None, ''):
        submitted_date = _normalize_date(submitted_date, '申请日期')
    time_slot = payload.get('time_slot') or 'BEFORE_1500'
    if payload.get('trade_date'):
        trade_date = _normalize_date(payload.get('trade_date'))
    else:
        trade_date, time_slot = resolve_trade_date(submitted_date, time_slot)

    nav_date = str(payload.get('nav_date') or trade_date).strip()[:10]
    confirm_date = _resolve_explicit_confirm_date(payload)
    nav = _to_float(payload.get('nav'))
    if nav is None or nav <= 0:
        available_nav = _find_first_available_nav(code, nav_date, history_rows=history_rows)
        if available_nav:
            nav_date = available_nav['nav_date']
            nav = available_nav['nav']
            if not confirm_date:
                confirm_date = nav_date

    fee = _to_float(payload.get('fee'), 0.0) or 0.0
    fee_rate = _to_float(payload.get('fee_rate'))
    amount = _to_float(payload.get('amount'))
    shares = _to_float(payload.get('shares'))

    if fee < 0:
        raise ValueError('手续费不能为负数')
    if fee_rate is not None and fee_rate < 0:
        raise ValueError('费率不能为负数')

    if tx_type in (BUY, SIP_BUY, CONVERT_IN):
        if amount is None or amount <= 0:
            raise ValueError('加仓金额必须大于 0')
        if fee_rate is not None and not payload.get('fee'):
            fee = amount * fee_rate / 100
        if nav and nav > 0:
            if amount - fee <= 0:
                raise ValueError('手续费不能大于或等于加仓金额')
            shares = (amount - fee) / nav
    elif tx_type in (SELL, CONVERT_OUT):
        if shares is None or shares <= 0:
            raise ValueError('减仓份额必须大于 0')
        if nav and nav > 0:
            amount = shares * nav
            if fee_rate is not None and not payload.get('fee'):
                fee = amount * fee_rate / 100

    if nav and nav > 0 and not confirm_date:
        confirm_date = nav_date

    status = CONFIRMED if _can_confirm(nav, confirm_date) else PENDING
    return {
        'fund_code': code,
        'type': tx_type,
        'submitted_date': submitted_date,
        'time_slot': time_slot,
        'trade_date': trade_date,
        'nav_date': nav_date,
        'confirm_date': confirm_date,
        'nav': nav,
        'amount': amount,
        'fee': fee,
        'fee_rate': fee_rate,
        'shares': shares,
        'status': status,
    }


def _serialize_transaction(tx):
    return {
        'id': tx.id,
        'fund_code': tx.fund_code,
        'type': tx.transaction_type,
        'status': tx.status,
        'batch_id': tx.batch_id,
        'conversion_id': tx.conversion_id,
        'related_fund_code': tx.related_fund_code,
        'submitted_date': tx.submitted_date,
        'time_slot': tx.time_slot,
        'trade_date': tx.trade_date,
        'nav_date': tx.nav_date,
        'confirm_date': tx.confirm_date,
        'nav': _round_nav(tx.nav) if tx.nav is not None else None,
        'amount': _round_money(tx.amount) if tx.amount is not None else None,
        'fee': _round_money(tx.fee or 0),
        'fee_rate': tx.fee_rate,
        'shares': _round_shares(tx.shares) if tx.shares is not None else None,
        'realized_profit': _round_money(tx.realized_profit) if tx.realized_profit is not None else None,
        'is_dca': bool(tx.is_dca),
        'note': tx.note,
        'created_at': tx.created_at.strftime('%Y-%m-%d %H:%M:%S') if tx.created_at else None,
        'updated_at': tx.updated_at.strftime('%Y-%m-%d %H:%M:%S') if tx.updated_at else None,
    }


def _invalidate_user_view_caches_for_user_id(session, user_id):
    user = session.execute(select(User).where(User.id == user_id)).scalar_one()
    invalidate_dashboard_bootstrap(user.client_id)
    invalidate_user_snapshot(user.client_id)
    invalidate_user_portfolio(user.client_id)


def _ensure_user_fund(session, user_id, fund_code):
    fund = session.execute(
        select(UserFund).where(UserFund.user_id == user_id, UserFund.fund_code == fund_code)
    ).scalar_one_or_none()
    if fund:
        return fund

    max_sort = session.execute(
        select(UserFund.sort_order)
        .where(UserFund.user_id == user_id)
        .order_by(UserFund.sort_order.desc())
        .limit(1)
    ).scalar_one_or_none()
    fund = UserFund(
        user_id=user_id,
        fund_code=fund_code,
        sort_order=(max_sort or 0) + 1,
    )
    session.add(fund)
    user = session.execute(select(User).where(User.id == user_id)).scalar_one()
    user.initialized = True
    session.flush()
    return fund


def get_occupied_pending_shares(session, user_id, fund_code, exclude_conversion_id=None):
    query = select(func.coalesce(func.sum(FundTransaction.shares), 0.0)).where(
        FundTransaction.user_id == user_id,
        FundTransaction.fund_code == fund_code,
        FundTransaction.status == PENDING,
        FundTransaction.transaction_type.in_([SELL, CONVERT_OUT]),
    )
    if exclude_conversion_id is not None:
        query = query.where(
            (FundTransaction.conversion_id.is_(None)) |
            (FundTransaction.conversion_id != exclude_conversion_id)
        )
    return _to_float(session.execute(query).scalar_one_or_none(), 0.0) or 0.0


def get_available_confirmed_shares(session, user_id, fund_code, exclude_conversion_id=None):
    fund = session.execute(
        select(UserFund).where(UserFund.user_id == user_id, UserFund.fund_code == fund_code)
    ).scalar_one_or_none()
    holding_shares = _to_float(getattr(fund, 'holding_shares', None), 0.0) or 0.0
    occupied = get_occupied_pending_shares(
        session,
        user_id,
        fund_code,
        exclude_conversion_id=exclude_conversion_id,
    )
    return max(holding_shares - occupied, 0.0)


def validate_available_shares(session, user_id, fund_code, shares, exclude_conversion_id=None):
    required = _to_float(shares, 0.0) or 0.0
    available = get_available_confirmed_shares(
        session,
        user_id,
        fund_code,
        exclude_conversion_id=exclude_conversion_id,
    )
    if available + 0.000001 < required:
        raise ValueError('减仓份额不能大于当前可用份额')
    return available


def _rebuild_position_for_fund(session, user_id, fund_code):
    fund = _ensure_user_fund(session, user_id, fund_code)
    transactions = session.execute(
        select(FundTransaction)
        .where(
            FundTransaction.user_id == user_id,
            FundTransaction.fund_code == fund_code,
            FundTransaction.status == CONFIRMED,
        )
        .order_by(FundTransaction.trade_date.asc(), FundTransaction.id.asc())
    ).scalars().all()

    total_shares = 0.0
    total_cost = 0.0
    last_nav = None
    last_date = None

    for tx in transactions:
        nav = _to_float(tx.nav)
        fee = _to_float(tx.fee, 0.0) or 0.0
        if tx.transaction_type in (BUY, SIP_BUY, CONVERT_IN):
            amount = _to_float(tx.amount)
            if amount is None or amount <= 0 or nav is None or nav <= 0:
                continue
            shares = _to_float(tx.shares)
            if shares is None or shares <= 0:
                shares = (amount - fee) / nav
                tx.shares = _round_shares(shares)
            total_shares += shares
            total_cost += amount
            tx.realized_profit = None
            last_nav = nav
            last_date = tx.nav_date or tx.trade_date
        elif tx.transaction_type in (SELL, CONVERT_OUT):
            shares = _to_float(tx.shares)
            if shares is None or shares <= 0 or nav is None or nav <= 0:
                continue
            if shares > total_shares + 0.000001:
                raise ValueError('减仓份额不能大于当前交易流水持有份额')
            avg_cost = total_cost / total_shares if total_shares > 0 else 0
            amount = shares * nav
            cost_removed = shares * avg_cost
            proceeds = amount - fee
            tx.amount = _round_money(amount)
            tx.realized_profit = _round_money(proceeds - cost_removed)
            total_shares = max(total_shares - shares, 0.0)
            total_cost = max(total_cost - cost_removed, 0.0)
            if total_shares <= 0.000001:
                total_shares = 0.0
                total_cost = 0.0
            last_nav = nav
            last_date = tx.nav_date or tx.trade_date

    if total_shares > 0 and last_nav and last_nav > 0:
        holding_amount = total_shares * last_nav
        holding_profit = holding_amount - total_cost
        fund.holding_amount = _round_money(holding_amount)
        fund.holding_profit = _round_money(holding_profit)
        fund.cost_amount = _round_money(total_cost)
        fund.holding_shares = _round_shares(total_shares)
        fund.avg_cost_nav = _round_nav(total_cost / total_shares)
        fund.snapshot_nav = _round_nav(last_nav)
        fund.snapshot_date = last_date
        fund.position_updated_at = datetime.utcnow()
    else:
        fund.holding_amount = None
        fund.holding_profit = None
        fund.cost_amount = None
        fund.holding_shares = None
        fund.avg_cost_nav = None
        fund.snapshot_nav = None
        fund.snapshot_date = None
        fund.position_updated_at = datetime.utcnow()

    return fund


def list_fund_transactions(user_id, fund_code):
    code = normalize_fund_code(fund_code)
    confirm_pending_transactions(user_id=user_id, fund_code=code)
    with session_scope() as session:
        rows = session.execute(
            select(FundTransaction)
            .where(FundTransaction.user_id == user_id, FundTransaction.fund_code == code)
            .order_by(FundTransaction.trade_date.desc(), FundTransaction.id.desc())
        ).scalars().all()
        return {
            'success': True,
            'fund_code': code,
            'transactions': [_serialize_transaction(row) for row in rows],
        }


def _confirm_pending_tx(session, tx, history_rows=None):
    payload = {
        'type': tx.transaction_type,
        'submitted_date': tx.submitted_date,
        'time_slot': tx.time_slot,
        'trade_date': tx.trade_date,
        'nav_date': tx.nav_date,
        'amount': tx.amount,
        'shares': tx.shares,
        'fee': tx.fee,
        'fee_rate': tx.fee_rate,
    }
    calculated = _calculate_transaction_fields(tx.fund_code, payload, history_rows=history_rows)
    if calculated['status'] != CONFIRMED:
        return False

    tx.status = CONFIRMED
    tx.trade_date = calculated['trade_date']
    tx.nav_date = calculated['nav_date']
    tx.confirm_date = calculated['confirm_date']
    tx.nav = _round_nav(calculated['nav'])
    tx.amount = _round_money(calculated['amount']) if calculated['amount'] is not None else None
    tx.fee = _round_money(calculated['fee'])
    tx.fee_rate = calculated['fee_rate']
    tx.shares = _round_shares(calculated['shares']) if calculated['shares'] is not None else None
    return True


def confirm_pending_transactions(user_id=None, fund_code=None):
    code = normalize_fund_code(fund_code) if fund_code else None
    checked = 0
    confirmed = 0
    failed = 0
    with session_scope() as session:
        query = select(FundTransaction).where(
            FundTransaction.status == PENDING,
            FundTransaction.conversion_id.is_(None),
        )
        if user_id is not None:
            query = query.where(FundTransaction.user_id == user_id)
        if code:
            query = query.where(FundTransaction.fund_code == code)

        rows = session.execute(query).scalars().all()
        pairs = sorted({(row.user_id, row.fund_code) for row in rows})
        checked = len(rows)

    for pair_user_id, pair_fund_code in pairs:
        try:
            with session_scope() as session:
                rows = session.execute(
                    select(FundTransaction)
                    .where(
                        FundTransaction.status == PENDING,
                        FundTransaction.conversion_id.is_(None),
                        FundTransaction.user_id == pair_user_id,
                        FundTransaction.fund_code == pair_fund_code,
                    )
                    .order_by(FundTransaction.trade_date.asc(), FundTransaction.id.asc())
                ).scalars().all()
                history_rows = None
                if rows:
                    earliest_nav_date = min(str(tx.nav_date or tx.trade_date)[:10] for tx in rows)
                    history = get_fund_networth_history(
                        pair_fund_code,
                        days=_history_days_for_start_date(earliest_nav_date),
                    )
                    history_rows = history.get('data') if history.get('success') else []
                pair_confirmed = 0
                for tx in rows:
                    if _confirm_pending_tx(session, tx, history_rows=history_rows):
                        pair_confirmed += 1
                if pair_confirmed:
                    session.flush()
                    _rebuild_position_for_fund(session, pair_user_id, pair_fund_code)
                    _invalidate_user_view_caches_for_user_id(session, pair_user_id)
                    confirmed += pair_confirmed
        except ValueError:
            failed += 1

    return {
        'success': True,
        'checked': checked,
        'confirmed': confirmed,
        'failed_groups': failed,
    }


def _seconds_until_next_trading_midnight():
    now = datetime.now()
    candidate = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    while not is_trading_day(candidate.date()):
        candidate += timedelta(days=1)
    return max((candidate - now).total_seconds(), 1)


def _pending_confirmation_scheduler_loop():
    while True:
        time.sleep(_seconds_until_next_trading_midnight())
        try:
            confirm_pending_transactions()
            from services.fund_conversion_service import confirm_pending_conversions
            confirm_pending_conversions()
        except Exception:
            pass


def start_pending_transaction_confirmation_scheduler():
    global _PENDING_CONFIRM_THREAD_STARTED
    with _PENDING_CONFIRM_THREAD_LOCK:
        if _PENDING_CONFIRM_THREAD_STARTED:
            return False
        thread = threading.Thread(
            target=_pending_confirmation_scheduler_loop,
            name='pending-transaction-confirmation',
            daemon=True,
        )
        thread.start()
        _PENDING_CONFIRM_THREAD_STARTED = True
        return True


def preview_fund_transaction(fund_code, payload):
    calculated = _calculate_transaction_fields(fund_code, payload)
    confirmed = calculated['status'] == CONFIRMED
    return {
        'success': True,
        'fund_code': calculated['fund_code'],
        'type': calculated['type'],
        'submitted_date': calculated['submitted_date'],
        'time_slot': calculated['time_slot'],
        'trade_date': calculated['trade_date'],
        'nav_date': calculated['nav_date'],
        'confirm_date': calculated['confirm_date'],
        'nav': _round_nav(calculated['nav']) if calculated['nav'] else None,
        'amount': _round_money(calculated['amount']) if calculated['amount'] is not None else None,
        'fee': _round_money(calculated['fee']),
        'fee_rate': calculated['fee_rate'],
        'shares': _round_shares(calculated['shares']) if calculated['shares'] is not None else None,
        'status': calculated['status'],
        'confirmed': confirmed,
    }


def create_fund_transaction(user_id, fund_code, payload):
    calculated = _calculate_transaction_fields(fund_code, payload)
    code = calculated['fund_code']
    note = str(payload.get('note') or '').strip()[:255] or None
    batch_id = str(payload.get('batch_id') or '').strip()[:64] or None

    with session_scope() as session:
        if batch_id:
            existing = session.execute(
                select(FundTransaction)
                .where(
                    FundTransaction.user_id == user_id,
                    FundTransaction.batch_id == batch_id,
                )
                .order_by(FundTransaction.id.asc())
                .limit(1)
            ).scalar_one_or_none()
            if existing:
                return {
                    'success': True,
                    'transaction': _serialize_transaction(existing),
                    'status': existing.status,
                    'deduplicated': True,
                }
        _ensure_user_fund(session, user_id, code)
        if calculated['type'] in (SELL, CONVERT_OUT):
            validate_available_shares(session, user_id, code, calculated['shares'])
        tx = FundTransaction(
            user_id=user_id,
            fund_code=code,
            transaction_type=calculated['type'],
            status=calculated['status'],
            batch_id=batch_id,
            submitted_date=calculated['submitted_date'],
            time_slot=str(calculated['time_slot'] or '').strip()[:20] or None,
            trade_date=calculated['trade_date'],
            nav_date=calculated['nav_date'],
            confirm_date=calculated['confirm_date'],
            nav=_round_nav(calculated['nav']) if calculated['nav'] else None,
            amount=_round_money(calculated['amount']) if calculated['amount'] is not None else None,
            fee=_round_money(calculated['fee']),
            fee_rate=calculated['fee_rate'],
            shares=_round_shares(calculated['shares']) if calculated['shares'] is not None else None,
            is_dca=bool(payload.get('is_dca') or calculated['type'] == SIP_BUY),
            conversion_id=payload.get('conversion_id'),
            related_fund_code=normalize_fund_code(payload.get('related_fund_code')) if payload.get('related_fund_code') else None,
            note=note,
        )
        session.add(tx)
        session.flush()

        if calculated['status'] == CONFIRMED:
            _rebuild_position_for_fund(session, user_id, code)
        _invalidate_user_view_caches_for_user_id(session, user_id)
        session.flush()
        return {
            'success': True,
            'transaction': _serialize_transaction(tx),
            'status': calculated['status'],
        }


def delete_fund_transaction(user_id, transaction_id):
    with session_scope() as session:
        tx = session.execute(
            select(FundTransaction).where(
                FundTransaction.user_id == user_id,
                FundTransaction.id == int(transaction_id),
            )
        ).scalar_one_or_none()
        if not tx:
            return {'success': True, 'deleted': False}
        fund_code = tx.fund_code
        session.execute(delete(FundTransaction).where(FundTransaction.id == tx.id))
        session.flush()
        _rebuild_position_for_fund(session, user_id, fund_code)
        _invalidate_user_view_caches_for_user_id(session, user_id)
        return {'success': True, 'deleted': True, 'fund_code': fund_code}
