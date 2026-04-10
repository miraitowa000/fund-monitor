import json
import re
import threading
import time
import unicodedata
from datetime import datetime
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, send_from_directory
try:
    import akshare as ak
except Exception:
    ak = None

app = Flask(__name__, static_folder='static', template_folder='templates')

# Avoid conflict with Vue template syntax
app.jinja_env.variable_start_string = '{%{'
app.jinja_env.variable_end_string = '}%}'

_FUND_LIST_CACHE = None
_FUND_LIST_CACHE_LOCK = threading.Lock()
_API_CACHE = {
    'basic': {},
    'holdings': {},
    'history': {},
    'detail': {},
    'pingzhong': {},
    'related_etf': {},
}
_API_CACHE_LOCK = threading.Lock()
_FUNDS_EXECUTOR = ThreadPoolExecutor(max_workers=4)
_DETAIL_EXECUTOR = ThreadPoolExecutor(max_workers=2)
_HTTP = requests.Session()

TTL_BASIC_SECONDS = 20
TTL_HOLDINGS_SECONDS = 180
TTL_HISTORY_SECONDS = 600
TTL_DETAIL_SECONDS = 20
TTL_PINGZHONG_SECONDS = 180
TTL_RELATED_ETF_SECONDS = 1800

LINK_ETF_MANUAL_MAP = {
    '015283': ('513580', '华安恒生科技(QDII-ETF)'),
    '015282': ('513580', '华安恒生科技(QDII-ETF)'),
    '023833': ('561570', '华泰柏瑞中证油气产业ETF'),
}


def _http_get(url, headers=None, timeout=3):
    return _HTTP.get(url, headers=headers, timeout=timeout)


def _cache_get(bucket, key, ttl_seconds):
    now = time.time()
    with _API_CACHE_LOCK:
        item = _API_CACHE.get(bucket, {}).get(key)
        if not item:
            return None
        if now - item['ts'] > ttl_seconds:
            return None
        value = item['value']
    if bucket in ('pingzhong', 'basic'):
        return value
    return deepcopy(value)


def _cache_get_stale(bucket, key):
    with _API_CACHE_LOCK:
        item = _API_CACHE.get(bucket, {}).get(key)
        if not item:
            return None
        value = item['value']
    if bucket in ('pingzhong', 'basic'):
        return value
    return deepcopy(value)


def _cache_set(bucket, key, value):
    stored_value = value if bucket in ('pingzhong', 'basic') else deepcopy(value)
    with _API_CACHE_LOCK:
        _API_CACHE.setdefault(bucket, {})[key] = {
            'ts': time.time(),
            'value': stored_value,
        }


def _get_pingzhongdata_snapshot(fund_code):
    code = str(fund_code).zfill(6)
    cached = _cache_get('pingzhong', code, TTL_PINGZHONG_SECONDS)
    if cached:
        return cached
    try:
        url = f"https://fund.eastmoney.com/pingzhongdata/{code}.js?v={int(time.time() * 1000)}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': f'https://fund.eastmoney.com/{code}.html',
        }
        response = _http_get(url, headers=headers, timeout=5)
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

        latest_date = ''
        latest_value = '-'
        latest_change = '-'
        previous_date = ''
        previous_value = '-'
        if isinstance(latest, dict):
            try:
                latest_date = datetime.fromtimestamp(float(latest.get('x')) / 1000).strftime('%Y-%m-%d')
            except Exception:
                latest_date = ''
            try:
                latest_value = str(round(float(latest.get('y')), 4))
            except Exception:
                latest_value = '-'
            try:
                latest_change = f"{float(latest.get('equityReturn', 0)):.2f}"
            except Exception:
                latest_change = str(latest.get('equityReturn', '-'))
        if isinstance(previous, dict):
            try:
                previous_date = datetime.fromtimestamp(float(previous.get('x')) / 1000).strftime('%Y-%m-%d')
            except Exception:
                previous_date = ''
            try:
                previous_value = str(round(float(previous.get('y')), 4))
            except Exception:
                previous_value = '-'

        if latest_change in ('', '-', None) and isinstance(latest, dict) and isinstance(previous, dict):
            try:
                latest_num = float(latest.get('y'))
                previous_num = float(previous.get('y'))
                latest_change = f"{((latest_num - previous_num) / previous_num) * 100:.2f}" if previous_num else '-'
            except Exception:
                latest_change = '-'

        result = {
            'code': extract_string('fS_code') or code,
            'name': extract_string('fS_name'),
            'networth': networth,
            'latest_date': latest_date,
            'latest_value': latest_value,
            'latest_change': latest_change,
            'previous_date': previous_date,
            'previous_value': previous_value,
            'stock_codes_new': extract_json('stockCodesNew') or [],
        }
        _cache_set('pingzhong', code, result)
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
        # 105/106 are US market identifiers in Eastmoney payloads.
        if market_code in ('105', '106'):
            return True
        if market_code == '116':
            overseas_count += 1
    # Some A-share funds may hold one or two HK positions.
    # Treat as QDII only when overseas holdings are the clear majority.
    return total_count > 0 and overseas_count >= 3 and overseas_count / total_count >= 0.5
    return False


def _build_snapshot_estimate(code, fallback_name, snapshot, message):
    latest_date = snapshot.get('latest_date', '-') if snapshot else '-'
    return {
        'code': code,
        'name': (snapshot.get('name') if snapshot and snapshot.get('name') else fallback_name),
        'gsz': snapshot.get('latest_value', '-') if snapshot else '-',
        'gszzl': snapshot.get('latest_change', '-') if snapshot else '-',
        'gztime': latest_date or '-',
        'dwjz': snapshot.get('previous_value', '-') if snapshot else '-',
        'jzrq': snapshot.get('previous_date', latest_date) if snapshot else '-',
        'success': False,
        'message': message,
    }


def get_fund_estimate(fund_code):
    code = str(fund_code).zfill(6)
    pingzhongdata = _get_pingzhongdata_snapshot(code)
    fallback_name = _get_fund_name_by_code(code) or code
    if pingzhongdata and pingzhongdata.get('name'):
        fallback_name = pingzhongdata.get('name') or fallback_name

    def _empty_estimate(message):
        nonlocal pingzhongdata, fallback_name
        if pingzhongdata is None:
            pingzhongdata = _get_pingzhongdata_snapshot(code)
        if pingzhongdata and pingzhongdata.get('name'):
            fallback_name = pingzhongdata.get('name') or fallback_name
        if pingzhongdata and _is_qdii_like_snapshot(pingzhongdata):
            latest_date = pingzhongdata.get('latest_date', '-') or '-'
            return _build_snapshot_estimate(
                code,
                fallback_name,
                pingzhongdata,
                f'QDII????????????????? {latest_date}',
            )
        if pingzhongdata and pingzhongdata.get('latest_value') not in ('', '-', None):
            latest_date = pingzhongdata.get('latest_date', '-') or '-'
            return _build_snapshot_estimate(
                code,
                fallback_name,
                pingzhongdata,
                f'{message}????????? {latest_date}',
            )
        return {
            'code': code,
            'name': fallback_name,
            'gsz': '-',
            'gszzl': '-',
            'gztime': '-',
            'dwjz': pingzhongdata.get('latest_value', '-') if pingzhongdata else '-',
            'jzrq': pingzhongdata.get('latest_date', '-') if pingzhongdata else '-',
            'success': False,
            'message': message,
        }

    try:
        timestamp = int(time.time() * 1000)
        url = f"http://fundgz.1234567.com.cn/js/{code}.js?rt={timestamp}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://fund.eastmoney.com/'
        }
        response = _http_get(url, headers=headers, timeout=3)
        if response.status_code != 200:
            return _empty_estimate('????')

        match = re.search(r'({.*})', response.text)
        if not match:
            return _empty_estimate('??????')

        data = json.loads(match.group(1))
        return {
            'code': data.get('fundcode') or code,
            'name': data.get('name') or fallback_name,
            'gsz': data.get('gsz'),
            'gszzl': data.get('gszzl'),
            'gztime': data.get('gztime'),
            'dwjz': data.get('dwjz'),
            'jzrq': data.get('jzrq'),
            'success': True,
        }
    except Exception as e:
        return _empty_estimate(f'??: {e}')


def fetch_funds_parallel(codes):
    def load_one(code):
        norm_code = str(code).zfill(6)
        cached = _cache_get('basic', norm_code, TTL_BASIC_SECONDS)
        if cached:
            return cached
        result = get_fund_estimate(norm_code)
        if result:
            _cache_set('basic', norm_code, result)
        return result

    return list(_FUNDS_EXECUTOR.map(load_one, codes))


def normalize_stock_symbol(stock_code):
    code = str(stock_code).strip()
    if not re.match(r'^\d{6}$', code):
        return ''
    if code.startswith(('5', '6', '9')):
        return f"sh{code}"
    if code.startswith(('0', '1', '2', '3')):
        return f"sz{code}"
    if code.startswith(('4', '8')):
        return f"bj{code}"
    return ''


def _is_hk_name(name):
    n = str(name or '').upper()
    markers = ['-W', '-SW', '-S', '－Ｗ', '－ＳＷ', '－Ｓ']
    return any(m in n for m in markers)


def _normalize_code6(code):
    digits = re.sub(r'\D', '', str(code or ''))
    if not digits:
        return ''
    return digits.zfill(6)[-6:]


def _normalize_hk_code(code):
    digits = re.sub(r'\D', '', str(code or ''))
    if not digits:
        return ''
    return str(int(digits)).zfill(5)


def _resolve_quote_entry(code, name='', market=''):
    if market == 'hk':
        hk5 = _normalize_hk_code(code)
        if not hk5:
            return None
        return (f"rt_hk{hk5}", hk5)

    code6 = _normalize_code6(code)
    if not code6:
        return None

    # ETF linked funds may contain HK holdings such as 000700/003690.
    if _is_hk_name(name):
        hk5 = _normalize_hk_code(code6)
        return (f"rt_hk{hk5}", hk5)

    a_symbol = normalize_stock_symbol(code6)
    if a_symbol:
        return (a_symbol, code6)

    # fallback: try HK if code starts with 0 and cannot map to A-share.
    if code6.startswith('0'):
        hk5 = _normalize_hk_code(code6)
        return (f"rt_hk{hk5}", hk5)
    return None


def get_realtime_stock_quotes(stock_items):
    entries = []
    symbol_aliases = {}
    if not stock_items:
        return {}

    for item in stock_items:
        if isinstance(item, dict):
            raw_code = str(item.get('code', '')).strip().upper()
            entry = _resolve_quote_entry(raw_code, item.get('name', ''), item.get('market', ''))
        else:
            raw_code = str(item or '').strip().upper()
            entry = _resolve_quote_entry(raw_code, '')
        if entry:
            entries.append(entry)
            symbol_aliases.setdefault(entry[0], set()).add(raw_code)

    if not entries:
        return {}
    symbols = list(dict.fromkeys([e[0] for e in entries]))

    try:
        # Sina quote endpoint, supports batch symbols like sh600519,sz300750,bj430047
        url = f"https://hq.sinajs.cn/list={','.join(symbols)}"
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.sina.com.cn/'
        }
        response = _http_get(url, headers=headers, timeout=3)
        if response.status_code != 200:
            return {}

        result = {}
        for line in response.text.splitlines():
            match = re.search(r'var hq_str_(\w+)="([^"]*)";', line)
            if not match:
                continue
            symbol = match.group(1)
            body = match.group(2)
            parts = body.split(',')
            if len(parts) < 4 or not parts[0]:
                continue

            code6 = ''
            latest_price = None
            change_pct = None
            quote_name = ''

            if symbol.startswith('rt_hk'):
                # HK format: 0=en_name,1=cn_name,3=prev_close,6=latest,8=pct
                code6 = _normalize_hk_code(symbol[len('rt_hk'):])
                try:
                    quote_name = parts[1].strip() if len(parts) > 1 else parts[0].strip()
                    latest_price = float(parts[6])
                    if len(parts) > 8 and parts[8] not in ('', 'None'):
                        change_pct = float(parts[8])
                    else:
                        prev_close = float(parts[3])
                        change_pct = ((latest_price - prev_close) / prev_close * 100) if prev_close else 0.0
                except Exception:
                    continue
            else:
                # A-share/B-share format: 0=name,2=prev_close,3=latest
                if len(parts) < 4:
                    continue
                try:
                    quote_name = parts[0].strip()
                    prev_close = float(parts[2])
                    latest_price = float(parts[3])
                    change_pct = ((latest_price - prev_close) / prev_close * 100) if prev_close else 0.0
                except Exception:
                    continue
                if symbol.startswith(('sh', 'sz', 'bj')):
                    code6 = _normalize_code6(symbol[2:])
                else:
                    code6 = _normalize_code6(symbol)

            if not code6 or latest_price is None or change_pct is None:
                continue
            payload = {
                'name': quote_name,
                'price': f"{latest_price:.2f}",
                'change_pct': f"{change_pct:.2f}",
            }
            for alias in symbol_aliases.get(symbol, set()):
                result[alias] = payload
                normalized_alias = _normalize_code6(alias)
                if normalized_alias:
                    result.setdefault(normalized_alias, payload)
            result[code6] = payload
        return result
    except Exception:
        return {}


def _clean_compare_name(name):
    s = unicodedata.normalize('NFKC', str(name or '')).upper()
    for token in ['-', '－', ' ', '\t', '(', ')', '（', '）', '*']:
        s = s.replace(token, '')
    return s


def _quote_name_matches(holding_name, quote_name):
    h = _clean_compare_name(holding_name)
    q = _clean_compare_name(quote_name)
    if not h or not q:
        return False
    return h in q or q in h


def _clean_name(name):
    text = str(name or '')
    for token in ['(', ')', '（', '）', '-', ' ', '\t']:
        text = text.replace(token, '')
    return text


def _is_link_fund_name(name):
    return '\u8054\u63a5' in str(name or '')


def _first_col(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _get_cached_fund_list():
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
            name_map = dict(zip(df[code_col], df[name_col].astype(str)))
            _FUND_LIST_CACHE = {
                'df': df,
                'code_col': code_col,
                'name_col': name_col,
                'name_map': name_map,
            }
            return _FUND_LIST_CACHE
        except Exception:
            return None


def _get_fund_name_by_code(fund_code):
    cache = _get_cached_fund_list()
    if not cache:
        return ''
    try:
        return str(cache.get('name_map', {}).get(str(fund_code).zfill(6), ''))
    except Exception:
        return ''


def _get_related_etf_from_detail_page(fund_code):
    code = str(fund_code).zfill(6)
    cached = _cache_get('related_etf', code, TTL_RELATED_ETF_SECONDS)
    if cached is not None:
        return cached

    result = (None, None)
    try:
        url = f'https://fund.eastmoney.com/{code}.html'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://fund.eastmoney.com/',
        }
        response = _http_get(url, headers=headers, timeout=5)
        if response.status_code == 200 and response.content:
            html = response.content.decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            marker = '\u67e5\u770b\u76f8\u5173ETF'
            for a in soup.find_all('a', href=True):
                text = a.get_text(strip=True)
                href = a.get('href', '')
                if marker not in text:
                    continue
                match = re.search(r'fund\.eastmoney\.com/(\d{6})\.html', href, re.I)
                if not match:
                    continue
                etf_code = match.group(1)
                result = (etf_code, _get_fund_name_by_code(etf_code))
                break
    except Exception:
        result = (None, None)

    _cache_set('related_etf', code, result)
    return result


def _find_associated_etf(link_fund_code, link_fund_name=''):
    code = str(link_fund_code).zfill(6)
    detail_etf = _get_related_etf_from_detail_page(code)
    if detail_etf and detail_etf[0]:
        return detail_etf

    cache = _get_cached_fund_list()
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
        matches = df[
            (df['clean_name'].str.contains(term, regex=False)) &
            (~df[name_col].astype(str).str.contains('联接', regex=False))
        ]
        if matches.empty:
            return None, None
        for _, row in matches.iterrows():
            etf_code = str(row[code_col]).zfill(6)
            if etf_code.startswith(('51', '58', '15', '16', '56')):
                return etf_code, str(row[name_col])
        row = matches.iloc[0]
        return str(row[code_col]).zfill(6), str(row[name_col])
    except Exception:
        pass
    return LINK_ETF_MANUAL_MAP.get(code, (None, None))


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
        n = float(m.group(0))
        return f"{n:.2f}%"
    except Exception:
        return s


def _parse_percent_number(v):
    m = re.search(r'-?\d+(\.\d+)?', str(v or ''))
    if not m:
        return 0.0
    try:
        return float(m.group(0))
    except Exception:
        return 0.0


def _is_meaningful_holdings(holdings):
    if not holdings:
        return False
    valid = 0
    positive = 0
    for item in holdings:
        pct = _parse_percent_number(item.get('pct'))
        if pct >= 0:
            valid += 1
        if pct > 0:
            positive += 1
    # Treat as low-quality when only a few rows or all ratios are zero.
    if len(holdings) < 5:
        return False
    return valid > 0 and positive > 0


def _get_holdings_via_akshare_once(fund_code):
    if ak is None:
        return {'success': False, 'holdings': [], 'date': '', 'error': 'akshare not installed'}
    try:
        df = ak.fund_portfolio_hold_em(symbol=str(fund_code).zfill(6))
        if df is None or df.empty:
            return {'success': False, 'holdings': [], 'date': ''}

        code_col = _first_col(df, ['股票代码', '证券代码', '代码'])
        name_col = _first_col(df, ['股票名称', '证券名称', '名称'])
        pct_col = _first_col(df, ['占净值比例', '占净值比', '持仓占比'])
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

            holdings.append({
                'code': stock_code,
                'name': str(row.get(name_col, '')).strip(),
                'price': '-',
                'change_pct': '-',
                'pct': _fmt_percent_text(row.get(pct_col, '-')),
                'delta': _fmt_percent_text(row.get(delta_col, '-')) if delta_col else '-',
            })
            if len(holdings) >= 10:
                break

        report_date = ''
        if date_col and not df.empty:
            report_date = str(df.iloc[0].get(date_col, '')).strip()

        if not holdings:
            return {'success': False, 'holdings': [], 'date': report_date}

        quote_map = get_realtime_stock_quotes(holdings)
        for item in holdings:
            q = quote_map.get(item['code'])
            if q and _quote_name_matches(item.get('name', ''), q.get('name', '')):
                item['price'] = q.get('price', '-')
                item['change_pct'] = q.get('change_pct', '-')
                continue

            # Fallback to HK symbol when name mismatch or missing quote.
            hk_q = get_realtime_stock_quotes([{'code': item['code'], 'name': item.get('name', ''), 'market': 'hk'}]).get(item['code'])
            if hk_q and hk_q.get('price') not in (None, '', '-'):
                item['price'] = hk_q.get('price', '-')
                item['change_pct'] = hk_q.get('change_pct', '-')

        return {'success': True, 'holdings': holdings, 'date': report_date}
    except Exception as e:
        return {'success': False, 'holdings': [], 'date': '', 'error': str(e)}


def _get_holdings_via_akshare_with_link_fallback(fund_code):
    code = str(fund_code).zfill(6)
    res = _get_holdings_via_akshare_once(code)
    if res.get('success') and res.get('holdings'):
        first = res['holdings'][0]
        first_pct = _parse_percent_number(first.get('pct'))
        first_name = str(first.get('name') or '')
        if ('ETF' in first_name.upper() or first_pct >= 80.0) and re.match(r'^\d{6}$', str(first.get('code', ''))):
            nested = _get_holdings_via_akshare_once(first.get('code'))
            if nested.get('success') and nested.get('holdings'):
                return nested
        return res

    link_name = _get_fund_name_by_code(code)
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
    """Fetch top-10 holdings and merge realtime quote data."""
    try:
        url = f"http://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={fund_code}&topline=10&year=&month=&rt={int(time.time()*1000)}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': f'http://fundf10.eastmoney.com/jjcc_{fund_code}.html',
        }
        response = _http_get(url, headers=headers, timeout=3)
        if response.status_code != 200:
            return {'success': False, 'holdings': [], 'date': ''}

        soup = BeautifulSoup(response.text, 'html.parser')
        holdings = []

        fund_date = ''
        date_tag = soup.find('font', class_='px12')
        if date_tag:
            fund_date = date_tag.get_text(strip=True)

        def find_col(header_texts, keywords):
            for idx, text in enumerate(header_texts):
                if any(k in text for k in keywords):
                    return idx
            return -1

        seen_codes = set()
        for table in soup.select('table.tzxq'):
            header_texts = [h.get_text(' ', strip=True) for h in table.select('thead tr th')]
            if not header_texts:
                continue

            code_idx = find_col(header_texts, ['代码'])
            name_idx = find_col(header_texts, ['名称'])
            pct_idx = find_col(header_texts, ['占净值比例', '占净值比', '持仓占比'])
            delta_idx = find_col(header_texts, ['较上期', '较上期变化'])
            if code_idx < 0 or name_idx < 0 or pct_idx < 0:
                # Eastmoney holding tables are structurally stable even when header text
                # matching is affected by encoding or whitespace differences.
                if len(header_texts) >= 9:
                    code_idx, name_idx, pct_idx = 1, 2, 6
                    delta_idx = -1
                elif len(header_texts) >= 7:
                    code_idx, name_idx, pct_idx = 1, 2, 4
                    delta_idx = -1
            if code_idx < 0 or name_idx < 0 or pct_idx < 0:
                continue

            for row in table.select('tbody tr'):
                cols = row.find_all('td')
                if len(cols) <= max(code_idx, name_idx, pct_idx):
                    continue

                code_cell = cols[code_idx]
                code_text = code_cell.get_text(strip=True).upper()
                name = cols[name_idx].get_text(strip=True)
                pct = cols[pct_idx].get_text(strip=True)
                delta = cols[delta_idx].get_text(strip=True) if (delta_idx >= 0 and delta_idx < len(cols)) else '-'

                code_link = code_cell.find('a')
                href = code_link.get('href', '') if code_link else ''
                market = ''
                href_match = re.search(r'/r/(\d+)\.([A-Z0-9]+)', href, re.I)
                if href_match:
                    market = {'116': 'hk', '105': 'us', '106': 'us'}.get(href_match.group(1), '')
                    stock_code = href_match.group(2).upper()
                else:
                    code_match = re.search(r'[A-Z]{1,10}|\d{5,6}', code_text, re.I)
                    stock_code = code_match.group(0).upper() if code_match else ''

                if not name or not pct or not stock_code or stock_code in seen_codes:
                    continue
                seen_codes.add(stock_code)
                holdings.append({
                    'code': stock_code,
                    'name': name,
                    'price': '-',
                    'change_pct': '-',
                    'pct': pct,
                    'delta': delta,
                    'market': market,
                })
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
                if q and _quote_name_matches(item.get('name', ''), q.get('name', '')):
                    item['price'] = q.get('price', '-')
                    item['change_pct'] = q.get('change_pct', '-')
                    continue

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

        # For ETF linked funds, Eastmoney jjcc may be empty or only expose linked ETF.
        # Keep existing source first, then fallback to AkShare chain lookup.
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


def get_fund_networth_history(fund_code, days=30):
    code = str(fund_code).zfill(6)
    try:
        url = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize={days}&startDate=&endDate="
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://fund.eastmoney.com/',
        }
        response = _http_get(url, headers=headers, timeout=3)
        if response.status_code != 200:
            return {'success': False, 'data': []}

        payload = response.json()
        data_list = payload.get('Data', {}).get('LSJZList', [])
        result = []
        for item in data_list:
            try:
                result.append({
                    'date': item.get('FSRQ', ''),
                    'value': float(item.get('DWJZ', 0)),
                    'change': item.get('JZZZL', '0'),
                })
            except Exception:
                continue
        result.reverse()
        if result:
            return {'success': True, 'data': result}
    except Exception as e:
        api_error = str(e)

    try:
        snapshot = _get_pingzhongdata_snapshot(code)
        trend = snapshot.get('networth', []) if snapshot else []
        result = []
        for item in trend[-days:]:
            if not isinstance(item, dict):
                continue
            try:
                result.append({
                    'date': datetime.fromtimestamp(float(item.get('x')) / 1000).strftime('%Y-%m-%d'),
                    'value': float(item.get('y')),
                    'change': str(item.get('equityReturn', '0')),
                })
            except Exception:
                continue
        if result:
            return {'success': True, 'data': result}
        return {'success': False, 'data': []}
    except Exception as e:
        return {'success': False, 'data': [], 'error': locals().get('api_error') or str(e)}


def build_intraday_from_basic(estimate):
    """No official minute API available; build fallback structure from current estimate."""
    try:
        if not estimate:
            return {'success': False, 'data': []}
        gsz = float(estimate.get('gsz') or 0)
        gztime = estimate.get('gztime') or ''
        if gsz <= 0:
            return {'success': False, 'data': []}
        if not estimate.get('success'):
            # For QDII and other non-intraday funds, render a flat line from the latest disclosed NAV.
            return {
                'success': True,
                'data': [
                    {'time': '09:30', 'value': round(gsz, 4)},
                    {'time': '15:00', 'value': round(gsz, 4)},
                ],
            }
        if not gztime:
            return {'success': False, 'data': []}
        minute = gztime.split(' ')[1][:5] if ' ' in gztime else '09:30'
        return {'success': True, 'data': [{'time': minute, 'value': round(gsz, 4)}]}
    except Exception as e:
        return {'success': False, 'data': [], 'error': str(e)}


def get_fund_intraday(fund_code):
    estimate = get_fund_estimate(fund_code)
    return build_intraday_from_basic(estimate)


def get_fund_details(fund_code):
    code = str(fund_code).zfill(6)

    cached_detail = _cache_get('detail', code, TTL_DETAIL_SECONDS)
    if cached_detail:
        return cached_detail

    basic = _cache_get('basic', code, TTL_BASIC_SECONDS)
    if not basic:
        basic = get_fund_estimate(code)
        if basic and basic.get('success'):
            _cache_set('basic', code, basic)
        else:
            # If current fetch fails, fallback to stale value to avoid empty detail popup.
            stale_basic = _cache_get_stale('basic', code)
            if stale_basic:
                basic = stale_basic

    def load_holdings():
        cached = _cache_get('holdings', code, TTL_HOLDINGS_SECONDS)
        if cached:
            return cached
        res = get_fund_holdings(code)
        if res and res.get('success'):
            _cache_set('holdings', code, res)
            return res
        stale = _cache_get_stale('holdings', code)
        return stale if stale else res

    def load_history():
        cached = _cache_get('history', code, TTL_HISTORY_SECONDS)
        if cached:
            return cached
        res = get_fund_networth_history(code, days=30)
        if res and res.get('success'):
            _cache_set('history', code, res)
            return res
        stale = _cache_get_stale('history', code)
        return stale if stale else res

    holdings_future = _DETAIL_EXECUTOR.submit(load_holdings)
    history_future = _DETAIL_EXECUTOR.submit(load_history)
    holdings = holdings_future.result()
    history = history_future.result()

    result = {
        'basic': basic if basic else {'success': False},
        'holdings': holdings if holdings else {'success': False, 'holdings': []},
        'history': history if history else {'success': False, 'data': []},
        'intraday': build_intraday_from_basic(basic),
    }
    _cache_set('detail', code, result)
    return result


@app.route('/')
def index():
    return send_from_directory('templates', 'index.html')


@app.route('/health', methods=['GET'])
def health():
    return 'ok', 200


@app.route('/api/funds', methods=['POST'])
def get_funds():
    data = request.get_json()
    if not data or 'codes' not in data:
        return jsonify({'error': 'Missing \"codes\" parameter'}), 400

    codes = data['codes']
    results = fetch_funds_parallel(codes)

    response = jsonify(results)
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


@app.route('/api/funds', methods=['OPTIONS'])
def options_funds():
    response = jsonify({'status': 'ok'})
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response


@app.route('/api/indexes', methods=['GET'])
def get_indexes():
    def fetch(code):
        try:
            url = f"https://hq.sinajs.cn/list={code}"
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://finance.sina.com.cn/'
            }
            r = _http_get(url, headers=headers, timeout=3)
            if r.status_code == 200:
                m = re.search(r'="([^"]+)"', r.text)
                if m:
                    parts = m.group(1).split(',')
                    name = parts[0]

                    def fmt(v):
                        try:
                            return f"{float(v):.2f}"
                        except Exception:
                            return "-"

                    price = fmt(parts[1])
                    change = fmt(parts[2])
                    try:
                        pct = f"{float(parts[3].replace('%', '')):.2f}"
                    except Exception:
                        pct = "0.00"
                    return {'code': code, 'name': name, 'price': price, 'change': change, 'pct': pct}
        except Exception:
            pass
        return {'code': code, 'name': 'N/A', 'price': '-', 'change': '-', 'pct': '0.00'}

    items = [
        fetch('s_sh000001'),
        fetch('s_sz399001'),
        fetch('s_sz399006'),
        fetch('s_sh000688'),
        fetch('s_bj899050'),
    ]
    response = jsonify(items)
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response


@app.route('/api/fund/<fund_code>', methods=['GET'])
def get_fund_detail(fund_code):
    result = get_fund_details(fund_code)
    response = jsonify(result)
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response


if __name__ == '__main__':
    print('启动基金监控服务...')
    print('请在浏览器访问: http://127.0.0.1:5000')
    app.run(debug=True, port=5000)
