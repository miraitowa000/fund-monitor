import unittest
from datetime import datetime
from unittest.mock import patch

from core.time_utils import CHINA_TZ, timestamp_to_china_datetime
from services import fund_valuation_service as service


def _payload():
    return {
        'Data': {
            'gxrq': '2026-07-21',
            'gzrq': '2026-07-20',
            'list': [
                {
                    'bzdm': '018957',
                    'jjjc': 'test fund',
                    'gxrq': '2026-07-21',
                    'gzrq': '2026-07-20',
                    'gsz': '4.6527',
                    'gszzl': '8.04%',
                    'dwjz': '4.4806',
                    'gbdwjz': '4.3066',
                },
                {
                    'bzdm': 'bad',
                    'jjjc': 'invalid row',
                    'gsz': '---',
                    'gszzl': '---',
                    'dwjz': '---',
                },
            ],
        },
    }


class FakeResponse:
    status_code = 200

    def json(self):
        return _payload()


class FundValuationServiceTests(unittest.TestCase):
    def setUp(self):
        service._VALUATION_CACHE = {}
        service._VALUATION_CACHE_REFRESHED_AT = 0.0
        service._VALUATION_LAST_ATTEMPT_AT = 0.0
        service._SINA_VALUATION_CACHE = {}
        service._SINA_VALUATION_REFRESHED_AT = {}
        service._SINA_VALUATION_LAST_ATTEMPT_AT = {}

    def test_parse_sina_fund_quote(self):
        text = (
            'var hq_str_fu_018957="中航机遇领航混合发起C,11:31:00,4.3211,'
            '4.2787,4.2787,-0.0231,0.991,2026-07-27,4.3265,1.1172";'
        )

        result = service._parse_sina_valuation(text, '018957')

        self.assertEqual(result, {
            'code': '018957',
            'name': '中航机遇领航混合发起C',
            'gsz': '4.3211',
            'gszzl': '0.991',
            'gztime': '2026-07-27 11:31:00',
            'dwjz': '4.2787',
            'jzrq': '-',
            'display_date': '2026-07-27',
            'confirmed_date': '-',
            'base_date': '-',
            'quote_source': 'sina_fund_valuation',
        })

    def test_sina_quote_rejects_inconsistent_change(self):
        text = (
            'var hq_str_fu_018957="test fund,11:31:00,4.3211,4.2787,'
            '4.2787,-0.0231,-9.99,2026-07-27,4.3265,1.1172";'
        )

        self.assertIsNone(service._parse_sina_valuation(text, '018957'))

    def test_parse_maps_new_api_to_existing_quote_fields(self):
        observed_at = datetime(2026, 7, 21, 11, 49, 2, tzinfo=CHINA_TZ)

        result = service._parse_valuation_payload(_payload(), observed_at=observed_at)

        self.assertEqual(set(result), {'018957'})
        self.assertEqual(result['018957'], {
            'code': '018957',
            'name': 'test fund',
            'gsz': '4.6527',
            'gszzl': '8.04',
            'gztime': '2026-07-21 11:49:02',
            'dwjz': '4.3066',
            'jzrq': '2026-07-20',
            'display_date': '2026-07-21',
            'confirmed_date': '2026-07-20',
            'base_date': '2026-07-20',
            'quote_source': 'eastmoney_guzhi',
        })

    @patch.object(service, '_get_sina_valuation', return_value=None)
    @patch.object(service, 'http_get', return_value=FakeResponse())
    def test_process_cache_fetches_full_list_once(self, http_get, _get_sina_valuation):
        first = service.get_fund_valuation('018957')
        second = service.get_fund_valuation('018957')

        self.assertEqual(first['gszzl'], '8.04')
        self.assertEqual(second, first)
        self.assertEqual(http_get.call_count, 1)

    def test_eastmoney_epoch_is_converted_to_shanghai_date(self):
        parsed = timestamp_to_china_datetime(1784476800)

        self.assertEqual(parsed.strftime('%Y-%m-%d %H:%M'), '2026-07-20 00:00')

    def test_base_nav_falls_back_to_dwjz_before_official_value_is_filled(self):
        payload = _payload()
        payload['Data']['list'][0]['gbdwjz'] = '---'
        payload['Data']['list'][0]['dwjz'] = '4.3066'

        result = service._parse_valuation_payload(payload)

        self.assertEqual(result['018957']['dwjz'], '4.3066')


if __name__ == '__main__':
    unittest.main()
