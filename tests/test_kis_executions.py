"""E10 (2026-08-04 스크래퍼 지연 재설계): KIS 일별체결조회(TTTC8001R) 실측.

program_trader.py의 오래된 주석이 이미 인정하던 문제 — 원장의 avg_price는
"KIS 확정 체결가가 아닌 주문가 추정치"다. 이 모듈이 그 실측 소스를 제공한다.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.trade import executions


def _env():
    return {
        'KIS_APP_KEY': 'key', 'KIS_APP_SECRET': 'secret',
        'KIS_ACCOUNT_NO': '12345678-01', 'KIS_IS_VIRTUAL': 'false',
    }


def _fake_response(rows, rt_cd='0'):
    res = mock.MagicMock()
    res.status_code = 200
    res.json.return_value = {'rt_cd': rt_cd, 'output1': rows}
    return res


def test_no_token_returns_empty_list():
    with mock.patch.object(executions, 'get_access_token', return_value=None):
        assert executions.get_daily_executions() == []


def test_no_account_configured_returns_empty_list():
    with mock.patch.object(executions, 'get_access_token', return_value='tok'), \
         mock.patch.dict(os.environ, {'KIS_ACCOUNT_NO': ''}, clear=False):
        assert executions.get_daily_executions() == []


def test_parses_fill_rows():
    rows = [{
        'odno': '0000123456', 'pdno': '005930', 'prdt_name': '삼성전자',
        'sll_buy_dvsn_cd': '02', 'avg_prvs': '71000', 'tot_ccld_qty': '10',
        'tot_ccld_amt': '710000', 'ord_dt': '20260804', 'ord_tmd': '093000',
    }]
    with mock.patch.object(executions, 'get_access_token', return_value='tok'), \
         mock.patch.object(executions, 'get_base_url', return_value='https://x'), \
         mock.patch.dict(os.environ, _env(), clear=False), \
         mock.patch('src.trade.executions.requests.get', return_value=_fake_response(rows)):
        fills = executions.get_daily_executions()

    assert len(fills) == 1
    f = fills[0]
    assert f['odno'] == '0000123456'
    assert f['code'] == '005930'
    assert f['side'] == 'BUY'
    assert f['price'] == 71000.0
    assert f['qty'] == 10


def test_sell_side_mapping():
    rows = [{'odno': 'X', 'pdno': '005930', 'sll_buy_dvsn_cd': '01',
             'avg_prvs': '70000', 'tot_ccld_qty': '5'}]
    with mock.patch.object(executions, 'get_access_token', return_value='tok'), \
         mock.patch.object(executions, 'get_base_url', return_value='https://x'), \
         mock.patch.dict(os.environ, _env(), clear=False), \
         mock.patch('src.trade.executions.requests.get', return_value=_fake_response(rows)):
        fills = executions.get_daily_executions()
    assert fills[0]['side'] == 'SELL'


def test_zero_qty_rows_are_dropped():
    rows = [{'odno': 'X', 'pdno': '005930', 'sll_buy_dvsn_cd': '02',
             'avg_prvs': '70000', 'tot_ccld_qty': '0'}]
    with mock.patch.object(executions, 'get_access_token', return_value='tok'), \
         mock.patch.object(executions, 'get_base_url', return_value='https://x'), \
         mock.patch.dict(os.environ, _env(), clear=False), \
         mock.patch('src.trade.executions.requests.get', return_value=_fake_response(rows)):
        assert executions.get_daily_executions() == []


def test_non_zero_rt_cd_returns_empty():
    with mock.patch.object(executions, 'get_access_token', return_value='tok'), \
         mock.patch.object(executions, 'get_base_url', return_value='https://x'), \
         mock.patch.dict(os.environ, _env(), clear=False), \
         mock.patch('src.trade.executions.requests.get', return_value=_fake_response([], rt_cd='1')):
        assert executions.get_daily_executions() == []


def test_http_error_returns_empty():
    res = mock.MagicMock()
    res.status_code = 500
    with mock.patch.object(executions, 'get_access_token', return_value='tok'), \
         mock.patch.object(executions, 'get_base_url', return_value='https://x'), \
         mock.patch.dict(os.environ, _env(), clear=False), \
         mock.patch('src.trade.executions.requests.get', return_value=res):
        assert executions.get_daily_executions() == []


def test_network_exception_returns_empty_not_raises():
    with mock.patch.object(executions, 'get_access_token', return_value='tok'), \
         mock.patch.object(executions, 'get_base_url', return_value='https://x'), \
         mock.patch.dict(os.environ, _env(), clear=False), \
         mock.patch('src.trade.executions.requests.get', side_effect=OSError('net down')):
        assert executions.get_daily_executions() == []


def test_find_execution_by_odno_matches():
    rows = [{'odno': '0000777777', 'pdno': '005930', 'sll_buy_dvsn_cd': '02',
             'avg_prvs': '71500', 'tot_ccld_qty': '3'}]
    with mock.patch.object(executions, 'get_access_token', return_value='tok'), \
         mock.patch.object(executions, 'get_base_url', return_value='https://x'), \
         mock.patch.dict(os.environ, _env(), clear=False), \
         mock.patch('src.trade.executions.requests.get', return_value=_fake_response(rows)):
        found = executions.find_execution_by_odno('0000777777')
    assert found is not None
    assert found['price'] == 71500.0


def test_find_execution_by_odno_rejects_unknown_placeholder():
    """'UNKNOWN'은 애초에 조회를 시도하지 않는다 — 매칭 대상이 아니다."""
    with mock.patch('src.trade.executions.requests.get') as get_mock:
        assert executions.find_execution_by_odno('UNKNOWN') is None
        get_mock.assert_not_called()


def test_find_execution_by_odno_returns_none_when_not_found():
    with mock.patch.object(executions, 'get_access_token', return_value='tok'), \
         mock.patch.object(executions, 'get_base_url', return_value='https://x'), \
         mock.patch.dict(os.environ, _env(), clear=False), \
         mock.patch('src.trade.executions.requests.get', return_value=_fake_response([])):
        assert executions.find_execution_by_odno('0000000001') is None
