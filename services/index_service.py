import re

from core.http import http_get


def _fetch_index(code):
    try:
        url = f"https://hq.sinajs.cn/list={code}"
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.sina.com.cn/',
        }
        response = http_get(url, headers=headers, timeout=3)
        if response.status_code == 200:
            match = re.search(r'="([^"]+)"', response.text)
            if match:
                parts = match.group(1).split(',')
                name = parts[0]

                def fmt(v):
                    try:
                        return f"{float(v):.2f}"
                    except Exception:
                        return '-'

                price = fmt(parts[1])
                change = fmt(parts[2])
                try:
                    pct = f"{float(parts[3].replace('%', '')):.2f}"
                except Exception:
                    pct = '0.00'
                return {'code': code, 'name': name, 'price': price, 'change': change, 'pct': pct}
    except Exception:
        pass
    return {'code': code, 'name': 'N/A', 'price': '-', 'change': '-', 'pct': '0.00'}


def get_indexes():
    codes = [
        's_sh000001',
        's_sz399001',
        's_sz399006',
        's_sh000688',
        's_bj899050',
    ]
    return [_fetch_index(code) for code in codes]
