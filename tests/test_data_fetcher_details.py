import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
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


def test_current_price_is_parsed(monkeypatch):
    """거래상위에서 빠진 종목도 현재가를 얻어야 한다."""
    monkeypatch.setattr(data_fetcher.requests, 'get',
                        lambda url, **kw: FakeResponse(frgn_html()))
    w = object.__new__(DataFetcherWorker)

    d = w._get_stock_details('002990')

    assert d['current_price'] == 17940
    assert d['prev_close'] == 17310


# 2026-08-26 — Sim9-1(돈치안)의 "거래대금 동반" 게이트가 절대 거래대금의 횡단면
# z라서 대형주 필터로 동작했다. 급증을 제대로 재려면 그 종목 **자신의 평균**이
# 필요한데 국내 파이프라인에는 거래대금 이력이 아예 없었다. 종가·거래량이 같은
# 표(네이버 frgn)에 이미 있으므로 추가 호출 없이 만든다 — range_history와 같은 자리.

def frgn_html_with_volumes():
    """거래량이 행마다 다른 표. 컬럼: 날짜0 종가1 전일비2 등락률3 거래량4 ..."""
    def row(date, close, volume):
        return (
            f'<tr><td>{date}</td><td>{close}</td><td>0</td><td>+1.00%</td>'
            f'<td>{volume}</td><td>10</td><td>20</td><td>30</td><td>3.40%</td></tr>'
        )
    return ('<table class="type2">'
            + row('2026.07.10', '1,000', '5,000')     # 최신
            + row('2026.07.09', '2,000', '3,000')
            + row('2026.07.08', '4,000', '1,000')     # 가장 오래됨
            + '</table>')


def test_amount_history_is_close_times_volume_oldest_first(monkeypatch):
    """거래대금 이력 = 종가 x 거래량, range_history와 같은 과거->최신 순서."""
    monkeypatch.setattr(data_fetcher.requests, 'get',
                        lambda url, **kw: FakeResponse(frgn_html_with_volumes()))
    w = object.__new__(DataFetcherWorker)

    d = w._get_stock_details('002990')

    assert d['amount_history'] == [4_000_000, 6_000_000, 5_000_000]
    # 종가 이력과 같은 방향이어야 짝이 맞는다.
    assert d['range_history'] == [4000, 2000, 1000]


def test_amount_history_survives_unparsable_volume(monkeypatch):
    """거래량이 깨진 행이 있어도 배치 전체를 죽이지 않는다."""
    html = ('<table class="type2">'
            '<tr><td>2026.07.10</td><td>1,000</td><td>0</td><td>+1.00%</td>'
            '<td>-</td><td>10</td><td>20</td><td>30</td><td>3.40%</td></tr>'
            '<tr><td>2026.07.09</td><td>2,000</td><td>0</td><td>+1.00%</td>'
            '<td>3,000</td><td>10</td><td>20</td><td>30</td><td>3.40%</td></tr>'
            '</table>')
    monkeypatch.setattr(data_fetcher.requests, 'get', lambda url, **kw: FakeResponse(html))
    w = object.__new__(DataFetcherWorker)

    d = w._get_stock_details('002990')

    assert d['amount_history'] == [6_000_000]
