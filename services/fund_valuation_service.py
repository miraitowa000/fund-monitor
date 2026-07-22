from __future__ import annotations

import re
import threading
import time
from urllib.parse import urlencode

from core.http import http_get
from core.time_utils import china_now


EASTMONEY_VALUATION_URL = 'https://api.fund.eastmoney.com/FundGuZhi/GetFundGZList'
VALUATION_CACHE_TTL_SECONDS = 45
VALUATION_STALE_TTL_SECONDS = 5 * 60
VALUATION_RETRY_SECONDS = 10

_VALUATION_CACHE = {}
_VALUATION_CACHE_REFRESHED_AT = 0.0
_VALUATION_LAST_ATTEMPT_AT = 0.0
_VALUATION_CACHE_LOCK = threading.Lock()


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
    return _get_valuation_map(force_refresh=force_refresh).get(code)
