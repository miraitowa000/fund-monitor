import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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


def http_get(url, headers=None, timeout=3):
    return _HTTP.get(url, headers=headers, timeout=timeout)
