import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers import data_fetcher
from src.pipeline.workers.data_fetcher import DataFetcherWorker


def _row(date, close, volume=1, hold=3.4):
    """네이버 일별 수급 행(naver_api.investor_trend) — 최신이 앞."""
    return {'date': date, 'close': close, 'volume': volume, 'organ_net': 10,
            'foreign_net': 20, 'foreign_hold_ratio': hold}


def _serve(monkeypatch, rows):
    monkeypatch.setattr(data_fetcher.naver_api, 'investor_trend', lambda code, **kw: rows)
    monkeypatch.setattr(data_fetcher.naver_api, 'asking_price', lambda code, **kw: None)


def _worker():
    w = object.__new__(DataFetcherWorker)
    w.kis = None
    return w


def test_current_price_is_parsed(monkeypatch):
    """거래상위에서 빠진 종목도 현재가를 얻어야 한다."""
    _serve(monkeypatch, [_row('20260710', 17940, hold=3.47), _row('20260709', 17310, hold=3.40)])

    d = _worker()._get_stock_details('002990')

    assert d['current_price'] == 17940
    assert d['prev_close'] == 17310
    assert d['foreign_change'] == 0.07


# 2026-08-26 — Sim9-1(돈치안)의 "거래대금 동반" 게이트가 절대 거래대금의 횡단면
# z라서 대형주 필터로 동작했다. 급증을 제대로 재려면 그 종목 **자신의 평균**이
# 필요한데 국내 파이프라인에는 거래대금 이력이 아예 없었다. 종가·거래량이 같은
# 수급 표에 이미 있으므로 추가 호출 없이 만든다 — range_history와 같은 자리.

def test_amount_history_is_close_times_volume_oldest_first(monkeypatch):
    """거래대금 이력 = 종가 x 거래량, range_history와 같은 과거->최신 순서."""
    _serve(monkeypatch, [_row('20260710', 1000, 5000), _row('20260709', 2000, 3000),
                         _row('20260708', 4000, 1000)])

    d = _worker()._get_stock_details('002990')

    assert d['amount_history'] == [4_000_000, 6_000_000, 5_000_000]
    # 종가 이력과 같은 방향이어야 짝이 맞는다.
    assert d['range_history'] == [4000, 2000, 1000]


def test_amount_history_survives_missing_volume(monkeypatch):
    """거래량이 빈 행이 있어도 배치 전체를 죽이지 않는다."""
    _serve(monkeypatch, [_row('20260710', 1000, None), _row('20260709', 2000, 3000)])

    d = _worker()._get_stock_details('002990')

    assert d['amount_history'] == [6_000_000]


def test_unreachable_trend_leaves_fields_unset(monkeypatch):
    """못 닿으면 이력을 지어내지 않는다. 예전 코드는 이 경로에서
    정의되지 않은 이름(`result`)을 반환하다 NameError로 빠져나갔다."""
    _serve(monkeypatch, None)

    d = _worker()._get_stock_details('002990')

    assert d['current_price'] == 0
    assert 'range_history' not in d and 'amount_history' not in d
