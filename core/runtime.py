import threading
import time
from concurrent.futures import ThreadPoolExecutor


FUNDS_EXECUTOR = ThreadPoolExecutor(max_workers=20)
BG_REFRESH_EXECUTOR = ThreadPoolExecutor(max_workers=6)
DETAIL_EXECUTOR = ThreadPoolExecutor(max_workers=2)

WATCHED_CODE_TTL_SECONDS = 6 * 60 * 60

_WATCHED_CODES = {}
_WATCHED_CODES_LOCK = threading.Lock()
_INFLIGHT_BASIC = {}
_INFLIGHT_BASIC_LOCK = threading.Lock()


def register_watched_codes(codes):
    now = time.time()
    with _WATCHED_CODES_LOCK:
        for code in codes:
            _WATCHED_CODES[str(code).zfill(6)] = now


def get_watched_codes():
    with _WATCHED_CODES_LOCK:
        return list(_WATCHED_CODES.keys())


def prune_watched_codes(max_age_seconds=WATCHED_CODE_TTL_SECONDS):
    removed = 0
    cutoff = time.time() - max_age_seconds
    with _WATCHED_CODES_LOCK:
        stale_codes = [code for code, ts in _WATCHED_CODES.items() if ts < cutoff]
        for code in stale_codes:
            _WATCHED_CODES.pop(code, None)
            removed += 1
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
