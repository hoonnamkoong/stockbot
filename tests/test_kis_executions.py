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


from src.trade.executions import FILLED, UNFILLED, UNKNOWN, lookup_execution


def test_lookup_returns_filled_with_the_fill(monkeypatch):
    fill = {'odno': '0007441100', 'code': '353200', 'name': '대덕전자',
            'side': 'SELL', 'price': 108000.0, 'qty': 1, 'amount': 108000.0,
            'time': '20260810 094437'}
    monkeypatch.setattr(executions, '_request_executions', lambda *a, **k: [fill])

    status, got = lookup_execution('0007441100')

    assert status == FILLED
    assert got == fill


def test_lookup_returns_unfilled_when_query_succeeds_with_no_rows(monkeypatch):
    """조회는 됐는데 체결이 없다 = 미체결. 취소해도 되는 상태다."""
    monkeypatch.setattr(executions, '_request_executions', lambda *a, **k: [])

    assert lookup_execution('0007441100') == (UNFILLED, None)


def test_lookup_returns_unknown_when_query_itself_fails(monkeypatch):
    """조회 실패는 미체결이 아니다 — 이걸 섞으면 팔린 포지션을 되살린다."""
    monkeypatch.setattr(executions, '_request_executions', lambda *a, **k: None)

    assert lookup_execution('0007441100') == (UNKNOWN, None)


def test_lookup_without_odno_is_unknown_not_unfilled(monkeypatch):
    """주문번호가 없으면 추적 자체가 불가능하다. 미체결로 단정하면 안 된다."""
    monkeypatch.setattr(executions, '_request_executions', lambda *a, **k: [])

    assert lookup_execution('') == (UNKNOWN, None)
    assert lookup_execution('UNKNOWN') == (UNKNOWN, None)


def test_lookup_ignores_rows_for_other_orders(monkeypatch):
    monkeypatch.setattr(executions, '_request_executions',
                        lambda *a, **k: [{'odno': '9999999999', 'qty': 5, 'price': 100.0}])

    assert lookup_execution('0007441100') == (UNFILLED, None)


# ── 실패 사유 진단 ────────────────────────────────────────────────
# 2026-08-14: 001210(odno=0022794600, 08-12 주문)이 3런 연속 UNKNOWN인 채
# 날짜 경계 스윕에 걸려 원장에서 제거됐다. UNKNOWN이 나오는 경로는 사실상
# 요청 실패뿐인데, 이 함수가 status_code·rt_cd·예외를 전부 버려서 "왜
# 실패했는지"를 로그로 판정할 수 없었다. 돈이 걸린 경로에서 실패 사유가
# 안 남으면 다음에도 똑같이 추측만 하게 된다.

def test_http_error_logs_status_code(capsys):
    res = mock.MagicMock()
    res.status_code = 500
    with mock.patch.object(executions, 'get_access_token', return_value='tok'), \
         mock.patch.object(executions, 'get_base_url', return_value='https://x'), \
         mock.patch.dict(os.environ, _env(), clear=False), \
         mock.patch('src.trade.executions.requests.get', return_value=res):
        executions.lookup_execution('0022794600')

    out = capsys.readouterr().out
    assert '0022794600' in out
    assert '500' in out


def test_non_zero_rt_cd_logs_kis_message(capsys):
    res = mock.MagicMock()
    res.status_code = 200
    res.json.return_value = {'rt_cd': '1', 'msg_cd': 'EGW00123',
                             'msg1': '기간이 유효하지 않습니다', 'output1': []}
    with mock.patch.object(executions, 'get_access_token', return_value='tok'), \
         mock.patch.object(executions, 'get_base_url', return_value='https://x'), \
         mock.patch.dict(os.environ, _env(), clear=False), \
         mock.patch('src.trade.executions.requests.get', return_value=res):
        executions.lookup_execution('0022794600')

    out = capsys.readouterr().out
    assert '0022794600' in out
    assert 'EGW00123' in out
    assert '기간이 유효하지 않습니다' in out


def test_network_exception_logs_the_exception(capsys):
    with mock.patch.object(executions, 'get_access_token', return_value='tok'), \
         mock.patch.object(executions, 'get_base_url', return_value='https://x'), \
         mock.patch.dict(os.environ, _env(), clear=False), \
         mock.patch('src.trade.executions.requests.get', side_effect=OSError('net down')):
        executions.lookup_execution('0022794600')

    out = capsys.readouterr().out
    assert '0022794600' in out
    assert 'net down' in out


def test_no_token_logs_reason(capsys):
    with mock.patch.object(executions, 'get_access_token', return_value=None):
        executions.lookup_execution('0022794600')

    assert '토큰' in capsys.readouterr().out


def test_failure_log_carries_the_query_period(capsys):
    """어느 기간으로 조회하다 실패했는지가 없으면 날짜 범위 문제를 가려낼 수 없다."""
    res = mock.MagicMock()
    res.status_code = 500
    with mock.patch.object(executions, 'get_access_token', return_value='tok'), \
         mock.patch.object(executions, 'get_base_url', return_value='https://x'), \
         mock.patch.dict(os.environ, _env(), clear=False), \
         mock.patch('src.trade.executions.requests.get', return_value=res):
        executions.lookup_execution('0022794600', from_date='20260812', to_date='20260814')

    out = capsys.readouterr().out
    assert '20260812' in out
    assert '20260814' in out


def test_success_does_not_log_failure(capsys):
    """성공 경로는 조용해야 한다 — 2분마다 도는 루프다."""
    with mock.patch.object(executions, 'get_access_token', return_value='tok'), \
         mock.patch.object(executions, 'get_base_url', return_value='https://x'), \
         mock.patch.dict(os.environ, _env(), clear=False), \
         mock.patch('src.trade.executions.requests.get', return_value=_fake_response([])):
        executions.lookup_execution('0022794600')

    assert capsys.readouterr().out == ''
