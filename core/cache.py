import threading
import time
from copy import deepcopy


_API_CACHE = {
    'basic': {},
    'holdings': {},
    'history': {},
    'detail': {},
    'pingzhong': {},
    'related_etf': {},
}
_API_CACHE_LOCK = threading.Lock()


def cache_get(bucket, key, ttl_seconds):
    now = time.time()
    with _API_CACHE_LOCK:
        item = _API_CACHE.get(bucket, {}).get(key)
        if not item:
            return None
        if now - item['ts'] > ttl_seconds:
            return None
        value = item['value']
    if bucket in ('pingzhong', 'basic'):
        return value
    return deepcopy(value)


def cache_get_stale(bucket, key):
    with _API_CACHE_LOCK:
        item = _API_CACHE.get(bucket, {}).get(key)
        if not item:
            return None
        value = item['value']
    if bucket in ('pingzhong', 'basic'):
        return value
    return deepcopy(value)


def cache_set(bucket, key, value):
    stored_value = value if bucket in ('pingzhong', 'basic') else deepcopy(value)
    with _API_CACHE_LOCK:
        _API_CACHE.setdefault(bucket, {})[key] = {
            'ts': time.time(),
            'value': stored_value,
        }


def cache_get_age(bucket, key):
    with _API_CACHE_LOCK:
        item = _API_CACHE.get(bucket, {}).get(key)
        if not item:
            return None
        return time.time() - item['ts']


def cache_prune(bucket, max_age_seconds):
    removed = 0
    cutoff = time.time() - max_age_seconds
    with _API_CACHE_LOCK:
        items = _API_CACHE.get(bucket, {})
        stale_keys = [key for key, value in items.items() if value.get('ts', 0) < cutoff]
        for key in stale_keys:
            items.pop(key, None)
            removed += 1
    return removed
