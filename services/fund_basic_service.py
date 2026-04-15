import json
import re
import threading
import time
from concurrent.futures import wait as futures_wait
from datetime import datetime

from core.cache import cache_get, cache_get_age, cache_get_stale, cache_prune, cache_set
from core.http import http_get
from core.runtime import BG_REFRESH_EXECUTOR, FUNDS_EXECUTOR, get_inflight_basic, get_watched_codes, prune_watched_codes, set_inflight_basic

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

LINK_ETF_MANUAL_MAP = {
    '015283': ('513580', '华安恒生科技(QDII-ETF)'),
    '015282': ('513580', '华安恒生科技(QDII-ETF)'),
    '023833': ('561570', '华泰柏瑞中证油气产业ETF'),
}

_FUND_LIST_CACHE = None
_FUND_LIST_CACHE_LOCK = threading.Lock()
_BG_THREAD = None
_BG_THREAD_LOCK = threading.Lock()


def _build_basic_payload(code, name, gsz='-', gszzl='-', gztime='-', dwjz='-', jzrq='-', success=False, message='', nav_confirmed=False, confirmed_nav='', confirmed_change=''):
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
            _FUND_LIST_CACHE = {
                'df': df,
                'code_col': code_col,
                'name_col': name_col,
                'name_map': dict(zip(df[code_col], df[name_col].astype(str))),
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
                return datetime.fromtimestamp(float(item.get('x')) / 1000).strftime('%Y-%m-%d')
            except Exception:
                return ''

        result = {
            'code': extract_string('fS_code') or code,
            'name': extract_string('fS_name'),
            'networth': networth,
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
    return _build_basic_payload(
        code=code,
        name=snapshot.get('name') if snapshot and snapshot.get('name') else fallback_name,
        gsz=snapshot.get('latest_value', '-') if snapshot else '-',
        gszzl=snapshot.get('latest_change', '-') if snapshot else '-',
        gztime=latest_date or '-',
        dwjz=snapshot.get('previous_value', '-') if snapshot else '-',
        jzrq=snapshot.get('previous_date', latest_date) if snapshot else '-',
        success=False,
        message=message,
    )


def _load_pingzhong_fallback(code, fallback_name, message):
    snapshot = get_pingzhongdata_snapshot(code)
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
    )


def _is_trading_hours():
    """判断当前是否在交易时段（周一到周五 9:30-11:30, 13:00-15:00）"""
    now = datetime.now()
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


def _enrich_confirmed_nav(code, result):
    today = datetime.now().strftime('%Y-%m-%d')
    fund_name = result.get('name', '')

    # 判断是否需要查询历史接口
    if not _should_check_confirmed_nav(fund_name):
        # 交易时段，使用估算值
        return result

    # 非交易时段或 QDII 基金，查询历史接口
    try:
        from services.fund_detail_service import get_fund_networth_history

        history_result = get_fund_networth_history(code, days=2)
        if history_result.get('success') and history_result.get('data'):
            history_data = history_result['data']
            if not history_data:
                return result

            latest = history_data[-1]

            # 如果最新记录是今天，说明官方净值已公布
            if latest and latest.get('date') == today:
                result['nav_confirmed'] = True
                result['confirmed_nav'] = str(latest.get('value', ''))
                result['confirmed_change'] = str(latest.get('change', ''))
                result['jzrq'] = today
                # 获取前一天净值作为"昨日净值"
                if len(history_data) >= 2:
                    previous = history_data[-2]
                    result['dwjz'] = str(previous.get('value', result.get('dwjz')))
    except Exception as e:
        # 静默失败，保持估算值
        # 可以在这里添加日志记录：print(f"查询历史净值失败 {code}: {e}")
        pass

    return result


def get_fund_estimate(fund_code):
    code = str(fund_code).zfill(6)
    fallback_name = get_fund_name_by_code(code) or code
    try:
        response = http_get(
            f"http://fundgz.1234567.com.cn/js/{code}.js?rt={int(time.time() * 1000)}",
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Referer': 'http://fund.eastmoney.com/'},
            timeout=3,
        )
        if response.status_code != 200:
            return _load_pingzhong_fallback(code, fallback_name, '实时估值接口不可用')
        match = re.search(r'({.*})', response.text)
        if not match:
            return _load_pingzhong_fallback(code, fallback_name, '实时估值返回异常')
        data = json.loads(match.group(1))
        result = _build_basic_payload(
            code=data.get('fundcode') or code,
            name=data.get('name') or fallback_name,
            gsz=data.get('gsz'),
            gszzl=data.get('gszzl'),
            gztime=data.get('gztime'),
            dwjz=data.get('dwjz'),
            jzrq=data.get('jzrq'),
            success=True,
        )
        return _enrich_confirmed_nav(code, result)
    except Exception as e:
        return _load_pingzhong_fallback(code, fallback_name, f'实时估值请求失败: {e}')


def _fetch_and_cache_basic(code):
    norm_code = str(code).zfill(6)
    result = get_fund_estimate(norm_code)
    if result:
        cache_set('basic', norm_code, result)
    return result


def submit_basic_refresh(code, executor):
    future = get_inflight_basic(code)
    if future:
        return future
    return set_inflight_basic(code, executor.submit(_fetch_and_cache_basic, str(code).zfill(6)))


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
    )


def load_basic_for_detail(code, request_timeout=DETAIL_REQUEST_TIMEOUT_SECONDS):
    basic = cache_get('basic', code, TTL_BASIC_SECONDS)
    if basic:
        return basic
    stale_basic = cache_get_stale('basic', code)
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


def fetch_funds_parallel(codes, request_timeout=8):
    norm_codes = [str(c).zfill(6) for c in codes]
    results_map = {}
    to_fetch = []
    for code in norm_codes:
        fresh = cache_get('basic', code, TTL_BASIC_SECONDS)
        if fresh:
            results_map[code] = fresh
        else:
            stale = cache_get_stale('basic', code)
            if stale:
                results_map[code] = stale
                submit_basic_refresh(code, BG_REFRESH_EXECUTOR)
            else:
                to_fetch.append(code)
    if to_fetch:
        future_to_code = {submit_basic_refresh(code, FUNDS_EXECUTOR): code for code in to_fetch}
        done, not_done = futures_wait(future_to_code.keys(), timeout=request_timeout)
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
            results_map[code] = stale if stale else build_timeout_placeholder(code)
    return [results_map.get(code) for code in norm_codes]


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
        if not codes:
            continue
        futures = [
            submit_basic_refresh(code, BG_REFRESH_EXECUTOR)
            for code in codes
            if not (cache_get_age('basic', code) is not None and cache_get_age('basic', code) < max(TTL_BASIC_SECONDS - 15, 1))
        ]
        if futures:
            futures_wait(futures, timeout=15)


def start_background_refresh_thread():
    global _BG_THREAD
    with _BG_THREAD_LOCK:
        if _BG_THREAD and _BG_THREAD.is_alive():
            return
        _BG_THREAD = threading.Thread(target=_background_refresh_loop, daemon=True, name='fund-bg-refresh')
        _BG_THREAD.start()
