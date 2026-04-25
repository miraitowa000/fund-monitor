from datetime import datetime

from core.perf_metrics import increment_metric
from services.dashboard_cache_service import (
    get_dashboard_bootstrap as get_cached_dashboard_bootstrap,
    set_dashboard_bootstrap,
)
from services.index_service import get_indexes
from services.user_fund_profit_service import get_user_portfolio
from services.user_fund_service import bootstrap_user_funds, get_user_snapshot


def get_dashboard_bootstrap(client_id, legacy_codes=None):
    legacy_codes = legacy_codes or []

    if not legacy_codes:
        cached = get_cached_dashboard_bootstrap(client_id)
        if cached:
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

    payload = {
        'success': True,
        'snapshot': snapshot,
        'portfolio': get_user_portfolio(client_id, user_funds=snapshot.get('funds') or []),
        'indexes': get_indexes(),
        'bootstrapped_legacy': bootstrapped_legacy,
        'server_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    set_dashboard_bootstrap(client_id, payload)
    return payload
