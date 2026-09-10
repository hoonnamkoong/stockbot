# -*- coding: utf-8 -*-
"""네이버 JSON API 어댑터 — 모양이 틀리면 None, 값이 없으면 None.

2026-09-10 finance.naver.com이 stock.naver.com으로 302되자 HTML 파서들이
'표 없음'을 '0건'으로 냈다(EOD·프리마켓만 크게 죽고 나머지는 초록인 채 비었다).
이 파일은 같은 모양의 사고가 새 어댑터에서 재발하지 않는지 본다.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core import net
from src.data import naver_api as na


class _Res:
    def __init__(self, body=None, *, html=False, status=200):
        self._body, self._html, self.status_code = body, html, status

    def json(self):
        if self._html:
            raise ValueError('Expecting value')
        return self._body


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(net, '_STREAKS', {})
    monkeypatch.setattr(net, '_OPENED_AT', {})
    monkeypatch.setattr(net.time, 'sleep', lambda _s: None)


def _serve(monkeypatch, responder):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return responder(url, len(calls))

    monkeypatch.setattr(net.requests, 'get', fake_get)
    return calls


def _item(code, *, end='stock', price='1,000', ratio='1.50', direction='RISING',
          volume='1,234', cap='5,000', value='12'):
    return {'itemCode': code, 'stockName': f'종목{code}', 'stockEndType': end,
            'closePrice': price, 'fluctuationsRatio': ratio,
            'compareToPreviousPrice': {'name': direction},
            'accumulatedTradingVolume': volume, 'marketValue': cap,
            'accumulatedTradingValue': value}


def _list(items):
    return {'stocks': items}


# ── 이번 사고의 모양 ────────────────────────────────────────────

def test_리다이렉트_끝의_HTML은_0건이_아니라_None이다(monkeypatch):
    _serve(monkeypatch, lambda url, n: _Res(html=True))

    assert na.stock_list('marketValue', 'KOSPI', 100) is None
    assert na.investor_trend('005930') is None
    assert na.current_price('005930') is None


def test_응답_모양이_다르면_None이다(monkeypatch):
    _serve(monkeypatch, lambda url, n: _Res({'unexpected': True}))

    assert na.stock_list('marketValue', 'KOSPI', 100) is None
    assert na.investor_trend('005930') is None
    assert na.asking_price('005930') is None


def test_장전_빈_순위는_None이_아니라_빈_목록이다(monkeypatch):
    """거래량 순위는 09:00 전엔 정말로 비어 있다(2026-09-11 08:1x 실측). 실패와 다르다."""
    _serve(monkeypatch, lambda url, n: _Res({'stocks': [], 'totalCount': 0}))

    assert na.stock_list('quantTop', 'KOSPI', 100) == []


# ── 시총·거래량 목록 ────────────────────────────────────────────

def test_ETF는_뺀다(monkeypatch):
    """새 시총 목록은 ETF가 섞여 온다 — KOSPI 상위 200 중 43개(2026-09-11 실측)."""
    _serve(monkeypatch, lambda url, n: _Res(_list([
        _item('005930'), _item('069500', end='etf'), _item('000660')])))

    rows = na.stock_list('marketValue', 'KOSPI', 100)

    assert [r['code'] for r in rows] == ['005930', '000660']


def test_ETF도_원하면_남긴다(monkeypatch):
    _serve(monkeypatch, lambda url, n: _Res(_list([_item('005930'), _item('069500', end='etf')])))

    rows = na.stock_list('marketValue', 'KOSPI', 100, stock_only=False)

    assert len(rows) == 2


@pytest.mark.parametrize('ratio,direction,expected', [
    ('1.20', 'FALLING', -1.2),
    ('-1.20', 'FALLING', -1.2),
    ('29.97', 'LOWER_LIMIT', -29.97),
    ('1.20', 'RISING', 1.2),
    ('0.00', 'UNCHANGED', 0.0),
])
def test_등락률_부호는_방향으로_정한다(monkeypatch, ratio, direction, expected):
    _serve(monkeypatch, lambda url, n: _Res(_list([_item('005930', ratio=ratio,
                                                         direction=direction)])))

    assert na.stock_list('marketValue', 'KOSPI', 1)[0]['change_rate'] == expected


def test_장전_거래량_대시는_0이_아니라_None이다(monkeypatch):
    """장 시작 전 거래량은 '-'다. 0으로 적으면 '유동성 0'으로 읽힌다."""
    _serve(monkeypatch, lambda url, n: _Res(_list([_item('005930', volume='-', value='-')])))

    row = na.stock_list('marketValue', 'KOSPI', 1)[0]

    assert row['volume'] is None and row['amount'] is None


def test_단위(monkeypatch):
    _serve(monkeypatch, lambda url, n: _Res(_list([_item('005930', price='269,000',
                                                         cap='15,726,489', value='1,875')])))

    row = na.stock_list('marketValue', 'KOSPI', 1)[0]

    assert row['price'] == 269000
    assert row['market_cap'] == 15_726_489          # 억원
    assert row['amount'] == 1_875 * 1_000_000        # 백만원 → 원


def test_limit까지_페이지를_넘긴다(monkeypatch):
    full = _list([_item(f'{i:06d}') for i in range(1, 101)])
    rest = _list([_item(f'{i:06d}') for i in range(101, 201)])
    calls = _serve(monkeypatch, lambda url, n: _Res(full if n == 1 else rest))

    rows = na.stock_list('marketValue', 'KOSPI', 150)

    assert len(rows) == 150 and len(calls) == 2
    assert 'page=2' in calls[1]


def test_짧은_페이지에서_멈춘다(monkeypatch):
    calls = _serve(monkeypatch, lambda url, n: _Res(_list([_item('005930')])))

    assert len(na.stock_list('marketValue', 'KOSPI', 100)) == 1
    assert len(calls) == 1


def test_한_페이지라도_실패하면_부분목록이_아니라_None이다(monkeypatch):
    full = _list([_item(f'{i:06d}') for i in range(1, 101)])
    _serve(monkeypatch, lambda url, n: _Res(full) if n == 1 else _Res(status=503))

    assert na.stock_list('marketValue', 'KOSPI', 150) is None


def test_페이지가_밀려도_중복은_한_번만(monkeypatch):
    """장중엔 순위가 움직여 같은 종목이 두 페이지에 걸린다."""
    p1 = _list([_item(f'{i:06d}') for i in range(1, 101)])
    p2 = _list([_item('000100')] + [_item(f'{i:06d}') for i in range(101, 150)])
    _serve(monkeypatch, lambda url, n: _Res(p1 if n == 1 else p2))

    codes = [r['code'] for r in na.stock_list('marketValue', 'KOSPI', 200)]

    assert len(codes) == len(set(codes)) == 149


def test_숫자가_아닌_코드는_건너뛴다(monkeypatch):
    _serve(monkeypatch, lambda url, n: _Res(_list([_item('0015N0'), _item('005930')])))

    assert [r['code'] for r in na.stock_list('marketValue', 'KOSPI', 100)] == ['005930']


# ── 수급(옛 item/frgn) ───────────────────────────────────────────

def test_수급_행을_옛_표와_같은_재료로_준다(monkeypatch):
    _serve(monkeypatch, lambda url, n: _Res([
        {'bizdate': '20260910', 'closePrice': '269,000', 'accumulatedTradingVolume': '22,517,075',
         'organPureBuyQuant': '+4,266,985', 'foreignerPureBuyQuant': '-5,769,453',
         'foreignerHoldRatio': '46.71%'},
    ]))

    row = na.investor_trend('005930')[0]

    assert row == {'date': '20260910', 'close': 269000, 'volume': 22_517_075,
                   'organ_net': 4_266_985, 'foreign_net': -5_769_453,
                   'foreign_hold_ratio': 46.71}


def test_종가가_없는_행은_버린다(monkeypatch):
    _serve(monkeypatch, lambda url, n: _Res([{'bizdate': '20260910', 'closePrice': '-'}]))

    assert na.investor_trend('005930') == []


# ── 종토방(옛 item/board) ────────────────────────────────────────

def test_종토방_글과_다음_커서(monkeypatch):
    calls = _serve(monkeypatch, lambda url, n: _Res({'result': {
        'posts': [{'id': '429256915', 'writtenAt': '2026-09-11T08:06:22', 'title': '글',
                   'recommendCount': 3, 'writer': {'profileId': 'p1', 'nickname': 'n'}}],
        'lastOffset': '-429256484'}}))

    posts, nxt = na.discussion_page('005930', offset='-1')

    assert posts == [{'nid': '429256915', 'title': '글', 'likes': 3, 'writer': 'p1',
                      'written_at': '2026-09-11T08:06:22'}]
    assert nxt == '-429256484'
    assert 'offset=-1' in calls[0]


def test_종토방_모양이_다르면_이유를_남기고_None(monkeypatch):
    _serve(monkeypatch, lambda url, n: _Res({'isSuccess': False, 'result': None}))
    reasons = {}

    assert na.discussion_page('005930', reasons=reasons) is None
    assert reasons == {'bad_shape': 1}


def test_종토방이_HTML이면_not_json으로_센다(monkeypatch):
    _serve(monkeypatch, lambda url, n: _Res(html=True))
    reasons = {}

    assert na.discussion_page('005930', reasons=reasons) is None
    assert reasons == {'not_json': 1}


# ── 호가·현재가 ──────────────────────────────────────────────────

def test_호가_잔량(monkeypatch):
    _serve(monkeypatch, lambda url, n: _Res({'totalSell': '1,200', 'totalBuy': '400'}))

    assert na.asking_price('005930') == {'total_sell': 1200, 'total_buy': 400}


def test_현재가(monkeypatch):
    _serve(monkeypatch, lambda url, n: _Res({'closePrice': '269,000'}))

    assert na.current_price('005930') == 269000
