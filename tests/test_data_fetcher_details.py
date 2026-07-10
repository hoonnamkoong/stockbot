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
