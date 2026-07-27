import unittest
from datetime import datetime
from unittest.mock import patch

from core.time_utils import CHINA_TZ
from services import fund_basic_service as service


def _snapshot():
    return {
        'code': '018957',
        'name': '中航机遇领航混合发起C',
        'latest_date': '2026-07-24',
        'latest_value': '4.2787',
        'latest_change': '-2.83',
        'previous_date': '2026-07-23',
        'previous_value': '4.4032',
        'stock_codes_new': [],
    }


def _holdings(quote_date='2026-07-27'):
    return {
        'success': True,
        'date': '2026-06-30',
        'holdings': [
            {
                'code': f'60000{index}',
                'name': f'stock {index}',
                'pct': '10.00%',
                'change_pct': '1.00',
                'quote_date': quote_date,
                'quote_time': f'10:0{index}:00',
            }
            for index in range(5)
        ],
    }


class FundBasicValuationFallbackTests(unittest.TestCase):
    @patch.object(service, 'cache_get', return_value=None)
    @patch.object(service, 'cache_set')
    @patch('services.fund_detail_service.get_fund_holdings', return_value=_holdings())
    @patch.object(
        service,
        'china_now',
        return_value=datetime(2026, 7, 27, 10, 10, 0, tzinfo=CHINA_TZ),
    )
    def test_builds_weighted_estimate_from_current_holdings(
        self,
        china_now,
        get_fund_holdings,
        cache_set,
        cache_get,
    ):
        result = service._build_holdings_estimate(
            '018957',
            'fallback name',
            _snapshot(),
            '直接估值暂无数据',
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['gszzl'], '0.50')
        self.assertEqual(result['gsz'], '4.3001')
        self.assertEqual(result['dwjz'], '4.2787')
        self.assertEqual(result['display_date'], '2026-07-27')
        self.assertEqual(result['base_date'], '2026-07-24')
        self.assertEqual(result['quote_source'], 'holdings_weighted_estimate')
        self.assertEqual(result['holding_coverage'], 50.0)
        self.assertEqual(result['holding_quote_count'], 5)
        self.assertIn('2026-06-30', result['message'])

    @patch.object(service, 'cache_get', return_value=None)
    @patch('services.fund_detail_service.get_fund_holdings', return_value=_holdings('2026-07-24'))
    @patch.object(
        service,
        'china_now',
        return_value=datetime(2026, 7, 27, 10, 10, 0, tzinfo=CHINA_TZ),
    )
    def test_rejects_holdings_with_stale_stock_quotes(
        self,
        china_now,
        get_fund_holdings,
        cache_get,
    ):
        result = service._build_holdings_estimate(
            '018957',
            'fallback name',
            _snapshot(),
            '直接估值暂无数据',
        )

        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
