import re
import threading
import time
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from core.cache import cache_get, cache_get_stale, cache_set
from core.http import http_get
from core.perf_metrics import increment_metric
from core.runtime import DETAIL_EXECUTOR, register_watched_codes
from services.history_cache_service import (
    acquire_history_refresh_lock,
    get_fund_history as get_cached_fund_history,
    get_stale_fund_history,
    release_history_refresh_lock,
    set_fund_history,
)
from services.detail_cache_service import (
    acquire_detail_refresh_lock,
    get_fund_detail as get_cached_fund_detail,
    get_stale_fund_detail,
    release_detail_refresh_lock,
    set_fund_detail,
)
from services.fund_basic_service import (
    LINK_ETF_MANUAL_MAP,
    TTL_DETAIL_SECONDS,
    TTL_HOLDINGS_SECONDS,
    TTL_HISTORY_SECONDS,
    TTL_RELATED_ETF_SECONDS,
    get_cached_fund_list,
    get_fund_estimate,
    get_fund_name_by_code,
    get_pingzhongdata_snapshot,
    load_basic_for_detail,
)
from services.fund_quote_service import get_realtime_stock_quotes, quote_name_matches

try:
    import akshare as ak
except Exception:
    ak = None


_INFLIGHT_DETAIL = {}
_INFLIGHT_DETAIL_LOCK = threading.Lock()
DETAIL_REFRESH_LOCK_SECONDS = 10
DETAIL_WAIT_FOR_REMOTE_REFRESH_SECONDS = 3
DETAIL_WAIT_STEP_SECONDS = 0.1
HISTORY_REFRESH_LOCK_SECONDS = 10
HISTORY_WAIT_FOR_REMOTE_REFRESH_SECONDS = 3
HISTORY_WAIT_STEP_SECONDS = 0.1


def _clean_name(name):
    text = str(name or '')
    for token in ['(', ')', '（', '）', '-', ' ', '\t']:
        text = text.replace(token, '')
    return text


def _is_link_fund_name(name):
    return '联接' in str(name or '')


def _first_col(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _parse_percent_number(v):
    m = re.search(r'-?\d+(\.\d+)?', str(v or ''))
    if not m:
        return 0.0
    try:
        return float(m.group(0))
    except Exception:
        return 0.0


def _fmt_percent_text(v):
    s = str(v or '').strip()
    if not s:
        return '-'
    if s.endswith('%'):
        return s
    m = re.search(r'-?\d+(\.\d+)?', s)
    if not m:
        return s
    try:
        return f"{float(m.group(0)):.2f}%"
    except Exception:
        return s


def _is_meaningful_holdings(holdings):
    if not holdings or len(holdings) < 5:
        return False
    valid = 0
    positive = 0
    for item in holdings:
        pct = _parse_percent_number(item.get('pct'))
        if pct >= 0:
            valid += 1
        if pct > 0:
            positive += 1
    return valid > 0 and positive > 0


def _get_related_etf_from_detail_page(fund_code):
    code = str(fund_code).zfill(6)
    cached = cache_get('related_etf', code, TTL_RELATED_ETF_SECONDS)
    if cached is not None:
        return cached
    result = (None, None)
    try:
        response = http_get(
            f'https://fund.eastmoney.com/{code}.html',
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Referer': 'https://fund.eastmoney.com/'},
            timeout=5,
        )
        if response.status_code == 200 and response.content:
            soup = BeautifulSoup(response.content.decode('utf-8', errors='ignore'), 'html.parser')
            for a in soup.find_all('a', href=True):
                if '查看相关ETF' not in a.get_text(strip=True):
                    continue
                match = re.search(r'fund\.eastmoney\.com/(\d{6})\.html', a.get('href', ''), re.I)
                if match:
                    etf_code = match.group(1)
                    result = (etf_code, get_fund_name_by_code(etf_code))
                    break
    except Exception:
        result = (None, None)
    cache_set('related_etf', code, result)
    return result


def _find_associated_etf(link_fund_code, link_fund_name=''):
    code = str(link_fund_code).zfill(6)
    detail_etf = _get_related_etf_from_detail_page(code)
    if detail_etf and detail_etf[0]:
        return detail_etf
    cache = get_cached_fund_list()
    if not cache:
        return LINK_ETF_MANUAL_MAP.get(code, (None, None))
    df = cache['df']
    code_col = cache['code_col']
    name_col = cache['name_col']
    term = _clean_name(link_fund_name)
    for token in ['发起式', '联接A', '联接C', '联接', 'QDII', 'A类', 'C类', 'I类', '份额', 'A', 'C', 'I']:
        term = term.replace(token, '')
    if not term:
        return None, None
    try:
        matches = df[(df['clean_name'].str.contains(term, regex=False)) & (~df[name_col].astype(str).str.contains('联接', regex=False))]
        if matches.empty:
            return None, None
        for _, row in matches.iterrows():
            etf_code = str(row[code_col]).zfill(6)
            if etf_code.startswith(('51', '58', '15', '16', '56')):
                return etf_code, str(row[name_col])
        row = matches.iloc[0]
        return str(row[code_col]).zfill(6), str(row[name_col])
    except Exception:
        return LINK_ETF_MANUAL_MAP.get(code, (None, None))


def _get_holdings_via_akshare_once(fund_code):
    if ak is None:
        return {'success': False, 'holdings': [], 'date': '', 'error': 'akshare not installed'}
    try:
        df = ak.fund_portfolio_hold_em(symbol=str(fund_code).zfill(6))
        if df is None or df.empty:
            return {'success': False, 'holdings': [], 'date': ''}
        code_col = _first_col(df, ['股票代码', '证券代码', '代码'])
        name_col = _first_col(df, ['股票名称', '证券名称', '名称'])
        pct_col = _first_col(df, ['占净值比例', '持仓占比'])
        delta_col = _first_col(df, ['较上期变化', '较上期'])
        date_col = _first_col(df, ['季度', '报告期', '截止日期'])
        if not code_col or not name_col or not pct_col:
            return {'success': False, 'holdings': [], 'date': ''}
        holdings = []
        seen = set()
        for _, row in df.iterrows():
            stock_code = re.sub(r'\D', '', str(row.get(code_col, '')))
            if len(stock_code) < 5:
                continue
            stock_code = stock_code.zfill(6)[-6:]
            if stock_code in seen:
                continue
            seen.add(stock_code)
            holdings.append({'code': stock_code, 'name': str(row.get(name_col, '')).strip(), 'price': '-', 'change_pct': '-', 'pct': _fmt_percent_text(row.get(pct_col, '-')), 'delta': _fmt_percent_text(row.get(delta_col, '-')) if delta_col else '-'})
            if len(holdings) >= 10:
                break
        report_date = str(df.iloc[0].get(date_col, '')).strip() if date_col and not df.empty else ''
        if not holdings:
            return {'success': False, 'holdings': [], 'date': report_date}
        quote_map = get_realtime_stock_quotes(holdings)
        for item in holdings:
            q = quote_map.get(item['code'])
            if q and quote_name_matches(item.get('name', ''), q.get('name', '')):
                item['price'] = q.get('price', '-')
                item['change_pct'] = q.get('change_pct', '-')
        return {'success': True, 'holdings': holdings, 'date': report_date}
    except Exception as e:
        return {'success': False, 'holdings': [], 'date': '', 'error': str(e)}


def _get_holdings_via_akshare_with_link_fallback(fund_code):
    code = str(fund_code).zfill(6)
    res = _get_holdings_via_akshare_once(code)
    if res.get('success') and res.get('holdings'):
        first = res['holdings'][0]
        if ('ETF' in str(first.get('name') or '').upper() or _parse_percent_number(first.get('pct')) >= 80.0) and re.match(r'^\d{6}$', str(first.get('code', ''))):
            nested = _get_holdings_via_akshare_once(first.get('code'))
            if nested.get('success') and nested.get('holdings'):
                return nested
        return res
    link_name = get_fund_name_by_code(code)
    if not _is_link_fund_name(link_name) and code not in LINK_ETF_MANUAL_MAP:
        return res
    etf_code, _ = _find_associated_etf(code, link_name)
    if etf_code and etf_code != code:
        nested = _get_holdings_via_akshare_once(etf_code)
        if nested.get('success') and nested.get('holdings'):
            return nested
        nested = get_fund_holdings(etf_code)
        if nested.get('success') and nested.get('holdings'):
            return nested
    return res


def get_fund_holdings(fund_code):
    try:
        response = http_get(
            f"http://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={fund_code}&topline=10&year=&month=&rt={int(__import__('time').time()*1000)}",
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Referer': f'http://fundf10.eastmoney.com/jjcc_{fund_code}.html'},
            timeout=3,
        )
        if response.status_code != 200:
            return {'success': False, 'holdings': [], 'date': ''}
        soup = BeautifulSoup(response.text, 'html.parser')
        holdings = []
        fund_date = soup.find('font', class_='px12').get_text(strip=True) if soup.find('font', class_='px12') else ''
        seen_codes = set()
        for table in soup.select('table.tzxq'):
            header_texts = [h.get_text(' ', strip=True) for h in table.select('thead tr th')]
            if not header_texts:
                continue
            def find_col(keywords):
                for idx, text in enumerate(header_texts):
                    if any(k in text for k in keywords):
                        return idx
                return -1
            code_idx = find_col(['代码']); name_idx = find_col(['名称']); pct_idx = find_col(['占净值比例', '持仓占比']); delta_idx = find_col(['较上期', '较上期变化'])
            if code_idx < 0 or name_idx < 0 or pct_idx < 0:
                if len(header_texts) >= 9:
                    code_idx, name_idx, pct_idx, delta_idx = 1, 2, 6, -1
                elif len(header_texts) >= 7:
                    code_idx, name_idx, pct_idx, delta_idx = 1, 2, 4, -1
            if code_idx < 0 or name_idx < 0 or pct_idx < 0:
                continue
            for row in table.select('tbody tr'):
                cols = row.find_all('td')
                if len(cols) <= max(code_idx, name_idx, pct_idx):
                    continue
                code_cell = cols[code_idx]
                code_text = code_cell.get_text(strip=True).upper()
                code_link = code_cell.find('a')
                href = code_link.get('href', '') if code_link else ''
                href_match = re.search(r'/r/(\d+)\.([A-Z0-9]+)', href, re.I)
                market = {'116': 'hk', '105': 'us', '106': 'us'}.get(href_match.group(1), '') if href_match else ''
                stock_code = href_match.group(2).upper() if href_match else (re.search(r'[A-Z]{1,10}|\d{5,6}', code_text, re.I).group(0).upper() if re.search(r'[A-Z]{1,10}|\d{5,6}', code_text, re.I) else '')
                if not cols[name_idx].get_text(strip=True) or not cols[pct_idx].get_text(strip=True) or not stock_code or stock_code in seen_codes:
                    continue
                seen_codes.add(stock_code)
                holdings.append({'code': stock_code, 'name': cols[name_idx].get_text(strip=True), 'price': '-', 'change_pct': '-', 'pct': cols[pct_idx].get_text(strip=True), 'delta': cols[delta_idx].get_text(strip=True) if (delta_idx >= 0 and delta_idx < len(cols)) else '-', 'market': market})
                if len(holdings) >= 10:
                    break
            if holdings:
                break
        holdings = holdings[:10]
        if holdings:
            quote_map = get_realtime_stock_quotes(holdings)
            hk_fallback_items = []
            for item in holdings:
                q = quote_map.get(item['code'])
                if q and quote_name_matches(item.get('name', ''), q.get('name', '')):
                    item['price'] = q.get('price', '-')
                    item['change_pct'] = q.get('change_pct', '-')
                else:
                    hk_fallback_items.append({'code': item['code'], 'name': item.get('name', ''), 'market': 'hk'})
            if hk_fallback_items:
                hk_quote_map = get_realtime_stock_quotes(hk_fallback_items)
                for item in holdings:
                    if item.get('price') not in (None, '', '-'):
                        continue
                    hk_q = hk_quote_map.get(item['code'])
                    if hk_q and hk_q.get('price') not in (None, '', '-'):
                        item['price'] = hk_q.get('price', '-')
                        item['change_pct'] = hk_q.get('change_pct', '-')
            for item in holdings:
                item.pop('market', None)
        code = str(fund_code).zfill(6)
        if holdings and code not in LINK_ETF_MANUAL_MAP and _is_meaningful_holdings(holdings):
            return {'success': True, 'holdings': holdings, 'date': fund_date}
        ak_res = _get_holdings_via_akshare_with_link_fallback(code)
        if ak_res.get('success') and ak_res.get('holdings'):
            return ak_res
        if holdings:
            return {'success': True, 'holdings': holdings, 'date': fund_date}
        return {'success': False, 'holdings': [], 'date': fund_date}
    except Exception as e:
        ak_res = _get_holdings_via_akshare_with_link_fallback(str(fund_code).zfill(6))
        if ak_res.get('success') and ak_res.get('holdings'):
            return ak_res
        return {'success': False, 'holdings': [], 'error': str(e)}


def _fetch_fund_networth_history(code, days, history_cache_key):
    code = str(code).zfill(6)
    days = max(30, min(int(days or 30), 365))
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)
    start_date_text = start_date.strftime('%Y-%m-%d')
    end_date_text = end_date.strftime('%Y-%m-%d')
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://fund.eastmoney.com/',
        }
        result = []
        seen_dates = set()
        page_index = 1
        page_size = 100
        max_pages = 30

        while page_index <= max_pages:
            response = http_get(
                f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex={page_index}&pageSize={page_size}&startDate={start_date_text}&endDate={end_date_text}",
                headers=headers,
                timeout=3,
            )
            if response.status_code != 200:
                return {'success': False, 'data': []}

            payload = response.json()
            data_block = payload.get('Data') or {}
            page_items = data_block.get('LSJZList') or []
            if not page_items:
                break

            for item in page_items:
                try:
                    item_date = item.get('FSRQ', '')
                    if not item_date or item_date in seen_dates:
                        continue
                    seen_dates.add(item_date)
                    result.append({
                        'date': item_date,
                        'value': float(item.get('DWJZ', 0)),
                        'change': item.get('JZZZL', '0'),
                    })
                except Exception:
                    continue

            total_count = int(payload.get('TotalCount') or 0)
            actual_page_size = len(page_items)
            if total_count > 0 and len(result) >= total_count:
                break
            if actual_page_size == 0:
                break
            page_index += 1

        result.sort(key=lambda item: item.get('date', ''))
        if result:
            filtered = [
                item for item in result
                if start_date_text <= str(item.get('date', '')) <= end_date_text
            ]
            payload = {'success': True, 'data': filtered}
            cache_set('history', history_cache_key, payload)
            set_fund_history(code, days, payload)
            return payload
    except Exception as e:
        api_error = str(e)
    try:
        snapshot = get_pingzhongdata_snapshot(code)
        result = []
        for item in (snapshot.get('networth', []) if snapshot else []):
            if not isinstance(item, dict):
                continue
            try:
                item_date = datetime.fromtimestamp(float(item.get('x')) / 1000).date()
                if item_date < start_date or item_date > end_date:
                    continue
                result.append({'date': item_date.strftime('%Y-%m-%d'), 'value': float(item.get('y')), 'change': str(item.get('equityReturn', '0'))})
            except Exception:
                continue
        result.sort(key=lambda item: item.get('date', ''))
        filtered = [
            item for item in result
            if start_date_text <= str(item.get('date', '')) <= end_date_text
        ]
        payload = {'success': bool(filtered), 'data': filtered}
        if filtered:
            cache_set('history', history_cache_key, payload)
            set_fund_history(code, days, payload)
        return payload
    except Exception as e:
        return {'success': False, 'data': [], 'error': locals().get('api_error') or str(e)}


def _fetch_history_and_release_lock(code, days, history_cache_key, lock_token):
    try:
        return _fetch_fund_networth_history(code, days, history_cache_key)
    finally:
        release_history_refresh_lock(code, days, lock_token)


def _wait_for_remote_history_refresh(code, days, history_cache_key, wait_seconds=HISTORY_WAIT_FOR_REMOTE_REFRESH_SECONDS):
    deadline = time.time() + max(wait_seconds, HISTORY_WAIT_STEP_SECONDS)
    while time.time() < deadline:
        fresh = get_cached_fund_history(code, days, TTL_HISTORY_SECONDS)
        if fresh:
            cache_set('history', history_cache_key, fresh)
            return fresh
        time.sleep(HISTORY_WAIT_STEP_SECONDS)

    stale = get_stale_fund_history(code, days) or cache_get_stale('history', history_cache_key)
    if stale:
        increment_metric('cache.history.stale_hit')
        cache_set('history', history_cache_key, stale)
    return stale or {'success': False, 'data': []}


def get_fund_networth_history(fund_code, days=30):
    code = str(fund_code).zfill(6)
    days = max(30, min(int(days or 30), 365))
    history_cache_key = f'{code}:{days}'

    local_cached = cache_get('history', history_cache_key, TTL_HISTORY_SECONDS)
    if local_cached:
        increment_metric('cache.history.local_hit')
        return local_cached

    redis_cached = get_cached_fund_history(code, days, TTL_HISTORY_SECONDS)
    if redis_cached:
        increment_metric('cache.history.redis_hit')
        cache_set('history', history_cache_key, redis_cached)
        return redis_cached

    lock_token = acquire_history_refresh_lock(code, days, HISTORY_REFRESH_LOCK_SECONDS)
    if lock_token:
        increment_metric('cache.history.refresh_owner')
        return _fetch_history_and_release_lock(code, days, history_cache_key, lock_token)

    increment_metric('cache.history.refresh_waiter')
    return _wait_for_remote_history_refresh(code, days, history_cache_key)


def build_intraday_from_basic(estimate):
    try:
        if not estimate:
            return {'success': False, 'data': []}
        gsz = float(estimate.get('gsz') or 0)
        if gsz <= 0:
            return {'success': False, 'data': []}
        if not estimate.get('success'):
            return {'success': True, 'data': [{'time': '09:30', 'value': round(gsz, 4)}, {'time': '15:00', 'value': round(gsz, 4)}]}
        gztime = estimate.get('gztime') or ''
        if not gztime:
            return {'success': False, 'data': []}
        minute = gztime.split(' ')[1][:5] if ' ' in gztime else '09:30'
        return {'success': True, 'data': [{'time': minute, 'value': round(gsz, 4)}]}
    except Exception as e:
        return {'success': False, 'data': [], 'error': str(e)}


def get_fund_intraday(fund_code):
    return build_intraday_from_basic(get_fund_estimate(fund_code))


def _build_fund_details(code):
    basic = load_basic_for_detail(code)

    def load_holdings():
        cached = cache_get('holdings', code, TTL_HOLDINGS_SECONDS)
        if cached:
            return cached
        res = get_fund_holdings(code)
        if res and res.get('success'):
            cache_set('holdings', code, res)
            return res
        return cache_get_stale('holdings', code) or res

    def load_history():
        history_cache_key = f'{code}:30'
        cached = cache_get('history', history_cache_key, TTL_HISTORY_SECONDS)
        if cached:
            return cached
        res = get_fund_networth_history(code, days=30)
        if res and res.get('success'):
            cache_set('history', history_cache_key, res)
            return res
        return cache_get_stale('history', history_cache_key) or res

    holdings_future = DETAIL_EXECUTOR.submit(load_holdings)
    history_future = DETAIL_EXECUTOR.submit(load_history)
    holdings = holdings_future.result()
    history = history_future.result()
    result = {
        'basic': basic if basic else {'success': False},
        'holdings': holdings if holdings else {'success': False, 'holdings': []},
        'history': history if history else {'success': False, 'data': []},
        'intraday': build_intraday_from_basic(basic),
    }
    cache_set('detail', code, result)
    set_fund_detail(code, result)
    return result


def _build_details_and_release_lock(code, lock_token):
    try:
        return _build_fund_details(code)
    finally:
        release_detail_refresh_lock(code, lock_token)


def _wait_for_remote_detail_refresh(code, wait_seconds=DETAIL_WAIT_FOR_REMOTE_REFRESH_SECONDS):
    deadline = time.time() + max(wait_seconds, DETAIL_WAIT_STEP_SECONDS)
    while time.time() < deadline:
        fresh = get_cached_fund_detail(code, TTL_DETAIL_SECONDS)
        if fresh:
            cache_set('detail', code, fresh)
            return fresh
        time.sleep(DETAIL_WAIT_STEP_SECONDS)

    stale = get_stale_fund_detail(code) or cache_get_stale('detail', code)
    if stale:
        increment_metric('cache.detail.stale_hit')
        cache_set('detail', code, stale)
    return stale


def get_fund_details(fund_code):
    code = str(fund_code).zfill(6)
    register_watched_codes([code])
    cached_detail = cache_get('detail', code, TTL_DETAIL_SECONDS)
    if cached_detail:
        increment_metric('cache.detail.local_hit')
        return cached_detail
    redis_detail = get_cached_fund_detail(code, TTL_DETAIL_SECONDS)
    if redis_detail:
        increment_metric('cache.detail.redis_hit')
        cache_set('detail', code, redis_detail)
        return redis_detail
    with _INFLIGHT_DETAIL_LOCK:
        future = _INFLIGHT_DETAIL.get(code)
        if future is None or future.done():
            lock_token = acquire_detail_refresh_lock(code, DETAIL_REFRESH_LOCK_SECONDS)
            if lock_token:
                increment_metric('cache.detail.refresh_owner')
                future = DETAIL_EXECUTOR.submit(_build_details_and_release_lock, code, lock_token)
            else:
                increment_metric('cache.detail.refresh_waiter')
                future = DETAIL_EXECUTOR.submit(_wait_for_remote_detail_refresh, code)
            _INFLIGHT_DETAIL[code] = future

            def _cleanup(done_future, code_key=code):
                with _INFLIGHT_DETAIL_LOCK:
                    current = _INFLIGHT_DETAIL.get(code_key)
                    if current is done_future:
                        _INFLIGHT_DETAIL.pop(code_key, None)

            future.add_done_callback(_cleanup)

    try:
        result = future.result()
        if result:
            return result
    except Exception:
        pass

    stale_detail = cache_get_stale('detail', code) or get_stale_fund_detail(code)
    if stale_detail:
        increment_metric('cache.detail.stale_hit')
        cache_set('detail', code, stale_detail)
        return stale_detail
    raise RuntimeError(f'failed to load fund detail for {code}')
