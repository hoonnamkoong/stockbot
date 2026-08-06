"""Sim6가 6주 넘게 거래 0건이던 원인 — 고정 유니버스에 등락률이 안 붙는다.

Sim6의 유니버스는 하드코딩 리터럴({'code','name'} 두 개뿐)이라 파이프라인
후보와 달리 change_rate가 없다. 그런데 진입 조건이 `daily_change > 0`이라
parse_change_rate가 돌려주는 0.0이 조건을 영원히 거짓으로 만든다.
Sim0가 BEAR를 5연속 판정해 게이트가 열려 있어도 매수가 구조적으로 불가능했다.

Sim2·Sim4는 유니버스를 KIS 순위 API에서 받아 change_rate가 이미 들어 있어
같은 결함이 드러나지 않았다.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.trade_engine import TradeEngineWorker
from src.strategy.simulators.sim6_bear_hedge import decide_sim6


def _enrich(stocks, quote):
    """네이버는 죽이고 KIS만 살린 상태로 _enrich_universe를 돌린다.

    _enrich_universe는 self를 전혀 쓰지 않으므로 None으로 호출한다.
    """
    kis = mock.MagicMock()
    kis.get_price_quote.return_value = quote
    kis.get_investor_trend_estimate.return_value = {}
    with mock.patch('requests.get', side_effect=OSError('네트워크 차단')), \
         mock.patch('src.trade.kis_data_provider.KISDataProvider', return_value=kis):
        return TradeEngineWorker._enrich_universe(None, stocks)


_GOOD_QUOTE = {'price': 6000, 'change_rate_pct': 3.21, 'per': 0.0, 'pbr': 0.0, 'sector_name': ''}
_FAILED_QUOTE = {'price': 0, 'change_rate_pct': 0.0, 'per': 0.0, 'pbr': 0.0, 'sector_name': ''}


def test_enrich_attaches_change_rate_from_kis():
    """고정 유니버스에도 등락률이 붙어야 한다. 출처는 KIS 현재가(prdy_ctrt)다.

    네이버 frgn 페이지는 일봉 행이라 장중엔 전일 값이 박제될 수 있다 —
    Sim6가 과거에 걸렸던 함정이 정확히 그것이라 실시간 시세를 쓴다.
    """
    out = _enrich([{'code': '114800', 'name': 'KODEX 인버스'}], _GOOD_QUOTE)
    assert out[0]['change_rate'] == '+3.21%'


def test_enrich_formats_negative_change_rate():
    out = _enrich([{'code': '114800', 'name': 'KODEX 인버스'}],
                  dict(_GOOD_QUOTE, change_rate_pct=-2.5))
    assert out[0]['change_rate'] == '-2.50%'


def test_enrich_does_not_fabricate_change_rate_when_quote_fails():
    """조회 실패를 0%로 채우면 '보합'이라는 거짓을 만든다 — 키를 안 붙인다."""
    out = _enrich([{'code': '114800', 'name': 'KODEX 인버스'}], _FAILED_QUOTE)
    assert 'change_rate' not in out[0]


def test_enrich_does_not_overwrite_existing_change_rate():
    """KIS 순위 API에서 온 유니버스(Sim2·Sim4)의 값을 덮어쓰면 안 된다."""
    out = _enrich([{'code': '005930', 'name': '삼성전자', 'change_rate': '+1.00%'}],
                  dict(_GOOD_QUOTE, change_rate_pct=9.99))
    assert out[0]['change_rate'] == '+1.00%'


# ── 결함이 실제로 Sim6 진입을 막았다는 증거 ────────────────────
def _inverse(**kw):
    """enrich를 통과한 뒤의 인버스 ETF. 완벽한 상승 추세(=시장 급락)."""
    s = {'code': '114800', 'name': 'KODEX 인버스', 'price': 6000, 'current_price': 6000,
         'sparkline_price': [5000, 5200, 5500, 5800, 6000]}
    s.update(kw)
    return s


def _view():
    return {'portfolio': {}, 'cash': 3_000_000, 'cooldown_codes': {}}


def test_sim6_cannot_buy_without_change_rate():
    """회귀 고정 — 등락률이 빠지면 아무리 좋은 추세라도 주문이 0이다."""
    assert decide_sim6(_view(), [_inverse()], {'114800': 6000}) == []


def test_sim6_buys_when_change_rate_present():
    orders = decide_sim6(_view(), [_inverse(change_rate='+3.21%')], {'114800': 6000})
    assert [(o['action'], o['code']) for o in orders] == [('BUY', '114800')]
    assert orders[0]['quantity'] > 0


def test_enriched_universe_feeds_sim6_end_to_end():
    """enrich 산출물을 그대로 Sim6에 넣으면 매수가 나온다 — 배선 전체를 묶는다."""
    enriched = _enrich([{'code': '114800', 'name': 'KODEX 인버스'}], _GOOD_QUOTE)
    enriched[0].update(price=6000, sparkline_price=[5000, 5200, 5500, 5800, 6000])
    orders = decide_sim6(_view(), enriched, {'114800': 6000})
    assert [(o['action'], o['code']) for o in orders] == [('BUY', '114800')]


def test_sim10_bear_universe_gets_change_rate_too():
    """Sim10도 BEAR 국면에 같은 리터럴 유니버스로 decide_sim6을 재사용한다 —
    같은 결함을 공유하고 있었으므로 두 번째 소비자도 고정한다."""
    from src.strategy.simulators.sim10_orchestrator import INVERSE_UNIVERSE
    out = _enrich([dict(e) for e in INVERSE_UNIVERSE], _GOOD_QUOTE)
    assert all('change_rate' in s for s in out)


# ── 중복 가드가 매매 주기를 삼키지 않는다 ──────────────────────
# 이 가드는 주기를 따라와야 하는 값이다. 실측으로 두 번 데인 적이 있다:
#   2026-07-29 — 15분 가드 + 10분 주기 → 실행이 20분마다로 반토막
#   2026-08-06 — 5분 가드 + 2분 주기(태스커 단축)면 t=0,6,12만 통과해 실효 6분
# 지금은 trading_lite.yml이 2분 주기로 매매를 낸다.
def _ran_ago(minutes):
    from src.pipeline.workers.program_trader import _recently_ran
    now = datetime.now(timezone(timedelta(hours=9)))
    return _recently_ran({'last_run': (now - timedelta(minutes=minutes)).isoformat()}, now)


def test_dup_guard_allows_two_minute_cadence():
    """trading_lite는 2분 주기다. 가드가 그보다 길면 매 사이클이 skip된다."""
    assert _ran_ago(2) is False


def test_dup_guard_allows_ten_minute_cadence():
    """스크래퍼(10분) 경로도 그대로 통과한다."""
    assert _ran_ago(10) is False


def test_dup_guard_blocks_duplicate_dispatch():
    """같은 트리거가 두 번 들어오는 것(수초~1분)은 계속 막는다."""
    assert _ran_ago(0.5) is True
