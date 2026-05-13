from datetime import date, datetime, timedelta
from functools import lru_cache

try:
    import akshare as ak
except Exception:  # pragma: no cover - only used when the dependency is missing/broken.
    ak = None


BEFORE_1500 = 'BEFORE_1500'
AFTER_1500 = 'AFTER_1500'


def parse_date(date_text, field_name='date'):
    if isinstance(date_text, date):
        return date_text

    raw = str(date_text or '').strip()
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        raise ValueError(f'{field_name} must be YYYY-MM-DD')


def format_date(date_value):
    return date_value.strftime('%Y-%m-%d')


def normalize_time_slot(value):
    raw = str(value or '').strip().upper()
    aliases = {
        'BEFORE_1500': BEFORE_1500,
        'BEFORE_15': BEFORE_1500,
        'BEFORE': BEFORE_1500,
        'AM': BEFORE_1500,
        'AFTER_1500': AFTER_1500,
        'AFTER_15': AFTER_1500,
        'AFTER': AFTER_1500,
        'PM': AFTER_1500,
    }
    normalized = aliases.get(raw)
    if not normalized:
        raise ValueError('Please choose before or after 15:00')
    return normalized


@lru_cache(maxsize=1)
def get_trade_date_calendar():
    if ak is None:
        raise RuntimeError('AKShare is not available')

    trade_date_df = ak.tool_trade_date_hist_sina()
    trade_date_values = [
        parse_date(str(value)[:10])
        for value in trade_date_df['trade_date'].dropna().tolist()
    ]
    trade_dates = frozenset(format_date(value) for value in trade_date_values)
    return trade_dates, min(trade_date_values), max(trade_date_values)


def _is_weekday(date_value):
    return date_value.weekday() < 5


def is_trading_day(date_value):
    target_date = parse_date(date_value)

    try:
        trade_dates, start_date, end_date = get_trade_date_calendar()
    except Exception:
        return _is_weekday(target_date)

    if start_date <= target_date <= end_date:
        return format_date(target_date) in trade_dates

    return _is_weekday(target_date)


def next_trading_day(date_value):
    current = parse_date(date_value) + timedelta(days=1)
    while not is_trading_day(current):
        current += timedelta(days=1)
    return current


def resolve_trade_date(submitted_date, time_slot):
    date_value = parse_date(submitted_date, 'submitted_date')
    slot = normalize_time_slot(time_slot)
    if not is_trading_day(date_value):
        return format_date(next_trading_day(date_value)), slot
    if slot == AFTER_1500:
        return format_date(next_trading_day(date_value)), slot
    return format_date(date_value), slot
