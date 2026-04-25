from __future__ import annotations

import threading
import time
from collections import defaultdict

from core.redis_client import get_redis_client


COUNTERS_KEY = 'perf:metrics:counters'
TIMINGS_KEY = 'perf:metrics:timings'

_LOCAL_COUNTERS = defaultdict(float)
_LOCAL_TIMINGS = defaultdict(float)
_LOCAL_LOCK = threading.Lock()


def increment_metric(name, value=1):
    metric_name = str(name or '').strip()
    if not metric_name:
        return
    try:
        client = get_redis_client()
        client.hincrbyfloat(COUNTERS_KEY, metric_name, float(value))
    except Exception:
        with _LOCAL_LOCK:
            _LOCAL_COUNTERS[metric_name] += float(value)


def observe_duration_ms(name, elapsed_ms):
    metric_name = str(name or '').strip()
    if not metric_name:
        return

    elapsed_value = max(float(elapsed_ms or 0), 0.0)
    try:
        client = get_redis_client()
        pipeline = client.pipeline()
        pipeline.hincrbyfloat(TIMINGS_KEY, f'{metric_name}.count', 1.0)
        pipeline.hincrbyfloat(TIMINGS_KEY, f'{metric_name}.sum_ms', elapsed_value)
        pipeline.hget(TIMINGS_KEY, f'{metric_name}.max_ms')
        result = pipeline.execute()
        current_max = result[2]
        current_max_value = float(current_max) if current_max is not None else 0.0
        if elapsed_value > current_max_value:
            client.hset(TIMINGS_KEY, f'{metric_name}.max_ms', elapsed_value)
    except Exception:
        with _LOCAL_LOCK:
            _LOCAL_TIMINGS[f'{metric_name}.count'] += 1.0
            _LOCAL_TIMINGS[f'{metric_name}.sum_ms'] += elapsed_value
            max_key = f'{metric_name}.max_ms'
            _LOCAL_TIMINGS[max_key] = max(_LOCAL_TIMINGS.get(max_key, 0.0), elapsed_value)


def snapshot_metrics():
    counters = {}
    timings = {}

    try:
        client = get_redis_client()
        raw_counters = client.hgetall(COUNTERS_KEY) or {}
        raw_timings = client.hgetall(TIMINGS_KEY) or {}
        counters = {key: float(value) for key, value in raw_counters.items()}
        timings = {key: float(value) for key, value in raw_timings.items()}
    except Exception:
        pass

    with _LOCAL_LOCK:
        for key, value in _LOCAL_COUNTERS.items():
            counters[key] = counters.get(key, 0.0) + float(value)
        for key, value in _LOCAL_TIMINGS.items():
            timings[key] = timings.get(key, 0.0) + float(value)

    timing_summary = {}
    metric_names = {key.rsplit('.', 1)[0] for key in timings.keys() if '.' in key}
    for name in metric_names:
        count = float(timings.get(f'{name}.count', 0.0))
        total = float(timings.get(f'{name}.sum_ms', 0.0))
        maximum = float(timings.get(f'{name}.max_ms', 0.0))
        timing_summary[name] = {
            'count': int(count),
            'avg_ms': round(total / count, 2) if count > 0 else 0.0,
            'max_ms': round(maximum, 2),
            'sum_ms': round(total, 2),
        }

    return {
        'generated_at': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()),
        'counters': dict(sorted(counters.items())),
        'timings': dict(sorted(timing_summary.items())),
    }
