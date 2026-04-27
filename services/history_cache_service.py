from __future__ import annotations

import json
import time
import uuid

from core.redis_client import get_redis_client


REDIS_HISTORY_TTL_SECONDS = 24 * 60 * 60
HISTORY_REFRESH_LOCK_PREFIX = 'lock:history:fund:refresh:'


def _normalize_code(code):
    return str(code or '').zfill(6)


def _normalize_days(days):
    return max(30, min(int(days or 30), 365))


def _build_history_cache_key(code, days):
    return f'history:fund:{_normalize_code(code)}:{_normalize_days(days)}'


def _build_history_refresh_lock_key(code, days):
    return f'{HISTORY_REFRESH_LOCK_PREFIX}{_normalize_code(code)}:{_normalize_days(days)}'


def set_fund_history(code, days, payload):
    if not payload:
        return
    try:
        client = get_redis_client()
        client.set(
            _build_history_cache_key(code, days),
            json.dumps({
                'ts': time.time(),
                'value': payload,
            }, ensure_ascii=False),
            ex=REDIS_HISTORY_TTL_SECONDS,
        )
    except Exception:
        pass


def _read_fund_history_record(code, days):
    try:
        client = get_redis_client()
        raw = client.get(_build_history_cache_key(code, days))
        if not raw:
            return None
        record = json.loads(raw)
        if not isinstance(record, dict):
            return None
        return record
    except Exception:
        return None


def get_fund_history(code, days, ttl_seconds):
    record = _read_fund_history_record(code, days)
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


def get_stale_fund_history(code, days):
    record = _read_fund_history_record(code, days)
    if not record:
        return None
    return record.get('value')


def acquire_history_refresh_lock(code, days, lock_seconds=10):
    token = uuid.uuid4().hex
    try:
        client = get_redis_client()
        locked = client.set(
            _build_history_refresh_lock_key(code, days),
            token,
            nx=True,
            ex=max(1, int(lock_seconds)),
        )
        if locked:
            return token
    except Exception:
        return None
    return None


def release_history_refresh_lock(code, days, token):
    if not token:
        return
    try:
        client = get_redis_client()
        key = _build_history_refresh_lock_key(code, days)
        current = client.get(key)
        if current == token:
            client.delete(key)
    except Exception:
        pass
