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
CCNL_OUT = {'tday_rltv': '120.5'}


def _worker():
    w = object.__new__(DataFetcherWorker)
    w.kis_token = 'tok'
    w.kis_app_key = 'key'
    w.kis_app_secret = 'secret'
    w.kis_base_url = 'https://openapi.koreainvestment.com:9443'
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
