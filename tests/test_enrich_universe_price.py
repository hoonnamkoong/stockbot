"""2026-08-04: 실전 계좌(Sim4-1)가 하루 종일 매수 0건이었다.

원인은 _enrich_universe의 fetch_sparkline이 get_universe()가 이미 채워온 KIS
라이브 price를 네이버 frgn.naver(일봉 테이블) 값으로 조건 없이 덮어쓴 것.
그 페이지는 장중에 갱신이 멈출 수 있어(Sim6가 6주간 거래 0건이던 것과 동일 함정),
판단가가 11:26부터 15:36까지 얼어붙었고 check_buy_drift가 매 사이클 매수를 막았다.

Sim6처럼 유니버스 자체에 price가 없는 고정 리터럴은 계속 네이버 값을 써야 한다 —
그게 유일한 소스이기 때문. 여기서 확인하는 건 "이미 있으면 덮어쓰지 않는다"는
조건뿐이다.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.trade_engine import TradeEngineWorker


def _frgn_html(price='6,710'):
    """frgn.naver 응답 형태 — 9열, 첫 행이 '오늘' 종가."""
    def row(date, close):
        return (f'<tr><td>{date}</td><td>{close}</td><td>0</td><td>+1.00%</td>'
                f'<td>1</td><td>10</td><td>20</td><td>30</td><td>3.40%</td></tr>')
    return ('<table class="type2">'
            + row('2026.08.04', price)
            + row('2026.08.03', '6,500')
            + '</table>')


class _FakeResponse:
    def __init__(self, html):
        self.content = html.encode('utf-8')


def _enrich_with_naver(stocks, naver_price='6,710'):
    kis = mock.MagicMock()
    kis.get_price_quote.return_value = {'price': 0, 'change_rate_pct': 0.0,
                                         'per': 0.0, 'pbr': 0.0, 'sector_name': ''}
    kis.get_investor_trend_estimate.return_value = {}
    with mock.patch('requests.get', return_value=_FakeResponse(_frgn_html(naver_price))), \
         mock.patch('src.trade.kis_data_provider.KISDataProvider', return_value=kis):
        return TradeEngineWorker._enrich_universe(None, stocks)


def test_enrich_does_not_overwrite_live_price_from_get_universe():
    """Sim4/4-1처럼 get_universe()가 이미 KIS 라이브 price를 채운 경우,
    네이버 frgn 페이지의 값으로 덮어쓰면 안 된다 — 그게 오늘의 버그였다."""
    stocks = [{'code': '317400', 'name': '자이에스앤디', 'price': 7680,
               'current_price': 7680}]
    out = _enrich_with_naver(stocks, naver_price='6,710')
    assert out[0]['price'] == 7680
    assert out[0]['current_price'] == 7680


def test_enrich_fills_price_when_universe_has_none():
    """Sim6처럼 고정 리터럴(price 없음)은 네이버 값이 유일한 소스라 계속 채운다."""
    stocks = [{'code': '114800', 'name': 'KODEX 인버스'}]
    out = _enrich_with_naver(stocks, naver_price='1,314')
    assert out[0]['price'] == 1314
    assert out[0]['current_price'] == 1314


def test_enrich_treats_zero_price_as_missing():
    """price가 0으로 들어온 경우(조회 실패 잔재)도 채워야 정상 동작한다."""
    stocks = [{'code': '317400', 'name': '자이에스앤디', 'price': 0}]
    out = _enrich_with_naver(stocks, naver_price='6,710')
    assert out[0]['price'] == 6710


def test_enrich_still_fills_sparkline_when_price_preserved():
    """price는 보존해도 sparkline_price(ADX용)는 여전히 네이버에서 채워야 한다."""
    stocks = [{'code': '317400', 'name': '자이에스앤디', 'price': 7680}]
    out = _enrich_with_naver(stocks, naver_price='6,710')
    assert out[0]['price'] == 7680
    assert out[0]['sparkline_price'] == [6500, 6710]
