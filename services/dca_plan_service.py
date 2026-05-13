import calendar
import threading
import time
from datetime import date, datetime, timedelta

from sqlalchemy import select

from core.db import session_scope
from core.models import FundDcaPlan, FundTransaction, User
from services.fund_transaction_service import SIP_BUY, create_fund_transaction
from services.trading_calendar_service import format_date, is_trading_day, next_trading_day, parse_date
from services.user_fund_service import _invalidate_user_view_caches, normalize_fund_code


CYCLE_DAILY = 'daily'
CYCLE_WEEKLY = 'weekly'
CYCLE_BIWEEKLY = 'biweekly'
CYCLE_MONTHLY = 'monthly'
VALID_CYCLES = {CYCLE_DAILY, CYCLE_WEEKLY, CYCLE_BIWEEKLY, CYCLE_MONTHLY}

_DCA_THREAD_STARTED = False
_DCA_THREAD_LOCK = threading.Lock()
_DCA_RUN_LOCK = threading.Lock()


def _today_text():
    return datetime.now().strftime('%Y-%m-%d')


def _get_client_id_by_user_id(user_id):
    with session_scope() as session:
        return session.execute(select(User.client_id).where(User.id == user_id)).scalar_one_or_none()


def _invalidate_user_dca_views(user_id):
    client_id = _get_client_id_by_user_id(user_id)
    if client_id:
        _invalidate_user_view_caches(client_id)


def _round_money(value):
    return round(float(value), 2)


def _to_float(value, default=None):
    if value in (None, ''):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_date(value, field_name):
    raw = str(value or '').strip()[:10]
    try:
        datetime.strptime(raw, '%Y-%m-%d')
    except ValueError:
        raise ValueError(f'{field_name}必须是 YYYY-MM-DD')
    return raw


def _normalize_cycle(value):
    cycle = str(value or '').strip().lower()
    if cycle not in VALID_CYCLES:
        raise ValueError('定投周期不正确')
    return cycle


def _serialize_plan(plan):
    if not plan:
        return None
    next_run_date = compute_next_dca_date(plan, _today_text())
    return {
        'id': plan.id,
        'fund_code': plan.fund_code,
        'amount': _round_money(plan.amount),
        'fee_rate': float(plan.fee_rate or 0),
        'cycle': plan.cycle,
        'first_date': plan.first_date,
        'last_date': plan.last_date,
        'weekly_day': plan.weekly_day,
        'monthly_day': plan.monthly_day,
        'enabled': bool(plan.enabled),
        'next_run_date': next_run_date,
        'created_at': plan.created_at.strftime('%Y-%m-%d %H:%M:%S') if plan.created_at else None,
        'updated_at': plan.updated_at.strftime('%Y-%m-%d %H:%M:%S') if plan.updated_at else None,
    }


def _normalize_payload(payload):
    data = payload or {}
    amount = _to_float(data.get('amount'))
    if amount is None or amount <= 0:
        raise ValueError('定投金额必须大于 0')

    fee_rate = _to_float(data.get('fee_rate'), 0.0) or 0.0
    if fee_rate < 0:
        raise ValueError('费率不能为负数')

    cycle = _normalize_cycle(data.get('cycle') or CYCLE_MONTHLY)
    first_date = _normalize_date(data.get('first_date') or _today_text(), '首次定投日期')
    enabled = bool(data.get('enabled', True))

    weekly_day = data.get('weekly_day')
    monthly_day = data.get('monthly_day')
    if cycle in (CYCLE_WEEKLY, CYCLE_BIWEEKLY):
        try:
            weekly_day = int(weekly_day)
        except (TypeError, ValueError):
            weekly_day = parse_date(first_date).weekday()
        if weekly_day < 0 or weekly_day > 4:
            raise ValueError('每周定投只能选择周一到周五')
        monthly_day = None
    elif cycle == CYCLE_MONTHLY:
        try:
            monthly_day = int(monthly_day)
        except (TypeError, ValueError):
            monthly_day = parse_date(first_date).day
        if monthly_day < 1 or monthly_day > 28:
            raise ValueError('每月定投日期只能选择 1-28 号')
        weekly_day = None
    else:
        weekly_day = None
        monthly_day = None

    return {
        'amount': amount,
        'fee_rate': fee_rate,
        'cycle': cycle,
        'first_date': first_date,
        'weekly_day': weekly_day,
        'monthly_day': monthly_day,
        'enabled': enabled,
    }


def _add_months(date_value, months):
    month_index = date_value.month - 1 + months
    year = date_value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(date_value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _scheduled_month_date(year, month, day):
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _next_candidate_after(plan, previous_date):
    if plan.cycle == CYCLE_DAILY:
        return previous_date + timedelta(days=1)
    if plan.cycle == CYCLE_WEEKLY:
        return previous_date + timedelta(days=7)
    if plan.cycle == CYCLE_BIWEEKLY:
        return previous_date + timedelta(days=14)
    return _add_months(previous_date, 1)


def _align_first_candidate(plan):
    first = parse_date(plan.first_date)
    if plan.cycle in (CYCLE_WEEKLY, CYCLE_BIWEEKLY):
        target_weekday = int(plan.weekly_day if plan.weekly_day is not None else first.weekday())
        offset = (target_weekday - first.weekday()) % 7
        return first + timedelta(days=offset)
    if plan.cycle == CYCLE_MONTHLY:
        day = int(plan.monthly_day if plan.monthly_day is not None else first.day)
        candidate = _scheduled_month_date(first.year, first.month, day)
        if candidate < first:
            next_month = _add_months(date(first.year, first.month, 1), 1)
            candidate = _scheduled_month_date(next_month.year, next_month.month, day)
        return candidate
    return first


def _actual_run_date(scheduled_date):
    if is_trading_day(scheduled_date):
        return scheduled_date
    return next_trading_day(scheduled_date)


def _last_date_text(plan):
    return plan.last_date or ''


def compute_due_dca_dates(plan, today=None, current_time=None, limit=24):
    today_date = parse_date(today or _today_text())
    now_time = current_time or datetime.now().time()
    cursor = _align_first_candidate(plan)
    last_date = parse_date(plan.last_date) if plan.last_date else None
    due_dates = []
    seen_actual_dates = set()

    while len(due_dates) < limit:
        if last_date and cursor <= last_date:
            cursor = _next_candidate_after(plan, cursor)
            continue
        actual = _actual_run_date(cursor)
        if actual > today_date:
            break
        if actual == today_date and (now_time.hour, now_time.minute, now_time.second) < (12, 0, 0):
            break
        actual_text = format_date(actual)
        if actual_text not in seen_actual_dates:
            due_dates.append(actual)
            seen_actual_dates.add(actual_text)
        cursor = _next_candidate_after(plan, cursor)

    return [format_date(item) for item in due_dates]


def compute_next_dca_date(plan, today=None):
    today_date = parse_date(today or _today_text())
    cursor = _align_first_candidate(plan)
    last_date = parse_date(plan.last_date) if plan.last_date else None

    for _ in range(480):
        if last_date and cursor <= last_date:
            cursor = _next_candidate_after(plan, cursor)
            continue
        actual = _actual_run_date(cursor)
        if actual >= today_date:
            return format_date(actual)
        cursor = _next_candidate_after(plan, cursor)
    return None


def get_dca_plan(user_id, fund_code, run_due=True):
    code = normalize_fund_code(fund_code)
    if run_due:
        run_due_dca_plans(user_id=user_id, fund_code=code)
    with session_scope() as session:
        plan = session.execute(
            select(FundDcaPlan).where(FundDcaPlan.user_id == user_id, FundDcaPlan.fund_code == code)
        ).scalar_one_or_none()
        return {'success': True, 'plan': _serialize_plan(plan)}


def save_dca_plan(user_id, fund_code, payload):
    code = normalize_fund_code(fund_code)
    if not code.isdigit() or len(code) != 6:
        raise ValueError('基金代码格式不正确')
    data = _normalize_payload(payload)

    with session_scope() as session:
        plan = session.execute(
            select(FundDcaPlan).where(FundDcaPlan.user_id == user_id, FundDcaPlan.fund_code == code)
        ).scalar_one_or_none()
        if not plan:
            plan = FundDcaPlan(user_id=user_id, fund_code=code, **data)
            session.add(plan)
        else:
            for key, value in data.items():
                setattr(plan, key, value)
            plan.updated_at = datetime.utcnow()
        session.flush()
        result = {'success': True, 'plan': _serialize_plan(plan)}

    run_due_dca_plans(user_id=user_id, fund_code=code)
    _invalidate_user_dca_views(user_id)
    return result


def delete_dca_plan(user_id, fund_code):
    code = normalize_fund_code(fund_code)
    with session_scope() as session:
        plan = session.execute(
            select(FundDcaPlan).where(FundDcaPlan.user_id == user_id, FundDcaPlan.fund_code == code)
        ).scalar_one_or_none()
        if not plan:
            return {'success': True, 'deleted': False}
        session.delete(plan)
    _invalidate_user_dca_views(user_id)
    return {'success': True, 'deleted': True}


def _batch_exists(user_id, batch_id):
    with session_scope() as session:
        existing = session.execute(
            select(FundTransaction.id)
            .where(FundTransaction.user_id == user_id, FundTransaction.batch_id == batch_id)
            .limit(1)
        ).scalar_one_or_none()
        return existing is not None


def _mark_plan_last_date(plan_id, scheduled_date):
    with session_scope() as session:
        plan = session.execute(select(FundDcaPlan).where(FundDcaPlan.id == plan_id)).scalar_one_or_none()
        if plan and (not plan.last_date or scheduled_date > plan.last_date):
            plan.last_date = scheduled_date
            plan.updated_at = datetime.utcnow()


def run_due_dca_plans(user_id=None, fund_code=None, today=None, current_time=None):
    if not _DCA_RUN_LOCK.acquire(blocking=False):
        return {
            'success': True,
            'checked': 0,
            'generated': 0,
            'skipped': 0,
            'running': True,
        }
    try:
        return _run_due_dca_plans_locked(user_id=user_id, fund_code=fund_code, today=today, current_time=current_time)
    finally:
        _DCA_RUN_LOCK.release()


def _run_due_dca_plans_locked(user_id=None, fund_code=None, today=None, current_time=None):
    code = normalize_fund_code(fund_code) if fund_code else None
    today_text = today or _today_text()
    generated = 0
    skipped = 0
    checked = 0

    with session_scope() as session:
        query = select(FundDcaPlan).where(FundDcaPlan.enabled.is_(True))
        if user_id is not None:
            query = query.where(FundDcaPlan.user_id == user_id)
        if code:
            query = query.where(FundDcaPlan.fund_code == code)
        plans = session.execute(query).scalars().all()
        plan_rows = [
            {
                'id': plan.id,
                'user_id': plan.user_id,
                'fund_code': plan.fund_code,
                'amount': plan.amount,
                'fee_rate': plan.fee_rate,
                'cycle': plan.cycle,
                'first_date': plan.first_date,
                'last_date': plan.last_date,
                'weekly_day': plan.weekly_day,
                'monthly_day': plan.monthly_day,
                'enabled': plan.enabled,
            }
            for plan in plans
        ]

    for row in plan_rows:
        plan = type('DcaPlanView', (), row)()
        due_dates = compute_due_dca_dates(plan, today=today_text, current_time=current_time)
        checked += len(due_dates)
        for scheduled_date in due_dates:
            batch_id = f'dca:{plan.id}:{scheduled_date}'
            if _batch_exists(plan.user_id, batch_id):
                skipped += 1
                _mark_plan_last_date(plan.id, scheduled_date)
                continue
            actual_date = scheduled_date
            create_fund_transaction(plan.user_id, plan.fund_code, {
                'type': SIP_BUY,
                'amount': plan.amount,
                'fee_rate': plan.fee_rate,
                'submitted_date': actual_date,
                'time_slot': 'BEFORE_1500',
                'batch_id': batch_id,
                'is_dca': True,
            })
            _mark_plan_last_date(plan.id, scheduled_date)
            generated += 1

    return {
        'success': True,
        'checked': checked,
        'generated': generated,
        'skipped': skipped,
    }


def _seconds_until_next_noon():
    now = datetime.now()
    next_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
    if now >= next_noon:
        next_noon += timedelta(days=1)
    return max((next_noon - now).total_seconds(), 1)


def _dca_scheduler_loop():
    while True:
        time.sleep(_seconds_until_next_noon())
        try:
            run_due_dca_plans()
        except Exception:
            pass


def start_dca_plan_scheduler():
    global _DCA_THREAD_STARTED
    with _DCA_THREAD_LOCK:
        if _DCA_THREAD_STARTED:
            return False
        thread = threading.Thread(target=_dca_scheduler_loop, name='dca-plan-generator', daemon=True)
        thread.start()
        _DCA_THREAD_STARTED = True
        return True
