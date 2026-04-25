from __future__ import annotations

import json
import time

from core.redis_client import get_redis_client


REDIS_SNAPSHOT_TTL_SECONDS = 20


def _normalize_client_id(client_id):
    return str(client_id or '').strip()


def _build_snapshot_cache_key(client_id):
    return f'snapshot:user:{_normalize_client_id(client_id)}'


def set_user_snapshot(client_id, payload):
    normalized_client_id = _normalize_client_id(client_id)
    if not normalized_client_id or not payload:
        return

    try:
        client = get_redis_client()
        client.set(
            _build_snapshot_cache_key(normalized_client_id),
            json.dumps({
                'ts': time.time(),
                'value': payload,
            }, ensure_ascii=False),
            ex=REDIS_SNAPSHOT_TTL_SECONDS,
        )
    except Exception:
        pass


def _read_user_snapshot_record(client_id):
    normalized_client_id = _normalize_client_id(client_id)
    if not normalized_client_id:
        return None

    try:
        client = get_redis_client()
        raw = client.get(_build_snapshot_cache_key(normalized_client_id))
        if not raw:
            return None
        record = json.loads(raw)
        if not isinstance(record, dict):
            return None
        return record
    except Exception:
        return None


def get_user_snapshot(client_id, ttl_seconds=REDIS_SNAPSHOT_TTL_SECONDS):
    record = _read_user_snapshot_record(client_id)
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


def invalidate_user_snapshot(client_id):
    normalized_client_id = _normalize_client_id(client_id)
    if not normalized_client_id:
        return

    try:
        client = get_redis_client()
        client.delete(_build_snapshot_cache_key(normalized_client_id))
    except Exception:
        pass
