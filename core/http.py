import threading
import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3.util.retry import Retry

from core.perf_metrics import increment_metric, observe_duration_ms


_HTTP = requests.Session()
_HTTP_RETRY = Retry(
    total=1,
    connect=1,
    read=0,
    status=0,
    backoff_factor=0.1,
    allowed_methods=frozenset(['GET']),
)
_HTTP_ADAPTER = HTTPAdapter(
    pool_connections=64,
    pool_maxsize=64,
    max_retries=_HTTP_RETRY,
)
_HTTP.mount('http://', _HTTP_ADAPTER)
_HTTP.mount('https://', _HTTP_ADAPTER)

HTTP_FAILURE_THRESHOLD = 3
HTTP_FAILURE_WINDOW_SECONDS = 20
HTTP_FAILURE_COOLDOWN_SECONDS = 8

_HOST_FAILURES = {}
_HOST_FAILURES_LOCK = threading.Lock()


class UpstreamCircuitOpen(RequestException):
    pass


def _get_host_key(url):
    parsed = urlparse(str(url or ''))
    return (parsed.scheme or 'http', parsed.netloc or parsed.path or '')


def _host_metric_suffix(host_key):
    raw = str(host_key[1] or 'unknown').lower()
    normalized = ''.join(ch if ch.isalnum() else '_' for ch in raw)
    return normalized.strip('_') or 'unknown'


def _is_failure_status(status_code):
    try:
        status = int(status_code)
    except Exception:
        return False
    return status == 429 or status >= 500


def _should_short_circuit(host_key):
    now = time.time()
    with _HOST_FAILURES_LOCK:
        state = _HOST_FAILURES.get(host_key)
        if not state:
            return False
        cooldown_until = float(state.get('cooldown_until') or 0)
        if cooldown_until > now:
            return True
        if cooldown_until:
            state['cooldown_until'] = 0
        return False


def _mark_host_success(host_key):
    with _HOST_FAILURES_LOCK:
        _HOST_FAILURES.pop(host_key, None)


def _mark_host_failure(host_key):
    now = time.time()
    with _HOST_FAILURES_LOCK:
        state = _HOST_FAILURES.get(host_key) or {
            'count': 0,
            'first_failure_at': now,
            'last_failure_at': now,
            'cooldown_until': 0,
        }
        window_start = float(state.get('first_failure_at') or now)
        if now - window_start > HTTP_FAILURE_WINDOW_SECONDS:
            state['count'] = 0
            state['first_failure_at'] = now

        state['count'] = int(state.get('count') or 0) + 1
        state['last_failure_at'] = now
        if state['count'] >= HTTP_FAILURE_THRESHOLD:
            state['cooldown_until'] = now + HTTP_FAILURE_COOLDOWN_SECONDS
        _HOST_FAILURES[host_key] = state


def http_get(url, headers=None, timeout=3):
    host_key = _get_host_key(url)
    host_suffix = _host_metric_suffix(host_key)
    if _should_short_circuit(host_key):
        increment_metric('http.circuit_open')
        increment_metric(f'http.host.{host_suffix}.circuit_open')
        raise UpstreamCircuitOpen(f'upstream circuit open for {host_key[1]}')

    started_at = time.perf_counter()
    try:
        response = _HTTP.get(url, headers=headers, timeout=timeout)
    except RequestException:
        _mark_host_failure(host_key)
        increment_metric('http.request_error')
        increment_metric(f'http.host.{host_suffix}.request_error')
        observe_duration_ms('http.request', (time.perf_counter() - started_at) * 1000)
        observe_duration_ms(f'http.host.{host_suffix}.request', (time.perf_counter() - started_at) * 1000)
        raise

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    increment_metric('http.request_total')
    increment_metric(f'http.host.{host_suffix}.request_total')
    observe_duration_ms('http.request', elapsed_ms)
    observe_duration_ms(f'http.host.{host_suffix}.request', elapsed_ms)
    if _is_failure_status(response.status_code):
        _mark_host_failure(host_key)
        increment_metric('http.response_failure')
        increment_metric(f'http.host.{host_suffix}.response_failure')
    else:
        _mark_host_success(host_key)
    return response
