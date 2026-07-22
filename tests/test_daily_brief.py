import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.trade.balance import _parse_holding


def test_parse_holding_includes_pl_amount():
    item = {
        'pdno': '005930', 'prdt_name': '삼성전자', 'hldg_qty': '10',
        'pchs_avg_pric': '70000', 'prpr': '75000',
        'evlu_pfls_rt': '7.14', 'evlu_pfls_amt': '50000',
    }
    h = _parse_holding(item)
    assert h['code'] == '005930'
    assert h['qty'] == 10
    assert h['current_price'] == 75000
    assert h['pl_amount'] == 50000


def test_parse_holding_missing_pl_amount_is_zero():
    item = {'pdno': '005930', 'prdt_name': '삼성전자', 'hldg_qty': '10',
            'pchs_avg_pric': '70000', 'prpr': '75000', 'evlu_pfls_rt': '0'}
    assert _parse_holding(item)['pl_amount'] == 0
