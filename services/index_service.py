from core.http import http_get


INDEX_CONFIG = [
    {'code': 's_sh000001', 'secid': '1.000001', 'name': '上证指数'},
    {'code': 's_sz399001', 'secid': '0.399001', 'name': '深证成指'},
    {'code': 's_sz399006', 'secid': '0.399006', 'name': '创业板指'},
    {'code': 's_sh000688', 'secid': '1.000688', 'name': '科创50'},
    {'code': 's_bj899050', 'secid': '0.899050', 'name': '北证50'},
]


def _fmt_number(value):
    try:
        return f"{float(value):.2f}"
    except Exception:
        return '-'


def get_indexes():
    url = (
        'https://push2.eastmoney.com/api/qt/ulist.np/get'
        '?fltt=2&invt=2'
        '&secids=1.000001,0.399001,0.399006,1.000688,0.899050'
        '&fields=f12,f14,f2,f3,f4'
    )
    fallback = [
        {'code': item['code'], 'name': item['name'], 'price': '-', 'change': '-', 'pct': '0.00'}
        for item in INDEX_CONFIG
    ]
    try:
        response = http_get(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://quote.eastmoney.com/',
            },
            timeout=3,
        )
        if response.status_code != 200:
            return fallback

        payload = response.json()
        diff = (payload.get('data') or {}).get('diff') or []
        data_map = {
            str(item.get('f12', '')).zfill(6): item
            for item in diff
            if isinstance(item, dict)
        }

        results = []
        for item in INDEX_CONFIG:
            raw = data_map.get(item['secid'].split('.', 1)[1], {})
            results.append({
                'code': item['code'],
                'name': raw.get('f14') or item['name'],
                'price': _fmt_number(raw.get('f2')),
                'change': _fmt_number(raw.get('f4')),
                'pct': _fmt_number(raw.get('f3') or 0),
            })
        return results
    except Exception:
        return fallback
