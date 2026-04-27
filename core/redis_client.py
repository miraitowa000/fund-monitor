from __future__ import annotations

import threading

from redis import Redis

from core.settings import build_redis_url


_REDIS_CLIENT = None
_REDIS_LOCK = threading.Lock()


def get_redis_client() -> Redis:
    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT

    with _REDIS_LOCK:
        if _REDIS_CLIENT is None:
            _REDIS_CLIENT = Redis.from_url(
                build_redis_url(),
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                retry_on_timeout=True,
            )
    return _REDIS_CLIENT


def ping_redis() -> bool:
    try:
        return bool(get_redis_client().ping())
    except Exception:
        return False
