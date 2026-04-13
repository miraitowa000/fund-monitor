import re
import unicodedata

from core.http import http_get


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
    markers = ['-W', '-SW', '-S', '－W', '－SW']
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
    if _is_hk_name(name):
        hk5 = _normalize_hk_code(code6)
        return (f"rt_hk{hk5}", hk5)
    a_symbol = normalize_stock_symbol(code6)
    if a_symbol:
        return (a_symbol, code6)
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
        response = http_get(
            f"https://hq.sinajs.cn/list={','.join(symbols)}",
            headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn/'},
            timeout=3,
        )
        if response.status_code != 200:
            return {}
        result = {}
        for line in response.text.splitlines():
            match = re.search(r'var hq_str_(\w+)="([^"]*)";', line)
            if not match:
                continue
            symbol = match.group(1)
            parts = match.group(2).split(',')
            if len(parts) < 4 or not parts[0]:
                continue
            code6 = ''
            latest_price = None
            change_pct = None
            quote_name = ''
            if symbol.startswith('rt_hk'):
                code6 = _normalize_hk_code(symbol[len('rt_hk'):])
                try:
                    quote_name = parts[1].strip() if len(parts) > 1 else parts[0].strip()
                    latest_price = float(parts[6])
                    change_pct = float(parts[8]) if len(parts) > 8 and parts[8] not in ('', 'None') else ((latest_price - float(parts[3])) / float(parts[3]) * 100 if float(parts[3]) else 0.0)
                except Exception:
                    continue
            else:
                try:
                    quote_name = parts[0].strip()
                    prev_close = float(parts[2])
                    latest_price = float(parts[3])
                    change_pct = ((latest_price - prev_close) / prev_close * 100) if prev_close else 0.0
                except Exception:
                    continue
                code6 = _normalize_code6(symbol[2:] if symbol.startswith(('sh', 'sz', 'bj')) else symbol)
            if not code6 or latest_price is None or change_pct is None:
                continue
            payload = {'name': quote_name, 'price': f"{latest_price:.2f}", 'change_pct': f"{change_pct:.2f}"}
            for alias in symbol_aliases.get(symbol, set()):
                result[alias] = payload
                normalized_alias = _normalize_code6(alias)
                if normalized_alias:
                    result.setdefault(normalized_alias, payload)
            result[code6] = payload
        return result
    except Exception:
        return {}


def clean_compare_name(name):
    s = unicodedata.normalize('NFKC', str(name or '')).upper()
    for token in ['-', '－', ' ', '\t', '(', ')', '（', '）', '*']:
        s = s.replace(token, '')
    return s


def quote_name_matches(holding_name, quote_name):
    h = clean_compare_name(holding_name)
    q = clean_compare_name(quote_name)
    if not h or not q:
        return False
    return h in q or q in h
