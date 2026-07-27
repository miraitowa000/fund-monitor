from __future__ import annotations

import re
import threading
import time
from urllib.parse import urlencode

from core.http import http_get
from core.time_utils import china_now


EASTMONEY_VALUATION_URL = 'https://api.fund.eastmoney.com/FundGuZhi/GetFundGZList'
SINA_VALUATION_URL = 'https://hq.sinajs.cn/list=fu_{code}'
VALUATION_CACHE_TTL_SECONDS = 45
VALUATION_STALE_TTL_SECONDS = 5 * 60
VALUATION_RETRY_SECONDS = 10

_VALUATION_CACHE = {}
_VALUATION_CACHE_REFRESHED_AT = 0.0
_VALUATION_LAST_ATTEMPT_AT = 0.0
_VALUATION_CACHE_LOCK = threading.Lock()

_SINA_VALUATION_CACHE = {}
_SINA_VALUATION_REFRESHED_AT = {}
_SINA_VALUATION_LAST_ATTEMPT_AT = {}
_SINA_VALUATION_CACHE_LOCK = threading.Lock()


def _clean_number_text(value, allow_percent=False):
    text = str(value or '').strip()
    if allow_percent:
        text = text.removesuffix('%').strip()
    if not text or text in ('-', '--', '---'):
        return ''
    try:
        float(text)
    except (TypeError, ValueError):
        return ''
    return text


def _clean_date(value):
    text = str(value or '').strip()
    match = re.search(r'\d{4}-\d{2}-\d{2}', text)
    return match.group(0) if match else ''


def _response_text(response):
    content = getattr(response, 'content', None)
    if content:
        try:
            return content.decode('gb18030')
        except (UnicodeDecodeError, AttributeError):
            return content.decode('utf-8', errors='replace')
    return str(getattr(response, 'text', '') or '')


def _parse_sina_valuation(text, fund_code):
    code = str(fund_code or '').strip().zfill(6)
    match = re.search(
        rf'var\s+hq_str_fu_{re.escape(code)}\s*=\s*"([^"]*)"\s*;?',
        str(text or ''),
    )
    if not match:
        return None

    fields = [item.strip() for item in match.group(1).split(',')]
    if len(fields) < 8:
        return None

    name = fields[0]
    quote_time = fields[1]
    estimate_nav = _clean_number_text(fields[2])
    base_nav = _clean_number_text(fields[3])
    estimate_change = _clean_number_text(fields[6], allow_percent=True)
    estimate_date = _clean_date(fields[7])
    if (
        not name
        or not re.fullmatch(r'\d{2}:\d{2}:\d{2}', quote_time)
        or not estimate_nav
        or not base_nav
        or not estimate_change
        or not estimate_date
    ):
        return None

    try:
        estimate_nav_number = float(estimate_nav)
        base_nav_number = float(base_nav)
        estimate_change_number = float(estimate_change)
    except (TypeError, ValueError):
        return None
    if estimate_nav_number <= 0 or base_nav_number <= 0:
        return None

    calculated_change = (estimate_nav_number / base_nav_number - 1) * 100
    if abs(calculated_change - estimate_change_number) > 0.05:
        return None

    return {
        'code': code,
        'name': name,
        'gsz': estimate_nav,
        'gszzl': estimate_change,
        'gztime': f'{estimate_date} {quote_time}',
        'dwjz': base_nav,
        'jzrq': '-',
        'display_date': estimate_date,
        'confirmed_date': '-',
        'base_date': '-',
        'quote_source': 'sina_fund_valuation',
    }


def _fetch_sina_valuation(fund_code):
    code = str(fund_code or '').strip().zfill(6)
    response = http_get(
        SINA_VALUATION_URL.format(code=code),
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.sina.com.cn/fund/',
        },
        timeout=5,
    )
    if response.status_code != 200:
        raise RuntimeError(f'sina valuation endpoint returned HTTP {response.status_code}')
    return _parse_sina_valuation(_response_text(response), code)


def _get_sina_valuation(fund_code, force_refresh=False):
    code = str(fund_code or '').strip().zfill(6)
    now = time.monotonic()
    with _SINA_VALUATION_CACHE_LOCK:
        cached = _SINA_VALUATION_CACHE.get(code)
        refreshed_at = _SINA_VALUATION_REFRESHED_AT.get(code, 0.0)
        last_attempt_at = _SINA_VALUATION_LAST_ATTEMPT_AT.get(code, 0.0)
        age = now - refreshed_at if refreshed_at else None
        if not force_refresh and cached and age is not None and age < VALUATION_CACHE_TTL_SECONDS:
            return cached
        if not force_refresh and last_attempt_at and now - last_attempt_at < VALUATION_RETRY_SECONDS:
            return cached if cached and age is not None and age < VALUATION_STALE_TTL_SECONDS else None
        _SINA_VALUATION_LAST_ATTEMPT_AT[code] = now

    try:
        refreshed = _fetch_sina_valuation(code)
    except Exception:
        return cached if cached and age is not None and age < VALUATION_STALE_TTL_SECONDS else None
    if not refreshed:
        return cached if cached and age is not None and age < VALUATION_STALE_TTL_SECONDS else None

    with _SINA_VALUATION_CACHE_LOCK:
        _SINA_VALUATION_CACHE[code] = refreshed
        _SINA_VALUATION_REFRESHED_AT[code] = time.monotonic()
    return refreshed


def _parse_valuation_payload(payload, observed_at=None):
    data = payload.get('Data') if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError('valuation response is missing Data')

    rows = data.get('list')
    if not isinstance(rows, list):
        raise ValueError('valuation response is missing Data.list')

    observed = observed_at or china_now()
    default_estimate_date = _clean_date(data.get('gxrq'))
    default_base_date = _clean_date(data.get('gzrq'))
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get('bzdm') or '').strip().zfill(6)
        if len(code) != 6 or not code.isdigit():
            continue

        estimate_nav = _clean_number_text(row.get('gsz'))
        estimate_change = _clean_number_text(row.get('gszzl'), allow_percent=True)
        base_nav = _clean_number_text(row.get('gbdwjz')) or _clean_number_text(row.get('dwjz'))
        estimate_date = _clean_date(row.get('gxrq')) or default_estimate_date
        base_date = _clean_date(row.get('gzrq')) or default_base_date
        if not estimate_nav or not estimate_change or not base_nav or not estimate_date or not base_date:
            continue

        observed_time = observed.strftime('%H:%M:%S')
        result[code] = {
            'code': code,
            'name': str(row.get('jjjc') or '').strip(),
            'gsz': estimate_nav,
            'gszzl': estimate_change,
            'gztime': f'{estimate_date} {observed_time}',
            'dwjz': base_nav,
            'jzrq': base_date,
            'display_date': estimate_date,
            'confirmed_date': base_date,
            'base_date': base_date,
            'quote_source': 'eastmoney_guzhi',
        }
    return result


def _fetch_valuation_map():
    query = urlencode({
        'type': '1',
        'sort': '3',
        'orderType': 'desc',
        'canbuy': '0',
        'pageIndex': '1',
        'pageSize': '30000',
        '_': int(time.time() * 1000),
    })
    response = http_get(
        f'{EASTMONEY_VALUATION_URL}?{query}',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://fund.eastmoney.com/',
        },
        timeout=15,
    )
    if response.status_code != 200:
        raise RuntimeError(f'valuation endpoint returned HTTP {response.status_code}')
    return _parse_valuation_payload(response.json())


def _get_valuation_map(force_refresh=False):
    global _VALUATION_CACHE
    global _VALUATION_CACHE_REFRESHED_AT
    global _VALUATION_LAST_ATTEMPT_AT

    now = time.monotonic()
    age = now - _VALUATION_CACHE_REFRESHED_AT if _VALUATION_CACHE_REFRESHED_AT else None
    if not force_refresh and age is not None and age < VALUATION_CACHE_TTL_SECONDS:
        return _VALUATION_CACHE

    with _VALUATION_CACHE_LOCK:
        now = time.monotonic()
        age = now - _VALUATION_CACHE_REFRESHED_AT if _VALUATION_CACHE_REFRESHED_AT else None
        if not force_refresh and age is not None and age < VALUATION_CACHE_TTL_SECONDS:
            return _VALUATION_CACHE
        if (
            not force_refresh
            and _VALUATION_LAST_ATTEMPT_AT
            and now - _VALUATION_LAST_ATTEMPT_AT < VALUATION_RETRY_SECONDS
        ):
            return _VALUATION_CACHE if age is not None and age < VALUATION_STALE_TTL_SECONDS else {}

        _VALUATION_LAST_ATTEMPT_AT = now
        try:
            refreshed = _fetch_valuation_map()
        except Exception:
            return _VALUATION_CACHE if age is not None and age < VALUATION_STALE_TTL_SECONDS else {}

        _VALUATION_CACHE = refreshed
        _VALUATION_CACHE_REFRESHED_AT = time.monotonic()
        return _VALUATION_CACHE


def get_fund_valuation(fund_code, force_refresh=False):
    code = str(fund_code or '').strip().zfill(6)
    if len(code) != 6 or not code.isdigit():
        return None
    today = china_now().strftime('%Y-%m-%d')
    sina_valuation = _get_sina_valuation(code, force_refresh=force_refresh)
    if sina_valuation and sina_valuation.get('display_date') == today:
        return sina_valuation

    eastmoney_valuation = _get_valuation_map(force_refresh=force_refresh).get(code)
    if eastmoney_valuation and eastmoney_valuation.get('display_date') == today:
        return eastmoney_valuation
    return sina_valuation or eastmoney_valuation
