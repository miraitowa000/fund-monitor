import time

from core.http import http_get
from core.perf_metrics import increment_metric
from services.quote_cache_service import (
    acquire_market_indexes_refresh_lock,
    get_market_indexes,
    get_stale_market_indexes,
    release_market_indexes_refresh_lock,
    set_market_indexes,
)


INDEX_CONFIG = [
    {'code': 's_sh000001', 'secid': '1.000001', 'name': '上证指数'},
    {'code': 's_sz399001', 'secid': '0.399001', 'name': '深证成指'},
    {'code': 's_sz399006', 'secid': '0.399006', 'name': '创业板指'},
    {'code': 's_sh000688', 'secid': '1.000688', 'name': '科创50'},
    {'code': 's_bj899050', 'secid': '0.899050', 'name': '北证50'},
]
TTL_INDEX_SECONDS = 15
INDEX_REFRESH_LOCK_SECONDS = 5
INDEX_WAIT_FOR_CACHE_SECONDS = 0.6
INDEX_WAIT_STEP_SECONDS = 0.1


def _fmt_number(value):
    try:
        return f"{float(value):.2f}"
    except Exception:
        return '-'


def get_indexes(force_refresh=False):
    url = (
        'https://push2.eastmoney.com/api/qt/ulist.np/get'
        '?fltt=2&invt=2'
        '&secids=1.000001,0.399001,0.399006,1.000688,0.899050'
        '&fields=f12,f14,f2,f3,f4'
    )
    fallback = [
        {'code': item['code'], 'name': item['name'], 'price': '-', 'change': '-', 'pct': '0.00'}
        for item in INDEX_CONFIG
    ]
    has_lock = False
    if not force_refresh:
        cached = get_market_indexes(TTL_INDEX_SECONDS)
        if cached:
            increment_metric('cache.index.hit')
            return cached
        increment_metric('cache.index.miss')
        has_lock = acquire_market_indexes_refresh_lock(INDEX_REFRESH_LOCK_SECONDS)
        if not has_lock:
            increment_metric('cache.index.waiter')
            deadline = time.time() + INDEX_WAIT_FOR_CACHE_SECONDS
            while time.time() < deadline:
                time.sleep(INDEX_WAIT_STEP_SECONDS)
                cached = get_market_indexes(TTL_INDEX_SECONDS)
                if cached:
                    increment_metric('cache.index.waiter_hit')
                    return cached
            increment_metric('cache.index.stale_fallback')
            return get_stale_market_indexes() or fallback
        increment_metric('cache.index.refresh_owner')
    else:
        increment_metric('cache.index.force_refresh')
        has_lock = acquire_market_indexes_refresh_lock(INDEX_REFRESH_LOCK_SECONDS)
        if has_lock:
            increment_metric('cache.index.refresh_owner')
        else:
            increment_metric('cache.index.force_refresh_waiter')
            return get_market_indexes(TTL_INDEX_SECONDS) or get_stale_market_indexes() or fallback
    try:
        response = http_get(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://quote.eastmoney.com/',
            },
            timeout=3,
        )
        if response.status_code != 200:
            increment_metric('cache.index.stale_fallback')
            return get_stale_market_indexes() or fallback

        payload = response.json()
        diff = (payload.get('data') or {}).get('diff') or []
        data_map = {
            str(item.get('f12', '')).zfill(6): item
            for item in diff
            if isinstance(item, dict)
        }

        results = []
        for item in INDEX_CONFIG:
            raw = data_map.get(item['secid'].split('.', 1)[1], {})
            results.append({
                'code': item['code'],
                'name': raw.get('f14') or item['name'],
                'price': _fmt_number(raw.get('f2')),
                'change': _fmt_number(raw.get('f4')),
                'pct': _fmt_number(raw.get('f3') or 0),
            })
        set_market_indexes(results)
        return results
    except Exception:
        increment_metric('cache.index.stale_fallback')
        return get_stale_market_indexes() or fallback
    finally:
        if has_lock:
            release_market_indexes_refresh_lock()
