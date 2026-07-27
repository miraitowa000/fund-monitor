import json
import re
import threading
import time
from concurrent.futures import Future, wait as futures_wait
from functools import lru_cache

from core.cache import cache_get, cache_get_age, cache_get_stale, cache_prune, cache_set
from core.http import http_get
from core.perf_metrics import increment_metric
from core.runtime import BG_REFRESH_EXECUTOR, FUNDS_EXECUTOR, get_inflight_basic, get_watched_codes, prune_watched_codes, set_inflight_basic
from core.time_utils import china_now, timestamp_to_china_datetime
from services.fund_valuation_service import get_fund_valuation
from services.quote_cache_service import (
    acquire_basic_quote_refresh_lock,
    get_basic_quote,
    get_stale_basic_quote,
    release_basic_quote_refresh_lock,
    set_basic_quote,
)
from services.intraday_series_service import (
    get_active_position_fund_codes,
    is_intraday_collection_open,
    record_intraday_snapshots,
)

try:
    import akshare as ak
except Exception:
    ak = None


TTL_BASIC_SECONDS = 60
TTL_HOLDINGS_SECONDS = 180
TTL_HISTORY_SECONDS = 600
TTL_DETAIL_SECONDS = 60
TTL_PINGZHONG_SECONDS = 180
TTL_RELATED_ETF_SECONDS = 1800
DETAIL_REQUEST_TIMEOUT_SECONDS = 6
BASIC_REFRESH_LOCK_SECONDS = 8
BASIC_WAIT_FOR_REMOTE_REFRESH_SECONDS = 2.5
BASIC_WAIT_STEP_SECONDS = 0.1

LINK_ETF_MANUAL_MAP = {
    '015283': ('513580', '华安恒生科技(QDII-ETF)'),
    '015282': ('513580', '华安恒生科技(QDII-ETF)'),
    '023833': ('561570', '华泰柏瑞中证油气产业ETF'),
}

_FUND_LIST_CACHE = None
_FUND_LIST_CACHE_LOCK = threading.Lock()
_BG_THREAD = None
_BG_THREAD_LOCK = threading.Lock()


def _build_basic_payload(
    code,
    name,
    gsz='-',
    gszzl='-',
    gztime='-',
    dwjz='-',
    jzrq='-',
    success=False,
    message='',
    nav_confirmed=False,
    confirmed_nav='',
    confirmed_change='',
    display_date='-',
    confirmed_date='-',
    base_date='-',
    quote_source='',
):
    return {
        'code': code,
        'name': name,
        'gsz': gsz,
        'gszzl': gszzl,
        'gztime': gztime,
        'dwjz': dwjz,
        'jzrq': jzrq,
        'success': success,
        'message': message,
        'nav_confirmed': nav_confirmed,
        'confirmed_nav': confirmed_nav,
        'confirmed_change': confirmed_change,
        'display_date': display_date,
        'confirmed_date': confirmed_date,
        'base_date': base_date,
        'quote_source': quote_source,
    }


def _first_col(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _clean_name(name):
    text = str(name or '')
    for token in ['(', ')', '（', '）', '-', ' ', '\t']:
        text = text.replace(token, '')
    return text


def get_cached_fund_list():
    global _FUND_LIST_CACHE
    if ak is None:
        return None
    if _FUND_LIST_CACHE is not None:
        return _FUND_LIST_CACHE
    with _FUND_LIST_CACHE_LOCK:
        if _FUND_LIST_CACHE is not None:
            return _FUND_LIST_CACHE
        try:
            df = ak.fund_name_em()
            if df is None or df.empty:
                return None
            code_col = _first_col(df, ['基金代码', '代码'])
            name_col = _first_col(df, ['基金简称', '基金名称', '名称'])
            if not code_col or not name_col:
                return None
            df = df.copy()
            df[code_col] = df[code_col].astype(str).str.zfill(6)
            df['clean_name'] = df[name_col].astype(str).map(_clean_name)
            search_rows = [
                {
                    'code': str(row.get(code_col, '') or '').zfill(6),
                    'name': str(row.get(name_col, '') or '').strip(),
                    'clean_name': str(row.get('clean_name', '') or '').lower(),
                }
                for row in df[[code_col, name_col, 'clean_name']].to_dict('records')
            ]
            _FUND_LIST_CACHE = {
                'df': df,
                'code_col': code_col,
                'name_col': name_col,
                'name_map': dict(zip(df[code_col], df[name_col].astype(str))),
                'search_rows': [row for row in search_rows if row['code'] and row['name']],
            }
            return _FUND_LIST_CACHE
        except Exception:
            return None


def get_fund_name_by_code(fund_code):
    cache = get_cached_fund_list()
    if not cache:
        return ''
    try:
        return str(cache.get('name_map', {}).get(str(fund_code).zfill(6), ''))
    except Exception:
        return ''


@lru_cache(maxsize=256)
def _search_funds_cached(normalized_query, max_items):
    cache = get_cached_fund_list()
    if not cache:
        return []

    search_rows = cache.get('search_rows') or []
    records = []
    for row in search_rows:
        code = row['code']
        name = row['name']
        clean_name = row['clean_name']

        score = None
        if code == normalized_query:
            score = 0
        elif code.startswith(normalized_query):
            score = 1
        elif normalized_query in clean_name:
            score = 2
        elif normalized_query in name.lower():
            score = 3

        if score is None:
            continue

        records.append({
            'code': code,
            'name': name,
            'match_score': score,
        })

    records.sort(key=lambda item: (item['match_score'], len(item['code']), item['code']))
    return [
        {'code': item['code'], 'name': item['name']}
        for item in records[:max_items]
    ]


def search_funds(keyword, limit=10):
    cache = get_cached_fund_list()
    if not cache:
        return []

    query = str(keyword or '').strip()
    if not query:
        return []

    normalized_query = _clean_name(query).lower()
    if not normalized_query:
        return []

    try:
        max_items = max(1, min(int(limit), 20))
    except Exception:
        max_items = 10

    try:
        return _search_funds_cached(normalized_query, max_items)
    except Exception:
        return []


def get_pingzhongdata_snapshot(fund_code):
    code = str(fund_code).zfill(6)
    cached = cache_get('pingzhong', code, TTL_PINGZHONG_SECONDS)
    if cached:
        return cached
    try:
        response = http_get(
            f"https://fund.eastmoney.com/pingzhongdata/{code}.js?v={int(time.time() * 1000)}",
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Referer': f'https://fund.eastmoney.com/{code}.html'},
            timeout=5,
        )
        if response.status_code != 200 or not response.text:
            return None
        text = response.text

        def extract_string(var_name):
            match = re.search(rf'var\s+{var_name}\s*=\s*"([^"]*)";', text)
            return match.group(1).strip() if match else ''

        def extract_json(var_name):
            match = re.search(rf'var\s+{var_name}\s*=\s*(.*?);', text, re.S)
            if not match:
                return None
            try:
                return json.loads(match.group(1).strip())
            except Exception:
                return None

        networth = extract_json('Data_netWorthTrend') or []
        latest = networth[-1] if networth else {}
        previous = networth[-2] if len(networth) >= 2 else {}

        def _fmt_date(item):
            try:
                return timestamp_to_china_datetime(float(item.get('x')) / 1000).strftime('%Y-%m-%d')
            except Exception:
                return ''

        result = {
            'code': extract_string('fS_code') or code,
            'name': extract_string('fS_name'),
            'networth': networth,
            'grand_total': extract_json('Data_grandTotal') or [],
            'rate_in_similar_type': extract_json('Data_rateInSimilarType') or [],
            'rate_in_similar_percent': extract_json('Data_rateInSimilarPersent') or [],
            'latest_date': _fmt_date(latest) if isinstance(latest, dict) else '',
            'latest_value': str(round(float(latest.get('y')), 4)) if isinstance(latest, dict) and latest.get('y') not in (None, '') else '-',
            'latest_change': f"{float(latest.get('equityReturn', 0)):.2f}" if isinstance(latest, dict) and latest.get('equityReturn') not in (None, '') else '-',
            'previous_date': _fmt_date(previous) if isinstance(previous, dict) else '',
            'previous_value': str(round(float(previous.get('y')), 4)) if isinstance(previous, dict) and previous.get('y') not in (None, '') else '-',
            'stock_codes_new': extract_json('stockCodesNew') or [],
        }
        cache_set('pingzhong', code, result)
        return result
    except Exception:
        return None


def _is_qdii_like_snapshot(snapshot):
    if not snapshot:
        return False
    overseas_count = 0
    total_count = 0
    for item in snapshot.get('stock_codes_new') or []:
        text = str(item or '').strip()
        if not text:
            continue
        total_count += 1
        market_code = text.split('.', 1)[0]
        if market_code in ('105', '106'):
            return True
        if market_code == '116':
            overseas_count += 1
    return total_count > 0 and overseas_count >= 3 and overseas_count / total_count >= 0.5


def _build_snapshot_estimate(code, fallback_name, snapshot, message):
    latest_date = snapshot.get('latest_date', '-') if snapshot else '-'
    return _sync_confirmation_fields(_build_basic_payload(
        code=code,
        name=snapshot.get('name') if snapshot and snapshot.get('name') else fallback_name,
        gsz=snapshot.get('latest_value', '-') if snapshot else '-',
        gszzl=snapshot.get('latest_change', '-') if snapshot else '-',
        gztime=latest_date or '-',
        dwjz=snapshot.get('previous_value', '-') if snapshot else '-',
        jzrq=latest_date or '-',
        success=False,
        message=message,
        confirmed_nav=snapshot.get('latest_value', '-') if snapshot else '-',
        confirmed_change=snapshot.get('latest_change', '-') if snapshot else '-',
        display_date=latest_date or '-',
        confirmed_date=latest_date or '-',
        base_date=snapshot.get('previous_date', latest_date) if snapshot else '-',
        quote_source='history_fallback',
    ))


def _load_pingzhong_fallback(code, fallback_name, message, snapshot=None):
    snapshot = snapshot or get_pingzhongdata_snapshot(code)
    if snapshot and snapshot.get('name'):
        fallback_name = snapshot.get('name') or fallback_name
    if snapshot and _is_qdii_like_snapshot(snapshot):
        return _build_snapshot_estimate(code, fallback_name, snapshot, f"QDII暂无盘中估值，展示最近净值 {snapshot.get('latest_date', '-') or '-'}")
    if snapshot and snapshot.get('latest_value') not in ('', '-', None):
        return _build_snapshot_estimate(code, fallback_name, snapshot, f"{message}，展示最近净值 {snapshot.get('latest_date', '-') or '-'}")
    return _build_basic_payload(
        code=code,
        name=fallback_name,
        gsz='-',
        gszzl='-',
        gztime='-',
        dwjz=snapshot.get('latest_value', '-') if snapshot else '-',
        jzrq=snapshot.get('latest_date', '-') if snapshot else '-',
        success=False,
        message=message,
        display_date='-',
        confirmed_date=snapshot.get('latest_date', '-') if snapshot else '-',
        base_date=snapshot.get('latest_date', '-') if snapshot else '-',
    )


def _parse_number(value):
    match = re.search(r'-?\d+(?:\.\d+)?', str(value or ''))
    if not match:
        return None
    try:
        return float(match.group(0))
    except (TypeError, ValueError):
        return None


def _build_holdings_estimate(code, fallback_name, snapshot, direct_source_message):
    if not snapshot or _is_qdii_like_snapshot(snapshot):
        return None

    base_nav = _parse_number(snapshot.get('latest_value'))
    base_date = _date_text(snapshot.get('latest_date'))
    if base_nav is None or base_nav <= 0 or base_date == '-':
        return None

    try:
        # Lazy import avoids the fund detail/basic service import cycle.
        from services.fund_detail_service import get_fund_holdings

        holdings_result = cache_get('holdings', code, TTL_HOLDINGS_SECONDS)
        if not holdings_result:
            holdings_result = get_fund_holdings(code)
            if holdings_result and holdings_result.get('success'):
                cache_set('holdings', code, holdings_result)
    except Exception:
        return None
    if not holdings_result or not holdings_result.get('success'):
        return None

    today = china_now().strftime('%Y-%m-%d')
    weighted_change = 0.0
    coverage = 0.0
    quote_count = 0
    quote_times = []
    holdings = holdings_result.get('holdings') or []
    holding_count = len(holdings)
    for item in holdings:
        weight = _parse_number(item.get('pct'))
        change = _parse_number(item.get('change_pct'))
        quote_date = _date_text(item.get('quote_date'))
        if weight is None or weight <= 0 or change is None or quote_date != today:
            continue
        weighted_change += weight * change / 100
        coverage += weight
        quote_count += 1
        quote_time = str(item.get('quote_time') or '').strip()
        if re.fullmatch(r'\d{2}:\d{2}:\d{2}', quote_time):
            quote_times.append(quote_time)

    if quote_count < 5 or coverage < 20 or coverage > 100.5:
        return None

    estimated_nav = base_nav * (1 + weighted_change / 100)
    if estimated_nav <= 0:
        return None

    report_date = _date_text(holdings_result.get('date'))
    report_label = report_date if report_date != '-' else '最近披露期'
    quote_time = max(quote_times) if quote_times else china_now().strftime('%H:%M:%S')
    result = _build_basic_payload(
        code=code,
        name=snapshot.get('name') or fallback_name,
        gsz=f'{estimated_nav:.4f}',
        gszzl=f'{weighted_change:.2f}',
        gztime=f'{today} {quote_time}',
        dwjz=f'{base_nav:.4f}',
        jzrq=base_date,
        success=True,
        message=(
            f'{direct_source_message}；按 {report_label} 前十大持仓估算'
            f'（行情 {quote_count}/{holding_count}，覆盖净值 {coverage:.2f}%）'
        ),
        display_date=today,
        confirmed_date=base_date,
        base_date=base_date,
        quote_source='holdings_weighted_estimate',
    )
    result['holding_report_date'] = report_date
    result['holding_coverage'] = round(coverage, 2)
    result['holding_quote_count'] = quote_count
    result['holding_count'] = holding_count
    return _sync_confirmation_fields(result)


def _is_trading_hours():
    """判断当前是否在交易时段（周一到周五 9:30-11:30, 13:00-15:00）"""
    now = china_now()
    # 周末不交易（0=周一, 6=周日）
    if now.weekday() >= 5:
        return False
    # 计算当前分钟数
    current_minutes = now.hour * 60 + now.minute
    # 上午交易时段：9:30-11:30 (570-690分钟)
    morning_trading = 570 <= current_minutes < 690
    # 下午交易时段：13:00-15:00 (780-900分钟)
    afternoon_trading = 780 <= current_minutes < 900
    return morning_trading or afternoon_trading


def _should_check_confirmed_nav(fund_name):
    """判断是否需要查询历史接口获取官方净值"""
    fund_name_upper = str(fund_name or '').upper()
    # QDII 基金始终查询（更新时间不固定）
    if 'QDII' in fund_name_upper or 'QDII-ETF' in fund_name_upper:
        return True
    # 非交易时段查询
    return not _is_trading_hours()


def _date_text(date_text):
    raw = str(date_text or '').strip()
    if not raw or raw == '-':
        return '-'
    return raw.split(' ')[0]


def _should_use_stale_basic(stale):
    if not stale:
        return False
    now = china_now()
    if now.weekday() >= 5:
        return True

    current_minutes = now.hour * 60 + now.minute
    if current_minutes < 540:
        return True

    stale_date = _date_text((stale or {}).get('display_date') or (stale or {}).get('gztime'))
    if stale_date == '-' or stale_date == now.strftime('%Y-%m-%d'):
        return True
    return False


def _sync_confirmation_fields(result):
    display_date = _date_text(result.get('display_date') or result.get('gztime'))
    confirmed_date = _date_text(result.get('confirmed_date') or result.get('jzrq'))
    base_date = _date_text(result.get('base_date') or result.get('jzrq'))

    result['display_date'] = display_date
    result['confirmed_date'] = confirmed_date
    result['base_date'] = base_date

    is_confirmed = display_date != '-' and confirmed_date != '-' and display_date == confirmed_date
    result['nav_confirmed'] = is_confirmed

    if is_confirmed:
        result['confirmed_nav'] = str(result.get('confirmed_nav') or result.get('gsz') or '')
        result['confirmed_change'] = str(result.get('confirmed_change') or result.get('gszzl') or '')
    else:
        result['confirmed_nav'] = str(result.get('confirmed_nav') or '')
        result['confirmed_change'] = str(result.get('confirmed_change') or '')

    return result


def _enrich_confirmed_nav(code, result):
    today = china_now().strftime('%Y-%m-%d')
    fund_name = result.get('name', '')

    # 判断是否需要查询历史接口
    if not _should_check_confirmed_nav(fund_name):
        # 交易时段，使用估算值
        return _sync_confirmation_fields(result)

    # 非交易时段或 QDII 基金，查询历史接口
    try:
        from services.fund_detail_service import get_fund_networth_history

        history_result = get_fund_networth_history(code, days=2)
        if history_result.get('success') and history_result.get('data'):
            history_data = history_result['data']
            if not history_data:
                return _sync_confirmation_fields(result)

            latest = history_data[-1]

            # 如果最新记录是今天，说明官方净值已公布
            if latest and latest.get('date') == today:
                result['confirmed_nav'] = str(latest.get('value', ''))
                result['confirmed_change'] = str(latest.get('change', ''))
                result['jzrq'] = today
                result['confirmed_date'] = today
                # 获取前一天净值作为"昨日净值"
                if len(history_data) >= 2:
                    previous = history_data[-2]
                    result['dwjz'] = str(previous.get('value', result.get('dwjz')))
                    result['base_date'] = previous.get('date', result.get('base_date'))
    except Exception as e:
        # 静默失败，保持估算值
        # 可以在这里添加日志记录：print(f"查询历史净值失败 {code}: {e}")
        pass

    return _sync_confirmation_fields(result)


def get_fund_estimate(fund_code):
    code = str(fund_code).zfill(6)
    valuation = get_fund_valuation(code)
    fallback_name = (valuation or {}).get('name') or get_fund_name_by_code(code) or code
    today = china_now().strftime('%Y-%m-%d')
    if valuation and valuation.get('display_date') == today:
        result = _build_basic_payload(
            code=valuation.get('code') or code,
            name=valuation.get('name') or fallback_name,
            gsz=valuation.get('gsz'),
            gszzl=valuation.get('gszzl'),
            gztime=valuation.get('gztime'),
            dwjz=valuation.get('dwjz'),
            jzrq=valuation.get('jzrq'),
            success=True,
            display_date=valuation.get('display_date'),
            confirmed_date=valuation.get('confirmed_date'),
            base_date=valuation.get('base_date'),
            quote_source=valuation.get('quote_source') or 'direct_valuation',
        )
        return _enrich_confirmed_nav(code, result)

    snapshot = get_pingzhongdata_snapshot(code)
    if valuation:
        direct_source_message = f'直接估值尚未更新至 {today}'
        fallback_name = valuation.get('name') or fallback_name
    else:
        direct_source_message = '新浪和东方财富直接估值暂无数据'

    holdings_estimate = _build_holdings_estimate(
        code,
        fallback_name,
        snapshot,
        direct_source_message,
    )
    if holdings_estimate:
        return holdings_estimate
    return _load_pingzhong_fallback(
        code,
        fallback_name,
        direct_source_message,
        snapshot=snapshot,
    )


def _fetch_and_cache_basic(code):
    norm_code = str(code).zfill(6)
    result = get_fund_estimate(norm_code)
    if result:
        cache_set('basic', norm_code, result)
        set_basic_quote(norm_code, result)
    return result


def _fetch_cache_and_release_basic_lock(code, lock_token):
    try:
        return _fetch_and_cache_basic(code)
    finally:
        release_basic_quote_refresh_lock(code, lock_token)


def _wait_for_remote_basic_refresh(code, wait_seconds=BASIC_WAIT_FOR_REMOTE_REFRESH_SECONDS):
    norm_code = str(code).zfill(6)
    deadline = time.time() + max(wait_seconds, BASIC_WAIT_STEP_SECONDS)
    while time.time() < deadline:
        fresh = get_basic_quote(norm_code, TTL_BASIC_SECONDS)
        if fresh:
            cache_set('basic', norm_code, fresh)
            return fresh
        time.sleep(BASIC_WAIT_STEP_SECONDS)

    stale = get_stale_basic_quote(norm_code)
    if stale:
        cache_set('basic', norm_code, stale)
    return stale


def _resolved_future(result):
    future = Future()
    future.set_result(result)
    return future


def submit_basic_refresh(code, executor):
    norm_code = str(code).zfill(6)
    future = get_inflight_basic(norm_code)
    if future:
        increment_metric('cache.basic.inflight_reuse')
        return future

    lock_token = acquire_basic_quote_refresh_lock(norm_code, BASIC_REFRESH_LOCK_SECONDS)
    if lock_token:
        increment_metric('cache.basic.refresh_owner')
        return set_inflight_basic(
            norm_code,
            executor.submit(_fetch_cache_and_release_basic_lock, norm_code, lock_token)
        )

    fresh = get_basic_quote(norm_code, TTL_BASIC_SECONDS)
    if fresh:
        increment_metric('cache.basic.redis_waiter_hit')
        cache_set('basic', norm_code, fresh)
        return _resolved_future(fresh)

    increment_metric('cache.basic.refresh_waiter')
    return set_inflight_basic(
        norm_code,
        executor.submit(_wait_for_remote_basic_refresh, norm_code)
    )


def build_timeout_placeholder(code):
    return _build_basic_payload(
        code=code,
        name=code,
        gsz='-',
        gszzl='-',
        gztime='-',
        dwjz='-',
        jzrq='-',
        success=False,
        message='请求超时，请稍后刷新',
        display_date='-',
        confirmed_date='-',
        base_date='-',
    )


def load_basic_for_detail(code, request_timeout=DETAIL_REQUEST_TIMEOUT_SECONDS):
    basic = cache_get('basic', code, TTL_BASIC_SECONDS)
    if basic:
        increment_metric('cache.basic.local_hit')
        return basic
    redis_basic = get_basic_quote(code, TTL_BASIC_SECONDS)
    if redis_basic:
        increment_metric('cache.basic.redis_hit')
        cache_set('basic', code, redis_basic)
        return redis_basic
    stale_basic = cache_get_stale('basic', code)
    if not stale_basic:
        stale_basic = get_stale_basic_quote(code)
        if stale_basic:
            cache_set('basic', code, stale_basic)
    if stale_basic:
        increment_metric('cache.basic.stale_hit')
    future = submit_basic_refresh(code, FUNDS_EXECUTOR)
    done, _ = futures_wait([future], timeout=request_timeout)
    if done:
        try:
            result = future.result()
            if result:
                return result
        except Exception:
            pass
    return stale_basic if stale_basic else build_timeout_placeholder(code)


def fetch_funds_parallel(codes, request_timeout=15):
    norm_codes = [str(c).zfill(6) for c in codes]
    results_map = {}
    to_fetch = []
    for code in norm_codes:
        fresh = cache_get('basic', code, TTL_BASIC_SECONDS)
        if fresh:
            increment_metric('cache.basic.local_hit')
            results_map[code] = fresh
            continue

        redis_fresh = get_basic_quote(code, TTL_BASIC_SECONDS)
        if redis_fresh:
            increment_metric('cache.basic.redis_hit')
            cache_set('basic', code, redis_fresh)
            results_map[code] = redis_fresh
            continue

        stale = cache_get_stale('basic', code) or get_stale_basic_quote(code)
        if stale:
            increment_metric('cache.basic.stale_hit')
            cache_set('basic', code, stale)
        if stale and _should_use_stale_basic(stale):
            results_map[code] = stale
            submit_basic_refresh(code, BG_REFRESH_EXECUTOR)
        else:
            to_fetch.append(code)
    if to_fetch:
        # 分批提交，避免单次关注基金数过大时线程池排队和长时间阻塞
        chunk_size = 50
        deadline = time.time() + max(float(request_timeout or 0), 0.1)
        for offset in range(0, len(to_fetch), chunk_size):
            chunk = to_fetch[offset: offset + chunk_size]
            remaining = max(deadline - time.time(), 0.0)
            if remaining <= 0:
                remaining = 0.01
            future_to_code = {submit_basic_refresh(code, FUNDS_EXECUTOR): code for code in chunk}
            done, not_done = futures_wait(future_to_code.keys(), timeout=remaining)
            for future in done:
                code = future_to_code[future]
                try:
                    result = future.result()
                    if result:
                        results_map[code] = result
                except Exception:
                    pass
            for future in not_done:
                code = future_to_code[future]
                stale = cache_get_stale('basic', code)
                results_map[code] = stale if _should_use_stale_basic(stale) else build_timeout_placeholder(code)
    results = [results_map.get(code) for code in norm_codes]
    record_intraday_snapshots(results)
    return results


def _background_refresh_loop():
    while True:
        time.sleep(50)
        cache_prune('basic', TTL_BASIC_SECONDS * 10)
        cache_prune('detail', TTL_DETAIL_SECONDS * 10)
        cache_prune('holdings', TTL_HOLDINGS_SECONDS * 10)
        cache_prune('history', TTL_HISTORY_SECONDS * 10)
        cache_prune('pingzhong', TTL_PINGZHONG_SECONDS * 10)
        cache_prune('related_etf', TTL_RELATED_ETF_SECONDS * 4)
        prune_watched_codes()
        codes = get_watched_codes()
        if is_intraday_collection_open():
            codes = list(dict.fromkeys([*codes, *get_active_position_fund_codes()]))
        if not codes:
            continue
        futures = [
            submit_basic_refresh(code, BG_REFRESH_EXECUTOR)
            for code in codes
            if not (cache_get_age('basic', code) is not None and cache_get_age('basic', code) < max(TTL_BASIC_SECONDS - 15, 1))
        ]
        if futures:
            futures_wait(futures, timeout=15)
            record_intraday_snapshots([
                cache_get('basic', code, TTL_BASIC_SECONDS) or get_stale_basic_quote(code)
                for code in codes
            ])


def start_background_refresh_thread():
    global _BG_THREAD
    with _BG_THREAD_LOCK:
        if _BG_THREAD and _BG_THREAD.is_alive():
            return
        _BG_THREAD = threading.Thread(target=_background_refresh_loop, daemon=True, name='fund-bg-refresh')
        _BG_THREAD.start()
