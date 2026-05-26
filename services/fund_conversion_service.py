import uuid
from datetime import datetime

from sqlalchemy import select

from core.db import session_scope
from core.models import FundConversion, FundTransaction
from services.fund_transaction_service import (
    CONFIRMED,
    CONVERT_IN,
    CONVERT_OUT,
    PENDING,
    _find_first_available_nav,
    get_available_confirmed_shares,
    _invalidate_user_view_caches_for_user_id,
    _is_qdii_fund,
    _rebuild_position_for_fund,
    _round_money,
    _round_nav,
    _round_shares,
    _shift_trading_days,
    _to_float,
)
from services.trading_calendar_service import format_date, parse_date, resolve_trade_date
from services.user_fund_service import normalize_fund_code


STATUS_PENDING = 'PENDING'
STATUS_OUT_CONFIRMED = 'OUT_CONFIRMED'
STATUS_CONFIRMED = 'CONFIRMED'
STATUS_FAILED = 'FAILED'


def _today_text():
    return datetime.now().strftime('%Y-%m-%d')


def _normalize_date(value, field_name):
    return format_date(parse_date(value, field_name))


def _confirm_date_for_fund(fund_code, nav_date):
    days = 2 if _is_qdii_fund(fund_code) else 1
    return _shift_trading_days(nav_date, days)


def _normalize_payload(payload):
    data = payload or {}
    from_code = normalize_fund_code(data.get('from_fund_code') or data.get('fund_code'))
    to_code = normalize_fund_code(data.get('to_fund_code'))
    if not from_code.isdigit() or len(from_code) != 6:
        raise ValueError('转出基金代码格式不正确')
    if not to_code.isdigit() or len(to_code) != 6:
        raise ValueError('转入基金代码格式不正确')
    if from_code == to_code:
        raise ValueError('转入基金不能和转出基金相同')

    shares = _to_float(data.get('shares') or data.get('from_shares'))
    if shares is None or shares <= 0:
        raise ValueError('转出份额必须大于 0')

    submitted_date = _normalize_date(data.get('submitted_date'), 'submitted_date')
    time_slot = data.get('time_slot') or 'BEFORE_1500'
    from_fee_rate = _to_float(data.get('from_fee_rate'), 0.0) or 0.0
    to_fee_rate = _to_float(data.get('to_fee_rate'), 0.0) or 0.0
    supplement_fee_rate = _to_float(data.get('supplement_fee_rate'), 0.0) or 0.0
    if from_fee_rate < 0 or to_fee_rate < 0 or supplement_fee_rate < 0:
        raise ValueError('费率不能为负数')

    return {
        'from_fund_code': from_code,
        'to_fund_code': to_code,
        'from_shares': shares,
        'submitted_date': submitted_date,
        'time_slot': time_slot,
        'from_fee_rate': from_fee_rate,
        'to_fee_rate': to_fee_rate,
        'supplement_fee_rate': supplement_fee_rate,
    }


def _validate_available_shares(session, user_id, fund_code, shares, exclude_conversion_id=None):
    available = get_available_confirmed_shares(
        session,
        user_id,
        fund_code,
        exclude_conversion_id=exclude_conversion_id,
    )
    if available + 0.000001 < shares:
        raise ValueError('转出份额不能大于当前持有份额')
    return available


def _calculate_conversion(data):
    from_start_date, time_slot = resolve_trade_date(data['submitted_date'], data['time_slot'])
    to_start_date = from_start_date

    from_available = _find_first_available_nav(data['from_fund_code'], from_start_date)
    to_available = _find_first_available_nav(data['to_fund_code'], to_start_date)
    from_nav_date = from_available['nav_date'] if from_available else from_start_date
    to_nav_date = to_available['nav_date'] if to_available else to_start_date
    from_nav = from_available['nav'] if from_available else None
    to_nav = to_available['nav'] if to_available else None
    from_confirm_date = from_nav_date if from_available else _confirm_date_for_fund(data['from_fund_code'], from_start_date)
    to_confirm_date = to_nav_date if to_available else _confirm_date_for_fund(data['to_fund_code'], to_start_date)
    from_amount = data['from_shares'] * from_nav if from_nav else None
    from_fee = from_amount * data['from_fee_rate'] / 100 if from_amount is not None else 0.0
    out_net_amount = from_amount - from_fee if from_amount is not None else None
    supplement_fee = out_net_amount * data['supplement_fee_rate'] / 100 if out_net_amount is not None else 0.0
    to_fee = out_net_amount * data['to_fee_rate'] / 100 if out_net_amount is not None else 0.0
    to_amount = out_net_amount - supplement_fee - to_fee if out_net_amount is not None else None
    to_shares = to_amount / to_nav if (to_amount is not None and to_nav and to_nav > 0) else None
    confirm_date = max(from_confirm_date, to_confirm_date)
    status = STATUS_CONFIRMED if (_today_text() >= confirm_date and from_nav and to_nav) else STATUS_PENDING

    return {
        **data,
        'time_slot': time_slot,
        'from_start_date': from_start_date,
        'to_start_date': to_start_date,
        'from_nav_date': from_nav_date,
        'from_confirm_date': from_confirm_date,
        'from_nav': from_nav,
        'from_amount': from_amount,
        'from_fee': from_fee,
        'to_nav_date': to_nav_date,
        'to_confirm_date': to_confirm_date,
        'to_nav': to_nav,
        'to_amount': to_amount,
        'to_fee': to_fee,
        'to_shares': to_shares,
        'supplement_fee': supplement_fee,
        'confirm_date': confirm_date,
        'status': status,
    }


def _serialize_conversion(row):
    return {
        'id': row.id,
        'batch_id': row.batch_id,
        'from_fund_code': row.from_fund_code,
        'to_fund_code': row.to_fund_code,
        'status': row.status,
        'submitted_date': row.submitted_date,
        'time_slot': row.time_slot,
        'from_shares': _round_shares(row.from_shares),
        'from_nav_date': row.from_nav_date,
        'from_confirm_date': row.from_confirm_date,
        'from_nav': _round_nav(row.from_nav) if row.from_nav is not None else None,
        'from_amount': _round_money(row.from_amount) if row.from_amount is not None else None,
        'from_fee_rate': row.from_fee_rate,
        'from_fee': _round_money(row.from_fee),
        'to_nav_date': row.to_nav_date,
        'to_confirm_date': row.to_confirm_date,
        'to_nav': _round_nav(row.to_nav) if row.to_nav is not None else None,
        'to_amount': _round_money(row.to_amount) if row.to_amount is not None else None,
        'to_fee_rate': row.to_fee_rate,
        'to_fee': _round_money(row.to_fee),
        'to_shares': _round_shares(row.to_shares) if row.to_shares is not None else None,
        'supplement_fee_rate': row.supplement_fee_rate,
        'supplement_fee': _round_money(row.supplement_fee),
        'created_at': row.created_at.strftime('%Y-%m-%d %H:%M:%S') if row.created_at else None,
    }


def preview_conversion(user_id, payload):
    data = _normalize_payload(payload)
    with session_scope() as session:
        available = _validate_available_shares(session, user_id, data['from_fund_code'], data['from_shares'])
    calculated = _calculate_conversion(data)
    def _preview_value(key, value):
        if key.endswith('_amount') or key.endswith('_fee'):
            return _round_money(value) if value is not None else None
        return value
    return {
        'success': True,
        'available_shares': _round_shares(available),
        **{
            key: _preview_value(key, value)
            for key, value in calculated.items()
            if key not in ('from_nav', 'to_nav', 'from_shares', 'to_shares')
        },
        'from_nav': _round_nav(calculated['from_nav']) if calculated['from_nav'] else None,
        'to_nav': _round_nav(calculated['to_nav']) if calculated['to_nav'] else None,
        'from_shares': _round_shares(calculated['from_shares']),
        'to_shares': _round_shares(calculated['to_shares']) if calculated['to_shares'] is not None else None,
        'confirmed': calculated['status'] == STATUS_CONFIRMED,
    }


def _build_transaction(row, tx_type):
    is_out = tx_type == CONVERT_OUT
    return FundTransaction(
        user_id=row.user_id,
        fund_code=row.from_fund_code if is_out else row.to_fund_code,
        transaction_type=tx_type,
        status=CONFIRMED if row.status == STATUS_CONFIRMED else PENDING,
        batch_id=row.batch_id,
        conversion_id=row.id,
        related_fund_code=row.to_fund_code if is_out else row.from_fund_code,
        submitted_date=row.submitted_date,
        time_slot=row.time_slot,
        trade_date=row.from_nav_date if is_out else row.to_nav_date,
        nav_date=row.from_nav_date if is_out else row.to_nav_date,
        confirm_date=row.from_confirm_date if is_out else row.to_confirm_date,
        nav=_round_nav(row.from_nav if is_out else row.to_nav) if (row.from_nav if is_out else row.to_nav) else None,
        amount=_round_money(row.from_amount if is_out else row.to_amount) if (row.from_amount if is_out else row.to_amount) is not None else None,
        fee=_round_money(row.from_fee if is_out else (row.to_fee + row.supplement_fee)),
        fee_rate=row.from_fee_rate if is_out else row.to_fee_rate,
        shares=_round_shares(row.from_shares if is_out else row.to_shares) if (row.from_shares if is_out else row.to_shares) is not None else None,
    )


def create_conversion(user_id, payload):
    data = _normalize_payload(payload)
    with session_scope() as session:
        _validate_available_shares(session, user_id, data['from_fund_code'], data['from_shares'])
        calculated = _calculate_conversion(data)
        row = FundConversion(
            user_id=user_id,
            batch_id=f'convert:{user_id}:{uuid.uuid4().hex[:16]}',
            from_fund_code=calculated['from_fund_code'],
            to_fund_code=calculated['to_fund_code'],
            status=calculated['status'],
            submitted_date=calculated['submitted_date'],
            time_slot=calculated['time_slot'],
            from_shares=_round_shares(calculated['from_shares']),
            from_nav_date=calculated['from_nav_date'],
            from_confirm_date=calculated['from_confirm_date'],
            from_nav=_round_nav(calculated['from_nav']) if calculated['from_nav'] else None,
            from_amount=_round_money(calculated['from_amount']) if calculated['from_amount'] is not None else None,
            from_fee_rate=calculated['from_fee_rate'],
            from_fee=_round_money(calculated['from_fee']),
            to_nav_date=calculated['to_nav_date'],
            to_confirm_date=calculated['to_confirm_date'],
            to_nav=_round_nav(calculated['to_nav']) if calculated['to_nav'] else None,
            to_amount=_round_money(calculated['to_amount']) if calculated['to_amount'] is not None else None,
            to_fee_rate=calculated['to_fee_rate'],
            to_fee=_round_money(calculated['to_fee']),
            to_shares=_round_shares(calculated['to_shares']) if calculated['to_shares'] is not None else None,
            supplement_fee_rate=calculated['supplement_fee_rate'],
            supplement_fee=_round_money(calculated['supplement_fee']),
        )
        session.add(row)
        session.flush()
        session.add(_build_transaction(row, CONVERT_OUT))
        session.add(_build_transaction(row, CONVERT_IN))
        session.flush()
        if row.status == STATUS_CONFIRMED:
            _rebuild_position_for_fund(session, user_id, row.from_fund_code)
            _rebuild_position_for_fund(session, user_id, row.to_fund_code)
        _invalidate_user_view_caches_for_user_id(session, user_id)
        return {'success': True, 'conversion': _serialize_conversion(row)}


def confirm_pending_conversions(user_id=None, fund_code=None):
    code = normalize_fund_code(fund_code) if fund_code else None
    confirmed = 0
    with session_scope() as session:
        query = select(FundConversion).where(FundConversion.status != STATUS_CONFIRMED)
        if user_id is not None:
            query = query.where(FundConversion.user_id == user_id)
        if code:
            query = query.where((FundConversion.from_fund_code == code) | (FundConversion.to_fund_code == code))
        rows = session.execute(query).scalars().all()
        touched = set()
        for row in rows:
            _validate_available_shares(
                session,
                row.user_id,
                row.from_fund_code,
                row.from_shares,
                exclude_conversion_id=row.id,
            )
            calculated = _calculate_conversion({
                'from_fund_code': row.from_fund_code,
                'to_fund_code': row.to_fund_code,
                'from_shares': row.from_shares,
                'submitted_date': row.submitted_date,
                'time_slot': row.time_slot,
                'from_fee_rate': row.from_fee_rate,
                'to_fee_rate': row.to_fee_rate,
                'supplement_fee_rate': row.supplement_fee_rate,
            })
            if calculated['status'] != STATUS_CONFIRMED:
                continue
            row.status = STATUS_CONFIRMED
            row.from_nav_date = calculated['from_nav_date']
            row.from_confirm_date = calculated['from_confirm_date']
            row.from_nav = _round_nav(calculated['from_nav'])
            row.from_amount = _round_money(calculated['from_amount'])
            row.from_fee = _round_money(calculated['from_fee'])
            row.to_nav_date = calculated['to_nav_date']
            row.to_confirm_date = calculated['to_confirm_date']
            row.to_nav = _round_nav(calculated['to_nav'])
            row.to_amount = _round_money(calculated['to_amount'])
            row.to_fee = _round_money(calculated['to_fee'])
            row.to_shares = _round_shares(calculated['to_shares'])
            row.supplement_fee = _round_money(calculated['supplement_fee'])
            txs = session.execute(select(FundTransaction).where(FundTransaction.conversion_id == row.id)).scalars().all()
            for tx in txs:
                tx.status = CONFIRMED
                if tx.transaction_type == CONVERT_OUT:
                    tx.trade_date = row.from_nav_date
                    tx.nav_date = row.from_nav_date
                    tx.confirm_date = row.from_confirm_date
                    tx.nav = row.from_nav
                    tx.amount = row.from_amount
                    tx.fee = row.from_fee
                    tx.shares = row.from_shares
                elif tx.transaction_type == CONVERT_IN:
                    tx.trade_date = row.to_nav_date
                    tx.nav_date = row.to_nav_date
                    tx.confirm_date = row.to_confirm_date
                    tx.nav = row.to_nav
                    tx.amount = row.to_amount
                    tx.fee = row.to_fee + row.supplement_fee
                    tx.shares = row.to_shares
            _rebuild_position_for_fund(session, row.user_id, row.from_fund_code)
            _rebuild_position_for_fund(session, row.user_id, row.to_fund_code)
            _invalidate_user_view_caches_for_user_id(session, row.user_id)
            touched.add(row.id)
        confirmed = len(touched)
    return {'success': True, 'confirmed': confirmed}


def list_conversions(user_id, fund_code=None):
    code = normalize_fund_code(fund_code) if fund_code else None
    confirm_pending_conversions(user_id=user_id, fund_code=code)
    with session_scope() as session:
        query = select(FundConversion).where(FundConversion.user_id == user_id)
        if code:
            query = query.where((FundConversion.from_fund_code == code) | (FundConversion.to_fund_code == code))
        rows = session.execute(query.order_by(FundConversion.submitted_date.desc(), FundConversion.id.desc())).scalars().all()
        return {'success': True, 'conversions': [_serialize_conversion(row) for row in rows]}
