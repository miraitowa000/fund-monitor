from __future__ import annotations

import json
import time
import uuid

from core.redis_client import get_redis_client


REDIS_DETAIL_TTL_SECONDS = 7 * 24 * 60 * 60
DETAIL_REFRESH_LOCK_PREFIX = 'lock:detail:fund:refresh:'


def _normalize_code(code):
    return str(code or '').zfill(6)


def _build_detail_cache_key(code):
    return f'detail:fund:{_normalize_code(code)}'


def _build_detail_refresh_lock_key(code):
    return f'{DETAIL_REFRESH_LOCK_PREFIX}{_normalize_code(code)}'


def set_fund_detail(code, payload):
    if not payload:
        return
    try:
        client = get_redis_client()
        client.set(
            _build_detail_cache_key(code),
            json.dumps({
                'ts': time.time(),
                'value': payload,
            }, ensure_ascii=False),
            ex=REDIS_DETAIL_TTL_SECONDS,
        )
    except Exception:
        pass


def _read_fund_detail_record(code):
    try:
        client = get_redis_client()
        raw = client.get(_build_detail_cache_key(code))
        if not raw:
            return None
        record = json.loads(raw)
        if not isinstance(record, dict):
            return None
        return record
    except Exception:
        return None


def get_fund_detail(code, ttl_seconds):
    record = _read_fund_detail_record(code)
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


def get_stale_fund_detail(code):
    record = _read_fund_detail_record(code)
    if not record:
        return None
    return record.get('value')


def acquire_detail_refresh_lock(code, lock_seconds=8):
    token = uuid.uuid4().hex
    try:
        client = get_redis_client()
        locked = client.set(
            _build_detail_refresh_lock_key(code),
            token,
            nx=True,
            ex=max(1, int(lock_seconds)),
        )
        if locked:
            return token
    except Exception:
        return None
    return None


def release_detail_refresh_lock(code, token):
    if not token:
        return
    try:
        client = get_redis_client()
        key = _build_detail_refresh_lock_key(code)
        current = client.get(key)
        if current == token:
            client.delete(key)
    except Exception:
        pass
