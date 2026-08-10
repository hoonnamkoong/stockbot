"""미체결 주문 취소(TTTC0803U). 실패를 성공으로 오인하면 같은 종목에 주문이 겹친다."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.trade import order_cancel


class _Res:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _patch(monkeypatch, res, captured=None):
    monkeypatch.setattr(order_cancel, 'get_access_token', lambda: 'tok')
    monkeypatch.setattr(order_cancel, 'get_base_url', lambda: 'https://kis.test')
    monkeypatch.setenv('KIS_ACCOUNT_NO', '1234567801')
    monkeypatch.setenv('KIS_APP_KEY', 'k')
    monkeypatch.setenv('KIS_APP_SECRET', 's')
    monkeypatch.setenv('KIS_IS_VIRTUAL', 'false')

    def fake_post(url, headers=None, json=None, timeout=None):
        if captured is not None:
            captured.update({'url': url, 'headers': headers, 'body': json})
        return res

    monkeypatch.setattr(order_cancel.requests, 'post', fake_post)


def test_returns_true_on_success(monkeypatch):
    _patch(monkeypatch, _Res(200, {'rt_cd': '0', 'msg1': '정상처리'}))
    assert order_cancel.cancel_order('0007441100', '353200', 3) is True


def test_returns_false_when_kis_rejects(monkeypatch):
    _patch(monkeypatch, _Res(200, {'rt_cd': '1', 'msg1': '취소할 수량이 없습니다'}))
    assert order_cancel.cancel_order('0007441100', '353200', 3) is False


def test_returns_false_on_http_error(monkeypatch):
    _patch(monkeypatch, _Res(500, {}))
    assert order_cancel.cancel_order('0007441100', '353200', 3) is False


def test_returns_false_without_odno(monkeypatch):
    """주문번호가 없으면 취소할 대상을 특정할 수 없다. 호출조차 하지 않는다."""
    called = {'n': 0}
    monkeypatch.setattr(order_cancel, 'get_access_token', lambda: 'tok')
    monkeypatch.setattr(order_cancel.requests, 'post',
                        lambda *a, **k: called.__setitem__('n', called['n'] + 1))

    assert order_cancel.cancel_order('', '353200', 3) is False
    assert order_cancel.cancel_order('UNKNOWN', '353200', 3) is False
    assert called['n'] == 0


def test_sends_full_cancel_with_required_fields(monkeypatch):
    captured = {}
    _patch(monkeypatch, _Res(200, {'rt_cd': '0'}), captured)

    order_cancel.cancel_order('0007441100', '353200', 3)

    body = captured['body']
    assert body['ORGN_ODNO'] == '0007441100'
    assert body['RVSE_CNCL_DVSN_CD'] == '02', '02=취소 (01=정정)'
    assert body['QTY_ALL_ORD_YN'] == 'Y', '잔량 전부 취소'
    assert body['CANO'] == '12345678'
    assert body['ACNT_PRDT_CD'] == '01'
    assert body['ORD_QTY'] == '3'
    assert captured['headers']['tr_id'] == 'TTTC0803U'


def test_uses_virtual_tr_id_when_virtual(monkeypatch):
    captured = {}
    _patch(monkeypatch, _Res(200, {'rt_cd': '0'}), captured)
    monkeypatch.setenv('KIS_IS_VIRTUAL', 'true')

    order_cancel.cancel_order('0007441100', '353200', 3)

    assert captured['headers']['tr_id'] == 'VTTC0803U'
