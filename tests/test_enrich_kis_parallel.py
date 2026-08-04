"""E6 (2026-08-04 스크래퍼 지연 재설계): _enrich_universe의 KIS per/pbr·수급
보강을 병렬화했다. 종목당 최대 2콜(get_price_quote + get_investor_trend_estimate)을
순차로 돌면 30종목에 수십 초가 들었다 — sparkline 단계와 같은 ThreadPoolExecutor로
바꿨다.

여기서는 동시성 자체를 타이밍으로 재는 대신(불안정한 테스트가 된다), 결과가
순차 버전과 동일하고 순서가 보존되며 종목 수만큼 정확히 호출되는지를 본다 —
그게 병렬화가 깨뜨리기 쉬운 지점이다(공유 리스트 순서, 부분 실패 시 나머지 유실).
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.trade_engine import TradeEngineWorker

_QUOTE = {'price': 6000, 'change_rate_pct': 1.0, 'per': 10.0, 'pbr': 1.0, 'sector_name': '전기전자'}


def _enrich(stocks, quote_side_effect=None):
    kis = mock.MagicMock()
    if quote_side_effect is not None:
        kis.get_price_quote.side_effect = quote_side_effect
    else:
        kis.get_price_quote.return_value = _QUOTE
    kis.get_investor_trend_estimate.return_value = {}
    with mock.patch('requests.get', side_effect=OSError('네트워크 차단')), \
         mock.patch('src.trade.kis_data_provider.KISDataProvider', return_value=kis):
        return TradeEngineWorker._enrich_universe(None, stocks), kis


def test_calls_kis_once_per_stock():
    stocks = [{'code': f'{i:06d}', 'name': f'종목{i}', 'price': 1000 + i} for i in range(20)]
    out, kis = _enrich(stocks)
    assert kis.get_price_quote.call_count == 20
    assert kis.get_investor_trend_estimate.call_count == 20


def test_order_is_preserved_across_threads():
    stocks = [{'code': f'{i:06d}', 'name': f'종목{i}', 'price': 1000 + i} for i in range(15)]
    out, _ = _enrich(stocks)
    assert [s['code'] for s in out] == [s['code'] for s in stocks]


def test_partial_kis_failure_does_not_drop_other_stocks():
    """한 종목 조회가 실패해도 나머지는 정상 보강돼야 한다 — 스레드 하나가
    예외를 던져도 ex.map이 전체를 죽이면 안 된다(enrich_kis 내부 try/except가 막는다)."""
    def flaky(code):
        if code == '000005':
            raise TimeoutError('네트워크 지연')
        return _QUOTE

    stocks = [{'code': f'{i:06d}', 'name': f'종목{i}', 'price': 1000 + i} for i in range(10)]
    out, _ = _enrich(stocks, quote_side_effect=flaky)
    assert len(out) == 10
    assert out[5]['code'] == '000005' and 'per' not in out[5]  # 실패 종목만 미보강
    assert out[0].get('per') == 10.0  # 나머지는 정상 보강
