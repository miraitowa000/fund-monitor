import threading
import time
from concurrent.futures import ThreadPoolExecutor

from core.redis_client import get_redis_client


FUNDS_EXECUTOR = ThreadPoolExecutor(max_workers=20)
BG_REFRESH_EXECUTOR = ThreadPoolExecutor(max_workers=6)
DETAIL_EXECUTOR = ThreadPoolExecutor(max_workers=2)

WATCHED_CODE_TTL_SECONDS = 6 * 60 * 60
WATCHED_CODES_REDIS_KEY = 'runtime:watched_codes'

_WATCHED_CODES = {}
_WATCHED_CODES_LOCK = threading.Lock()
_INFLIGHT_BASIC = {}
_INFLIGHT_BASIC_LOCK = threading.Lock()


def _write_watched_codes_to_redis(entries):
    if not entries:
        return
    try:
        client = get_redis_client()
        payload = {code: str(ts) for code, ts in entries.items()}
        if payload:
            client.hset(WATCHED_CODES_REDIS_KEY, mapping=payload)
    except Exception:
        pass


def _read_watched_codes_from_redis():
    try:
        client = get_redis_client()
        values = client.hgetall(WATCHED_CODES_REDIS_KEY) or {}
    except Exception:
        return {}

    records = {}
    for code, ts in values.items():
        try:
            records[str(code).zfill(6)] = float(ts)
        except (TypeError, ValueError):
            continue
    return records


def _prune_watched_codes_in_redis(cutoff):
    try:
        client = get_redis_client()
        values = client.hgetall(WATCHED_CODES_REDIS_KEY) or {}
        stale_codes = []
        for code, ts in values.items():
            try:
                if float(ts) < cutoff:
                    stale_codes.append(code)
            except (TypeError, ValueError):
                stale_codes.append(code)
        if stale_codes:
            client.hdel(WATCHED_CODES_REDIS_KEY, *stale_codes)
        return len(stale_codes)
    except Exception:
        return 0


def register_watched_codes(codes):
    now = time.time()
    updated = {}
    with _WATCHED_CODES_LOCK:
        for code in codes:
            norm_code = str(code).zfill(6)
            _WATCHED_CODES[norm_code] = now
            updated[norm_code] = now
    _write_watched_codes_to_redis(updated)


def get_watched_codes():
    merged = _read_watched_codes_from_redis()
    with _WATCHED_CODES_LOCK:
        merged.update(_WATCHED_CODES)
    return list(merged.keys())


def prune_watched_codes(max_age_seconds=WATCHED_CODE_TTL_SECONDS):
    removed = 0
    cutoff = time.time() - max_age_seconds
    with _WATCHED_CODES_LOCK:
        stale_codes = [code for code, ts in _WATCHED_CODES.items() if ts < cutoff]
        for code in stale_codes:
            _WATCHED_CODES.pop(code, None)
            removed += 1
    removed += _prune_watched_codes_in_redis(cutoff)
    return removed


def get_inflight_basic(code):
    norm_code = str(code).zfill(6)
    with _INFLIGHT_BASIC_LOCK:
        future = _INFLIGHT_BASIC.get(norm_code)
        if future and not future.done():
            return future
    return None


def set_inflight_basic(code, future):
    norm_code = str(code).zfill(6)
    with _INFLIGHT_BASIC_LOCK:
        _INFLIGHT_BASIC[norm_code] = future

    def _cleanup(done_future, code_key=norm_code):
        with _INFLIGHT_BASIC_LOCK:
            current = _INFLIGHT_BASIC.get(code_key)
            if current is done_future:
                _INFLIGHT_BASIC.pop(code_key, None)

    future.add_done_callback(_cleanup)
    return future
