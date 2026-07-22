import threading

from core.runtime import PORTFOLIO_REFRESH_EXECUTOR, PORTFOLIO_REFRESH_SEMAPHORE
from core.perf_metrics import increment_metric
from core.time_utils import china_now
from services.dashboard_cache_service import (
    get_dashboard_bootstrap as get_cached_dashboard_bootstrap,
    set_dashboard_bootstrap,
)
from services.index_service import get_indexes
from services.fund_transaction_service import confirm_pending_transactions
from services.fund_conversion_service import confirm_pending_conversions
from services.user_fund_profit_service import get_user_portfolio
from services.portfolio_cache_service import (
    get_stale_user_portfolio,
    get_user_portfolio as get_cached_user_portfolio,
)
from services.user_fund_service import bootstrap_user_funds, get_user_snapshot
from services.user_fund_service import ensure_user


_PORTFOLIO_REFRESH_INFLIGHT = set()
_PORTFOLIO_REFRESH_LOCK = threading.Lock()


def _refresh_portfolio_in_background(client_id, user_funds):
    try:
        get_user_portfolio(client_id, force_refresh=True, user_funds=user_funds, confirm_pending=False)
    except Exception:
        increment_metric('cache.portfolio.bootstrap_bg_refresh_error')
    finally:
        try:
            PORTFOLIO_REFRESH_SEMAPHORE.release()
        except Exception:
            pass
        with _PORTFOLIO_REFRESH_LOCK:
            _PORTFOLIO_REFRESH_INFLIGHT.discard(str(client_id or '').strip())


def _schedule_portfolio_refresh(client_id, user_funds):
    normalized_client_id = str(client_id or '').strip()
    if not normalized_client_id:
        return False

    with _PORTFOLIO_REFRESH_LOCK:
        if normalized_client_id in _PORTFOLIO_REFRESH_INFLIGHT:
            increment_metric('cache.portfolio.bootstrap_bg_refresh_reuse')
            return False
        _PORTFOLIO_REFRESH_INFLIGHT.add(normalized_client_id)

    if not PORTFOLIO_REFRESH_SEMAPHORE.acquire(blocking=False):
        increment_metric('cache.portfolio.bootstrap_bg_refresh_throttled')
        with _PORTFOLIO_REFRESH_LOCK:
            _PORTFOLIO_REFRESH_INFLIGHT.discard(normalized_client_id)
        return False

    try:
        PORTFOLIO_REFRESH_EXECUTOR.submit(
            _refresh_portfolio_in_background,
            normalized_client_id,
            user_funds,
        )
    except Exception:
        PORTFOLIO_REFRESH_SEMAPHORE.release()
        with _PORTFOLIO_REFRESH_LOCK:
            _PORTFOLIO_REFRESH_INFLIGHT.discard(normalized_client_id)
        increment_metric('cache.portfolio.bootstrap_bg_refresh_submit_error')
        return False

    increment_metric('cache.portfolio.bootstrap_bg_refresh_submit')
    return True


def get_dashboard_bootstrap(client_id, legacy_codes=None):
    legacy_codes = legacy_codes or []
    user_id = ensure_user(client_id)

    try:
        confirm_result = confirm_pending_transactions(user_id=user_id)
    except Exception:
        confirm_result = {'confirmed': 0}
    try:
        conversion_confirm_result = confirm_pending_conversions(user_id=user_id)
    except Exception:
        conversion_confirm_result = {'confirmed': 0}

    confirmed_count = int(confirm_result.get('confirmed') or 0) + int(conversion_confirm_result.get('confirmed') or 0)

    if not legacy_codes:
        cached = get_cached_dashboard_bootstrap(client_id)
        if cached and not confirmed_count:
            increment_metric('cache.dashboard.hit')
            return cached
        increment_metric('cache.dashboard.miss')
    else:
        increment_metric('cache.dashboard.bypass_legacy')

    snapshot = get_user_snapshot(client_id)
    bootstrapped_legacy = False

    if (
        legacy_codes
        and not snapshot.get('initialized')
        and not (snapshot.get('funds') or [])
    ):
        bootstrap_user_funds(client_id, legacy_codes)
        snapshot = get_user_snapshot(client_id, force_refresh=True)
        bootstrapped_legacy = True

    user_funds = snapshot.get('funds') or []
    portfolio_stale = False
    portfolio = get_cached_user_portfolio(client_id)
    if portfolio:
        increment_metric('cache.portfolio.bootstrap_hit')
    else:
        increment_metric('cache.portfolio.bootstrap_miss')
        stale_portfolio = get_stale_user_portfolio(client_id)
        if stale_portfolio:
            increment_metric('cache.portfolio.bootstrap_stale_hit')
            portfolio = stale_portfolio
            portfolio_stale = True
            _schedule_portfolio_refresh(client_id, user_funds)
        else:
            increment_metric('cache.portfolio.bootstrap_sync_refresh')
            portfolio = get_user_portfolio(
                client_id,
                force_refresh=True,
                user_funds=user_funds,
                request_timeout=6,
                confirm_pending=False,
            )

    payload = {
        'success': True,
        'snapshot': snapshot,
        'portfolio': portfolio,
        'indexes': get_indexes(),
        'bootstrapped_legacy': bootstrapped_legacy,
        'portfolio_stale': portfolio_stale,
        'server_time': china_now().strftime('%Y-%m-%d %H:%M:%S'),
    }

    if portfolio_stale:
        increment_metric('cache.dashboard.skip_set_stale_portfolio')
    else:
        set_dashboard_bootstrap(client_id, payload)
    return payload
