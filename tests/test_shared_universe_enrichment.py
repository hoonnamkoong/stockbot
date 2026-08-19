"""자체 유니버스 심들의 종목 보강을 한 번만 한다 — 08-19 실측 65초의 원인 수정.

Sim4/4-1/9는 완전히 같은 30종목을, Sim2/8은 77% 겹치는 종목을 각자
_enrich_universe()로 따로 보강하고 있었다. 종목코드 기준으로 합쳐 딱 한 번
보강하고 심별로 되돌려주도록 _run_simulators를 고쳤다 — 이 파일은 그 배선이
실제로 중복을 없애는지, 심마다 다른 순서/필드를 안전하게 지키는지, 그리고
**새 자체유니버스 심이 추가돼도 하드코딩 없이 자동으로 이 캐시에 낀다는 것**을
검증한다(사용자 요청: 향후 심 추가·교체 시 자동 통합·검증).
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.trade_engine import TradeEngineWorker


# ── _merge_own_universes: 순수 병합 로직 ──────────────────────────
def test_merge_dedupes_by_code():
    merged = TradeEngineWorker._merge_own_universes([
        [{'code': '005930', 'price': 71000}],
        [{'code': '005930', 'price': 71000}, {'code': '000660', 'price': 200000}],
    ])
    codes = sorted(s['code'] for s in merged)
    assert codes == ['000660', '005930']


def test_merge_unions_fields_across_sims():
    """A 심 응답엔 없는 필드가 B 심 응답에 있으면 합쳐서 살아남아야 한다."""
    merged = TradeEngineWorker._merge_own_universes([
        [{'code': '005930', 'price': 71000, 'frgn_fake_ntby_qty': 500}],
        [{'code': '005930', 'price': 71000, 'roe': 12.3}],
    ])
    row = merged[0]
    assert row['frgn_fake_ntby_qty'] == 500
    assert row['roe'] == 12.3


def test_merge_does_not_overwrite_present_value_with_falsy():
    """나중에 합쳐지는 심의 결손(0/빈값)이 먼저 채워진 참값을 지우면 안 된다.

    sim-field-plumbing-audit에서 반복적으로 잡힌 유형이다 — 필드가 조용히
    사라지면 그 필드를 쓰는 심(예: Sim8의 info축)이 원인 모를 신호 상실을 겪는다.
    """
    merged = TradeEngineWorker._merge_own_universes([
        [{'code': '005930', 'frgn_fake_ntby_qty': 500}],
        [{'code': '005930', 'frgn_fake_ntby_qty': 0}],  # 다른 심 응답의 결손
    ])
    assert merged[0]['frgn_fake_ntby_qty'] == 500


def test_merge_handles_codeless_entries_safely():
    merged = TradeEngineWorker._merge_own_universes([[{'name': '코드없음'}]])
    assert merged == []


# ── _run_simulators 통합: 실제로 한 번만 보강하는지 ────────────────
class _FakeCtx:
    now_kst = datetime(2026, 8, 19, 11, 0, tzinfo=timezone(timedelta(hours=9)))

    def is_buy_window(self):
        return True

    def is_market_hours(self):
        return True

    def should_notify(self):
        return False

    def log(self, msg):
        pass


class _FakeSim:
    IS_ANALYZER = False
    IS_EOD = False

    def __init__(self, universe=None, portfolio=None):
        self.state = {'portfolio': portfolio or {}}
        self._universe = universe or []
        self.ran_with = None

    def get_universe(self):
        return list(self._universe)  # 매번 새 리스트 — in-place 오염 감지용

    def run(self, candidates, current_prices=None):
        self.ran_with = {'candidates': candidates, 'prices': current_prices}


def _worker():
    return TradeEngineWorker(_FakeCtx(), mock.MagicMock())


def test_overlapping_sims_are_enriched_only_once():
    """Sim A·B가 같은 종목을 갖고 있으면 _enrich_universe는 한 번만 불려야 한다."""
    sim_a = _FakeSim(universe=[{'code': '005930', 'price': 71000},
                                {'code': '000660', 'price': 200000}])
    sim_b = _FakeSim(universe=[{'code': '005930', 'price': 71000},
                                {'code': '035420', 'price': 150000}])
    w = _worker()

    calls = []

    def fake_enrich(_self, stocks):
        calls.append(len(stocks))
        return stocks

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[sim_a, sim_b]), \
         mock.patch.object(TradeEngineWorker, '_enrich_universe', fake_enrich):
        w._run_simulators([])

    assert calls == [3], f'유니버스 3종목(합집합)에 대해 한 번만 불려야 한다: {calls}'
    assert sim_a.ran_with is not None
    assert sim_b.ran_with is not None


def test_each_sim_keeps_its_own_order_and_only_its_own_codes():
    """공유 풀에서 되돌려줄 때 심 자신의 순위 순서·종목만 받아야 한다."""
    sim_a = _FakeSim(universe=[{'code': '000660', 'price': 1}, {'code': '005930', 'price': 2}])
    sim_b = _FakeSim(universe=[{'code': '035420', 'price': 3}])
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[sim_a, sim_b]), \
         mock.patch.object(TradeEngineWorker, '_enrich_universe', lambda self, x: x):
        w._run_simulators([])

    a_codes = [s['code'] for s in sim_a.ran_with['candidates']]
    b_codes = [s['code'] for s in sim_b.ran_with['candidates']]
    assert a_codes == ['000660', '005930']
    assert b_codes == ['035420']


def test_mutating_one_sims_candidate_does_not_leak_to_another():
    """심마다 사본을 받아야 한다 — 한 심의 in-place 변경이 다른 심에 안 번진다."""
    sim_a = _FakeSim(universe=[{'code': '005930', 'price': 71000}])
    sim_b = _FakeSim(universe=[{'code': '005930', 'price': 71000}])
    w = _worker()

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[sim_a, sim_b]), \
         mock.patch.object(TradeEngineWorker, '_enrich_universe', lambda self, x: x):
        w._run_simulators([])

    sim_a.ran_with['candidates'][0]['price'] = 999999
    assert sim_b.ran_with['candidates'][0]['price'] == 71000


def test_sim_with_empty_universe_still_falls_back_to_buzz_pool():
    """자체 유니버스가 비면(조회 실패 등) 기존처럼 공통 버즈 후보로 대체돼야 한다."""
    sim_empty = _FakeSim(universe=[])
    w = _worker()
    buzz_candidates = [{'code': '005930', 'price': 71000}]

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[sim_empty]), \
         mock.patch.object(TradeEngineWorker, '_enrich_universe', lambda self, x: x):
        w._run_simulators(buzz_candidates)

    assert sim_empty.ran_with['candidates'] == buzz_candidates


# ── 미래 확장: 새 심이 하드코딩 없이 자동으로 캐시를 나눠 쓰는지 ────────
def test_a_brand_new_sim_type_joins_the_shared_pool_without_special_casing():
    """이름도 모양도 다른(임의의) 심 셋을 넣어도 겹치는 종목은 한 번만 보강돼야
    한다 — 특정 심 id를 조건문에 넣지 않고 get_active_simulators가 주는 목록을
    그대로 처리하기 때문이다. 향후 심이 늘거나 교체돼도 이 테스트가 그 전제를
    계속 지킨다."""

    class _BrandNewSim(_FakeSim):
        """이 테스트 시점까지 존재한 적 없는, 임의의 새 자체유니버스 심을 흉내낸다."""
        pass

    known = _FakeSim(universe=[{'code': '005930', 'price': 71000}])
    brand_new = _BrandNewSim(universe=[{'code': '005930', 'price': 71000},
                                        {'code': '999999', 'price': 500}])
    w = _worker()
    calls = []

    def fake_enrich(_self, stocks):
        calls.append(sorted(s['code'] for s in stocks))
        return stocks

    with mock.patch('src.pipeline.workers.trade_engine.get_active_simulators',
                    return_value=[known, brand_new]), \
         mock.patch.object(TradeEngineWorker, '_enrich_universe', fake_enrich):
        w._run_simulators([])

    assert calls == [['005930', '999999']], (
        '새 심 클래스가 섞여도 겹치는 005930은 한 번만, 새 심만의 999999는 '
        '자동으로 함께 보강돼야 한다')
    assert brand_new.ran_with is not None


def test_only_sim_id_path_is_unaffected_by_the_shared_pool():
    """universe_override 경로(실전 선택 심)는 공유 풀 로직을 타지 않는다 —
    이미 확정된 유니버스를 그대로 써야 실전-페이퍼 파리티가 유지된다."""
    picked = _FakeSim()
    w = _worker()
    override = [{'code': '005930', 'price': 71000}]

    with mock.patch('src.strategy.registry.get_simulator_by_id', return_value=picked), \
         mock.patch.object(TradeEngineWorker, '_enrich_universe') as enrich:
        w._run_simulators([], only_sim_id='sim4_bull_daytrading',
                          universe_override=override)

    enrich.assert_not_called()
    assert picked.ran_with['candidates'] == override
