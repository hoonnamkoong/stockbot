"""네이버 페이지 파싱 실패가 KIS 보강까지 죽이면 안 된다.

2026-08-03: 후보 18종목 전부 open_price/day_high/day_low/per/pbr/tick_power가 0으로
들어와 심9(갭소진)가 진입 후보를 한 건도 만들지 못했다. 원인은 데이터가 아니라 구조였다 —
KIS inquire-price 호출이 main.naver 요청과 같은 try 블록 안에 있어서, 네이버 페이지가
타임아웃 나면 KIS 호출은 실행조차 되지 않았다. 두 소스는 독립이어야 한다.

[2026-08-12] KIS 호출은 이제 requests.get 사본이 아니라 KISDataProvider(하드닝된
클라이언트, rt_cd 검사·응답 형태 대응·캐시 포함)로 위임한다. 그래서 이 파일의 KIS
관련 테스트는 provider를 주입해 검증한다.
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


class _FakeProvider:
    def __init__(self, quote=None, tick=0.0, raises=False):
        self._quote = quote or {}
        self._tick = tick
        self._raises = raises

    def get_price_quote(self, code):
        if self._raises:
            raise RuntimeError('provider get_price_quote 실패(주입된 장애)')
        return self._quote

    def get_tick_power(self, code):
        if self._raises:
            raise RuntimeError('provider get_tick_power 실패(주입된 장애)')
        return self._tick


QUOTE = {
    'price': 18000, 'change_rate_pct': 3.6, 'per': 11.2, 'pbr': 0.9,
    'sector_name': '건설', 'w52_hgpr': 20000, 'w52_lwpr': 9000,
    'open_price': 17000, 'day_high': 18500, 'day_low': 16800, 'prev_close': 17310,
    'foreign_rate': 3.47, 'eps': 1500, 'bps': 20000,
    'mkt_cap': 1234, 'amount': 1234567890, 'volume': 4321,
}


def _worker():
    w = object.__new__(DataFetcherWorker)
    w.kis = None
    return w


def test_kis_enrichment_survives_naver_main_failure(monkeypatch):
    """main.naver가 죽어도 KIS 시가·고가·저가·체결강도는 채워져야 한다."""
    def fake_get(url, **kw):
        if 'frgn.naver' in url:
            return FakeResponse(frgn_html())
        if 'main.naver' in url:
            raise requests.exceptions.ConnectTimeout('naver unreachable from runner')
        raise AssertionError(f'예상치 못한 요청: {url}')

    monkeypatch.setattr(data_fetcher.requests, 'get', fake_get)
    w = _worker()
    w.kis = _FakeProvider(QUOTE, tick=120.5)

    d = w._get_stock_details('002990')

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
        raise AssertionError(f'예상치 못한 요청: {url}')

    monkeypatch.setattr(data_fetcher.requests, 'get', fake_get)

    d = _worker()._get_stock_details('002990')

    assert d['bid_ask_ratio'] == 3.0


def test_kis_fields_come_from_the_shared_provider(monkeypatch):
    """사본을 지운 뒤에도 같은 키·같은 값이 나와야 한다(동작 무변경)."""
    def fake_get(url, **kw):
        if 'frgn.naver' in url:
            return FakeResponse(frgn_html())
        if 'main.naver' in url:
            return FakeResponse('<table class="type2 type_stock2"></table>')
        raise AssertionError(f'KIS를 직접 부르면 안 된다: {url}')

    monkeypatch.setattr(data_fetcher.requests, 'get', fake_get)
    w = _worker()
    w.kis = _FakeProvider(QUOTE, tick=128.9)

    d = w._get_stock_details('002990')

    assert d['open_price'] == 17000 and d['day_high'] == 18500
    assert d['per'] == 11.2 and d['tick_power'] == 128.9
    assert d['amount'] == 1234567890 and d['sector_name'] == '건설'
    assert d['change_rate'] == '+3.60%'


def test_zero_quote_does_not_overwrite_naver_values(monkeypatch):
    """KIS가 0을 주면 덮어쓰지 않는다 — 08-04 실전 0체결이 이 형태였다."""
    def fake_get(url, **kw):
        if 'frgn.naver' in url:
            return FakeResponse(frgn_html())
        if 'main.naver' in url:
            return FakeResponse('<table class="type2 type_stock2"></table>')
        raise AssertionError(f'KIS를 직접 부르면 안 된다: {url}')

    monkeypatch.setattr(data_fetcher.requests, 'get', fake_get)
    w = _worker()
    w.kis = _FakeProvider({k: 0 for k in QUOTE}, tick=0.0)

    d = w._get_stock_details('002990')

    assert d['prev_close'] == 17310, '네이버가 준 전일종가가 0으로 덮이면 안 된다'
    assert d['current_price'] == 17940, '네이버가 준 현재가가 0으로 덮이면 안 된다'
    assert d.get('price', 0) == 0, 'KIS가 0이면 price 키를 만들지 않는다'


def test_kis_exception_survives_and_leaves_naver_values_intact(monkeypatch):
    """provider가 예외를 던져도 죽지 않고 네이버 값은 살아 있어야 한다.

    2026-08-03 격리 원칙(코드 대신)의 반대편: 그때는 '한쪽이 죽으면 다른 쪽도
    실행 안 됨'이었다. 여기서는 'KIS가 예외를 던져도 그 예외가 전체를 죽이면
    안 된다'는 같은 원칙의 다른 실패 모드를 확인한다. get_price_quote/
    get_tick_power를 감싼 try/except를 지워도 이 테스트 전에는 초록으로
    남았다 — provider가 주입되지 않은 시나리오만 있었기 때문이다.
    """
    def fake_get(url, **kw):
        if 'frgn.naver' in url:
            return FakeResponse(frgn_html())
        if 'main.naver' in url:
            return FakeResponse('<table class="type2 type_stock2"></table>')
        raise AssertionError(f'KIS를 직접 부르면 안 된다: {url}')

    monkeypatch.setattr(data_fetcher.requests, 'get', fake_get)
    w = _worker()
    w.kis = _FakeProvider(raises=True)

    d = w._get_stock_details('002990')  # 예외 없이 끝나야 한다

    assert d['prev_close'] == 17310
    assert d['current_price'] == 17940
    assert d['tick_power'] == 0.0
