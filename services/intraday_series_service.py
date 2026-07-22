from __future__ import annotations

import json
from datetime import datetime, time as dt_time
import re

from sqlalchemy import distinct, select

from core.db import session_scope
from core.models import UserFund
from core.redis_client import get_redis_client
from core.time_utils import china_now, china_today
from services.trading_calendar_service import is_trading_day


INTRADAY_STEP_MINUTES = 3
INTRADAY_TTL_SECONDS = 3 * 24 * 60 * 60
INTRADAY_SERIES_KEY_PREFIX = 'intraday:fund'


def get_intraday_today_text():
    return china_today().strftime('%Y-%m-%d')


def _build_key(code, day_text=None):
    return f'{INTRADAY_SERIES_KEY_PREFIX}:{day_text or get_intraday_today_text()}:{str(code).zfill(6)}'


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_minute(value):
    raw = str(value or '').strip()
    try:
        if len(raw) >= 16:
            return datetime.strptime(raw[:16], '%Y-%m-%d %H:%M').strftime('%H:%M')
    except ValueError:
        pass

    parts = raw.split()
    candidate = parts[-1] if parts else raw
    if len(candidate) >= 5 and candidate[2] == ':':
        return candidate[:5]
    return ''


def _to_date_text(value):
    match = re.search(r'\d{4}-\d{2}-\d{2}', str(value or ''))
    return match.group(0) if match else ''


def _normalize_step_minute(minute):
    raw = _to_minute(minute)
    if not raw:
        return ''
    try:
        hour, minute_value = [int(part) for part in raw.split(':')[:2]]
    except (TypeError, ValueError):
        return ''

    total = hour * 60 + minute_value
    bucket = (total // INTRADAY_STEP_MINUTES) * INTRADAY_STEP_MINUTES
    normalized_hour = bucket // 60
    normalized_minute = bucket % 60
    return f'{normalized_hour:02d}:{normalized_minute:02d}'


def _is_trade_minute(minute):
    raw = _to_minute(minute)
    if not raw:
        return False
    try:
        hour, minute_value = [int(part) for part in raw.split(':')[:2]]
    except (TypeError, ValueError):
        return False
    value = dt_time(hour, minute_value)
    return (
        dt_time(9, 30) <= value <= dt_time(11, 30)
        or dt_time(13, 0) <= value <= dt_time(15, 0)
    )


def is_intraday_collection_open(now=None):
    current = now or china_now()
    if not is_trading_day(current.date()):
        return False
    return _is_trade_minute(current.strftime('%H:%M'))


def get_active_position_fund_codes(limit=500):
    try:
        with session_scope() as session:
            rows = session.execute(
                select(distinct(UserFund.fund_code)).where(
                    UserFund.holding_amount.is_not(None),
                    UserFund.holding_profit.is_not(None),
                    UserFund.cost_amount.is_not(None),
                    UserFund.holding_shares.is_not(None),
                    UserFund.avg_cost_nav.is_not(None),
                    UserFund.snapshot_nav.is_not(None),
                )
            ).all()
    except Exception:
        return []

    codes = []
    seen = set()
    for row in rows:
        code = str(row[0] or '').zfill(6)
        if len(code) != 6 or not code.isdigit() or code in seen:
            continue
        seen.add(code)
        codes.append(code)
        if len(codes) >= limit:
            break
    return codes


def record_intraday_snapshot(code, quote, day_text=None):
    if not quote:
        return False
    if quote.get('nav_confirmed'):
        return False

    nav = _to_float(quote.get('gsz'))
    time_source = quote.get('gztime') or quote.get('display_date')
    target_day = day_text or get_intraday_today_text()
    quote_day = _to_date_text(time_source)
    if quote_day and quote_day != target_day:
        return False
    if not quote_day and not is_intraday_collection_open():
        return False

    minute = _normalize_step_minute(time_source)
    if nav is None or nav <= 0 or not minute or not _is_trade_minute(minute):
        return False

    try:
        client = get_redis_client()
        key = _build_key(code, target_day)
        client.hset(key, minute, json.dumps({
            'nav': round(nav, 4),
            'ts': int(datetime.now().timestamp()),
        }, ensure_ascii=False))
        client.expire(key, INTRADAY_TTL_SECONDS)
        return True
    except Exception:
        return False


def record_intraday_snapshots(quotes, day_text=None):
    count = 0
    for quote in quotes or []:
        code = (quote or {}).get('code')
        if code and record_intraday_snapshot(code, quote, day_text=day_text):
            count += 1
    return count


def get_intraday_series(codes, day_text=None):
    result = {}
    normalized_codes = []
    seen = set()
    for code in codes or []:
        normalized = str(code or '').zfill(6)
        if len(normalized) != 6 or not normalized.isdigit() or normalized in seen:
            continue
        seen.add(normalized)
        normalized_codes.append(normalized)

    if not normalized_codes:
        return result

    target_day = day_text or get_intraday_today_text()
    try:
        client = get_redis_client()
        for code in normalized_codes:
            raw_map = client.hgetall(_build_key(code, target_day)) or {}
            points = {}
            for minute, raw in raw_map.items():
                nav = None
                try:
                    payload = json.loads(raw)
                    nav = _to_float(payload.get('nav') if isinstance(payload, dict) else payload)
                except Exception:
                    nav = _to_float(raw)
                normalized_minute = _normalize_step_minute(minute)
                if normalized_minute and nav is not None and nav > 0:
                    points[normalized_minute] = round(nav, 4)
            if points:
                result[code] = dict(sorted(points.items()))
    except Exception:
        return result

    return result
