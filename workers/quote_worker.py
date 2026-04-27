import signal
import sys
import time

from core.settings import build_mysql_uri, build_redis_url
from core.redis_client import ping_redis
from services.fund_service import start_background_refresh_thread
from services.index_service import get_indexes
from services.user_fund_service import init_database


_RUNNING = True


def _handle_signal(signum, frame):
    global _RUNNING
    _RUNNING = False


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    print('启动行情刷新 Worker...')
    print(f'MySQL: {build_mysql_uri(mask_password=True)}')
    print(f'Redis: {build_redis_url(mask_password=True)}')

    init_database()
    print(f'Redis 连通性: {"ok" if ping_redis() else "unavailable"}')

    start_background_refresh_thread()
    print('后台刷新线程已启动')

    next_index_refresh_at = 0
    while _RUNNING:
        now = time.time()
        if now >= next_index_refresh_at:
          get_indexes(force_refresh=True)
          next_index_refresh_at = now + 15
        time.sleep(1)

    print('行情刷新 Worker 已停止')


if __name__ == '__main__':
    main()
