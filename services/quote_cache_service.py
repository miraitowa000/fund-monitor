from __future__ import annotations

import json
import time
import uuid

from core.redis_client import get_redis_client


REDIS_QUOTE_TTL_SECONDS = 7 * 24 * 60 * 60
REDIS_INDEX_TTL_SECONDS = 24 * 60 * 60
INDEX_CACHE_KEY = 'quote:indexes'
INDEX_REFRESH_LOCK_KEY = 'lock:quote:indexes:refresh'
BASIC_REFRESH_LOCK_PREFIX = 'lock:quote:fund:refresh:'


def _build_basic_quote_key(code):
    return f'quote:fund:{str(code).zfill(6)}'


def _build_basic_refresh_lock_key(code):
    return f'{BASIC_REFRESH_LOCK_PREFIX}{str(code).zfill(6)}'


def set_basic_quote(code, payload):
    if not payload:
        return
    try:
        client = get_redis_client()
        client.set(
            _build_basic_quote_key(code),
            json.dumps({
                'ts': time.time(),
                'value': payload,
            }, ensure_ascii=False),
            ex=REDIS_QUOTE_TTL_SECONDS,
        )
    except Exception:
        pass


def _read_basic_quote_record(code):
    try:
        client = get_redis_client()
        raw = client.get(_build_basic_quote_key(code))
        if not raw:
            return None
        record = json.loads(raw)
        if not isinstance(record, dict):
            return None
        return record
    except Exception:
        return None


def get_basic_quote(code, ttl_seconds):
    record = _read_basic_quote_record(code)
    if not record:
        return None

    ts = record.get('ts')
    value = record.get('value')
    try:
        if time.time() - float(ts) > ttl_seconds:
            return None
    except (TypeError, ValueError):
        return None
    return value


def get_stale_basic_quote(code):
    record = _read_basic_quote_record(code)
    if not record:
        return None
    return record.get('value')


def acquire_basic_quote_refresh_lock(code, lock_seconds=8):
    token = uuid.uuid4().hex
    try:
        client = get_redis_client()
        locked = client.set(
            _build_basic_refresh_lock_key(code),
            token,
            nx=True,
            ex=max(1, int(lock_seconds)),
        )
        if locked:
            return token
    except Exception:
        return None
    return None


def release_basic_quote_refresh_lock(code, token):
    if not token:
        return
    try:
        client = get_redis_client()
        key = _build_basic_refresh_lock_key(code)
        current = client.get(key)
        if current == token:
            client.delete(key)
    except Exception:
        pass


def set_market_indexes(payload):
    if not payload:
        return
    try:
        client = get_redis_client()
        client.set(
            INDEX_CACHE_KEY,
            json.dumps({
                'ts': time.time(),
                'value': payload,
            }, ensure_ascii=False),
            ex=REDIS_INDEX_TTL_SECONDS,
        )
    except Exception:
        pass


def _read_market_indexes_record():
    try:
        client = get_redis_client()
        raw = client.get(INDEX_CACHE_KEY)
        if not raw:
            return None
        record = json.loads(raw)
        if not isinstance(record, dict):
            return None
        return record
    except Exception:
        return None


def get_market_indexes(ttl_seconds):
    record = _read_market_indexes_record()
    if not record:
        return None

    ts = record.get('ts')
    value = record.get('value')
    try:
        if time.time() - float(ts) > ttl_seconds:
            return None
    except (TypeError, ValueError):
        return None
    return value


def get_stale_market_indexes():
    record = _read_market_indexes_record()
    if not record:
        return None
    return record.get('value')


def acquire_market_indexes_refresh_lock(lock_seconds=5):
    try:
        client = get_redis_client()
        return bool(client.set(INDEX_REFRESH_LOCK_KEY, '1', nx=True, ex=max(1, int(lock_seconds))))
    except Exception:
        return False


def release_market_indexes_refresh_lock():
    try:
        client = get_redis_client()
        client.delete(INDEX_REFRESH_LOCK_KEY)
    except Exception:
        pass
