"""네이버 페이지 파싱 실패가 KIS 보강까지 죽이면 안 된다.

2026-08-03: 후보 18종목 전부 open_price/day_high/day_low/per/pbr/tick_power가 0으로
들어와 심9(갭소진)가 진입 후보를 한 건도 만들지 못했다. 원인은 데이터가 아니라 구조였다 —
KIS inquire-price 호출이 main.naver 요청과 같은 try 블록 안에 있어서, 네이버 페이지가
타임아웃 나면 KIS 호출은 실행조차 되지 않았다. 두 소스는 독립이어야 한다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import requests
from src.pipeline.workers import data_fetcher
from src.pipeline.workers.data_fetcher import DataFetcherWorker


def frgn_html():
    def row(date, close, rate, foreign_rate):
        return (
            f'<tr><td>{date}</td><td>{close}</td><td>0</td><td>{rate}</td>'
            f'<td>1</td><td>10</td><td>20</td><td>30</td><td>{foreign_rate}%</td></tr>'
        )
    return ('<table class="type2">'
            + row('2026.07.10', '17,940', '+3.64%', '3.47')
            + row('2026.07.09', '17,310', '+1.00%', '3.40')
            + '</table>')


class FakeResponse:
    def __init__(self, html):
        self.content = html.encode('utf-8')


class FakeKisResponse:
    status_code = 200

    def __init__(self, out):
        self._out = out

    def json(self):
        return {'output': self._out}


KIS_OUT = {
    'stck_prpr': '18000', 'stck_oprc': '17000', 'stck_hgpr': '18500',
    'stck_lwpr': '16800', 'stck_sdpr': '17310',
    'per': '11.2', 'pbr': '0.9', 'acml_tr_pbmn': '1234567890',
}

# tday_rltv(체결강도)는 inquire-price가 아니라 inquire-ccnl 응답이다(2026-08-11 정정).
# **output은 dict가 아니라 체결 30행짜리 리스트다**(2026-08-12 실호출로 확정).
# 08-11에 엔드포인트만 옮기고 이 형태를 확인하지 않아, 실제로는 매 종목
# 'list' object has no attribute 'get'으로 죽고 tick_power가 100% 0이었다.
# 여기 mock이 코드와 같은 오해(dict)를 복제하고 있어서 테스트는 초록이었다.
# 최신 행이 [0]이고, tday_rltv는 당일 누적값이라 모든 행이 같은 값을 갖는다.
CCNL_OUT = [
    {'stck_cntg_hour': '155954', 'stck_prpr': '255500', 'cntg_vol': '19',
     'tday_rltv': '120.5', 'prdy_ctrt': '6.68'},
    {'stck_cntg_hour': '155747', 'stck_prpr': '255500', 'cntg_vol': '1',
     'tday_rltv': '120.5', 'prdy_ctrt': '6.68'},
]


def _worker():
    w = object.__new__(DataFetcherWorker)
    w.kis_token = 'tok'
    w.kis_app_key = 'key'
    w.kis_app_secret = 'secret'
    w.kis_base_url = 'https://openapi.koreainvestment.com:9443'
    # __init__을 건너뛰므로 여기서 채운다. 빠져 있으면 진단(probe) 경로가
    # AttributeError로 죽는데 그게 except에 삼켜져, 테스트는 통과하면서
    # 진단은 한 줄도 안 남는 상태를 못 잡는다.
    w._tick_probe_logged = False
    return w


def test_kis_enrichment_survives_naver_main_failure(monkeypatch):
    """main.naver가 죽어도 KIS 시가·고가·저가·체결강도는 채워져야 한다."""
    def fake_get(url, **kw):
        if 'frgn.naver' in url:
            return FakeResponse(frgn_html())
        if 'main.naver' in url:
            raise requests.exceptions.ConnectTimeout('naver unreachable from runner')
        if 'inquire-ccnl' in url:
            return FakeKisResponse(CCNL_OUT)
        if 'inquire-price' in url:
            return FakeKisResponse(KIS_OUT)
        raise AssertionError(f'예상치 못한 요청: {url}')

    monkeypatch.setattr(data_fetcher.requests, 'get', fake_get)

    d = _worker()._get_stock_details('002990')

    assert d['open_price'] == 17000
    assert d['day_high'] == 18500
    assert d['day_low'] == 16800
    assert d['tick_power'] == 120.5


def test_naver_micro_data_survives_kis_failure(monkeypatch):
    """반대 방향도 성립해야 한다 — KIS가 죽어도 네이버 호가 파싱은 살아 있어야 한다."""
    quote_html = ('<table class="type2 type_stock2">'
                  '<tr class="total"><td class="sell">300</td><td class="buy">100</td></tr>'
                  '</table>')

    def fake_get(url, **kw):
        if 'frgn.naver' in url:
            return FakeResponse(frgn_html())
        if 'main.naver' in url:
            return FakeResponse(quote_html)
        if 'inquire-ccnl' in url or 'inquire-price' in url:
            raise requests.exceptions.ConnectTimeout('KIS unreachable')
        raise AssertionError(f'예상치 못한 요청: {url}')

    monkeypatch.setattr(data_fetcher.requests, 'get', fake_get)

    d = _worker()._get_stock_details('002990')

    assert d['bid_ask_ratio'] == 3.0


def test_tick_power_survives_inquire_price_failure(monkeypatch):
    """inquire-price가 죽어도 체결강도(inquire-ccnl)는 독립적으로 채워져야 한다.

    둘 다 KIS 호출이지만 서로 다른 엔드포인트다 — 하나가 타임아웃 나도 다른
    쪽 보강은 살아야 한다(위 main.naver/KIS 격리와 같은 원칙).
    """
    def fake_get(url, **kw):
        if 'frgn.naver' in url:
            return FakeResponse(frgn_html())
        if 'main.naver' in url:
            return FakeResponse('<table class="type2 type_stock2"></table>')
        if 'inquire-ccnl' in url:
            return FakeKisResponse(CCNL_OUT)
        if 'inquire-price' in url:
            raise requests.exceptions.ConnectTimeout('inquire-price unreachable')
        raise AssertionError(f'예상치 못한 요청: {url}')

    monkeypatch.setattr(data_fetcher.requests, 'get', fake_get)

    d = _worker()._get_stock_details('002990')

    assert d['tick_power'] == 120.5
    assert d.get('open_price', 0) == 0


def test_empty_ccnl_list_leaves_tick_power_zero_with_diagnosis(monkeypatch, capsys):
    """체결이 아직 없으면(장 시작 전 등) output은 빈 리스트로 온다.

    0으로 남는 것만으로는 부족하다 — 예외로 죽어도 결과는 똑같이 0이라서
    둘이 구분되지 않는다. 진단이 남는지까지 봐야 '측정 못 함'의 이유가 남는다.
    """
    def fake_get(url, **kw):
        if 'frgn.naver' in url:
            return FakeResponse(frgn_html())
        if 'main.naver' in url:
            return FakeResponse('<table class="type2 type_stock2"></table>')
        if 'inquire-ccnl' in url:
            return FakeKisResponse([])
        if 'inquire-price' in url:
            return FakeKisResponse(KIS_OUT)
        raise AssertionError(f'예상치 못한 요청: {url}')

    monkeypatch.setattr(data_fetcher.requests, 'get', fake_get)

    d = _worker()._get_stock_details('002990')

    assert d['tick_power'] == 0.0
    out = capsys.readouterr().out
    assert '[진단]' in out
    assert 'has no attribute' not in out


def test_unexpected_ccnl_shape_logs_diagnosis_instead_of_crashing(monkeypatch, capsys):
    """형태가 또 바뀌어도 예외가 아니라 진단 한 줄이 남아야 한다.

    08-12 사고의 핵심이 이거였다. probe는 "필드명이 틀렸나 / 응답이 비었나"를
    가르려고 만든 계기판인데, 자기가 진단해야 할 형태 가정 **뒤에** 있어서
    리스트가 오는 순간 자기보다 먼저 예외가 났다. 계기판이 사고 때만 꺼졌다.
    """
    def fake_get(url, **kw):
        if 'frgn.naver' in url:
            return FakeResponse(frgn_html())
        if 'main.naver' in url:
            return FakeResponse('<table class="type2 type_stock2"></table>')
        if 'inquire-ccnl' in url:
            return FakeKisResponse('예상 못 한 형태')
        if 'inquire-price' in url:
            return FakeKisResponse(KIS_OUT)
        raise AssertionError(f'예상치 못한 요청: {url}')

    monkeypatch.setattr(data_fetcher.requests, 'get', fake_get)

    d = _worker()._get_stock_details('002990')

    assert d['tick_power'] == 0.0
    out = capsys.readouterr().out
    assert '[진단]' in out
    assert 'has no attribute' not in out
