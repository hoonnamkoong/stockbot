"""심 전용 유니버스에도 체결강도를 채운다 — 안 그러면 게이트가 전 종목을 막는다.

2026-08-13, 실전 계좌가 하루 종일 매수 0건이었다(원장 positions {}, 매 사이클
"주문 없음"). 예수금 약 100만원이 그대로 남았다.

연쇄:
  1. 08-12 22:06, "체결강도 **전량 결손**이면 면제하지 않는다"가 배포됐다
     (`BaseSimulator.validate_tick_power`). 개별 종목의 0은 종목 사정일 수 있지만
     런 전체가 0인 건 측정이 죽은 것이니 통과시키면 안 된다 — 그 자체로는 옳다.
  2. 그런데 **프로그램 경로의 유니버스에는 tick_power가 아예 없다.** 프로그램은
     스크래퍼 후보가 아니라 심 전용 유니버스(get_fluctuation_rank 30종목)를 쓰고,
     `_enrich_universe`가 per/pbr·sparkline·수급·시가/고저를 붙이는데 tick_power만
     안 붙인다(`KISDataProvider.get_tick_power`는 있는데 호출하지 않았다).
  3. → 30종목 전부 tick_power 없음 → `tick_power_outage()` = True
     → `validate_tick_power`가 tp==0에서 `not outage` = False → 전 종목 탈락.

파리티도 깨져 있었다: 스크래퍼 경로(페이퍼)는 tick_power가 있고 프로그램 경로는
없으니, 같은 심이 두 경로에서 다르게 판단한다.

없는 값을 지어내지 않는다 — 조회가 실패하면 키를 붙이지 않는다. 그러면 게이트는
여전히 막지만, 그건 '측정이 죽었다'는 사실에 근거한 차단이라 옳다.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers.trade_engine import TradeEngineWorker
from src.strategy.simulators.base_simulator import BaseSimulator

_QUOTE = {'price': 6000, 'change_rate_pct': 1.0, 'per': 10.0, 'pbr': 1.0}


def _enrich(stocks, tick_power=150.0):
    kis = mock.MagicMock()
    kis.get_price_quote.return_value = _QUOTE
    kis.get_investor_trend_estimate.return_value = {}
    if isinstance(tick_power, Exception):
        kis.get_tick_power.side_effect = tick_power
    else:
        kis.get_tick_power.return_value = tick_power
    with mock.patch('requests.get', side_effect=OSError('네트워크 차단')), \
         mock.patch('src.trade.kis_data_provider.KISDataProvider', return_value=kis):
        return TradeEngineWorker._enrich_universe(None, stocks), kis


def _universe(n=3):
    return [{'code': f'{i:06d}', 'name': f'종목{i}', 'price': 1000 + i} for i in range(n)]


def test_enrich_fills_tick_power():
    out, kis = _enrich(_universe())

    assert [s['tick_power'] for s in out] == [150.0, 150.0, 150.0]
    assert kis.get_tick_power.call_count == 3


def test_filled_universe_is_not_an_outage():
    """이게 08-13에 깨져 있던 불변식이다 — 유니버스에 값이 있어야 게이트가
    '측정 죽음'으로 오판하지 않는다."""
    out, _ = _enrich(_universe())

    assert BaseSimulator.tick_power_outage(out) is False
    assert BaseSimulator.validate_tick_power(out[0], 120.0, outage=False) is True


def test_existing_value_is_not_overwritten():
    """스크래퍼 경로로 들어온 후보는 이미 값을 갖고 있다. 덮어쓰면 그 런의
    실측을 KIS 재조회 값으로 바꿔치기하게 된다."""
    stocks = _universe(1)
    stocks[0]['tick_power'] = 88.8

    out, kis = _enrich(stocks)

    assert out[0]['tick_power'] == 88.8
    assert kis.get_tick_power.call_count == 0


def test_lookup_failure_leaves_the_key_absent():
    """조회 실패를 0으로 채우면 '체결강도가 0이다'라는 거짓이 된다.
    측정 못 한 것은 측정 못 한 채로 둔다."""
    out, _ = _enrich(_universe(1), tick_power=RuntimeError('KIS 다운'))

    assert 'tick_power' not in out[0]


def test_zero_is_recorded_as_absent_not_as_a_measurement():
    """클라이언트는 실패도 0.0으로 돌려준다(get_tick_power). 0을 값으로 적으면
    '측정 불가'와 '체결강도 0'이 합쳐진다."""
    out, _ = _enrich(_universe(1), tick_power=0.0)

    assert 'tick_power' not in out[0]
