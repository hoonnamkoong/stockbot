"""Sim8 군중축 — 유니버스를 바꾸면 z 기반 조건이 무너진다.

심8의 가설은 '정보거래자는 이미 사는데 군중은 아직 안 왔다'이다. 군중축은
그 '아직 안 왔다'를 재는 축이라 매집 단계의 필수 조건이다.

유니버스를 외인·기관 순매수 상위로 바꾸면 unique_posters(버즈 파이프라인
전용)가 후보에 없다. 기존 구현은 횡단면 z가 음수일 것을 요구했는데,
  · 값이 전부 없으면(0) 표준편차가 0이라 _zmap이 빈 dict를 준다 → cv가 None
  · cv가 None이면 매집 진입이 통째로 막힌다(돌파만 남는다)
즉 z 자체가 이 유니버스에서 표현력이 없다.

그래서 절대 기준으로 바꾼다: 버즈 유니버스의 관심 중앙값 미만이면 '군중
미도달'이다. 버즈 유니버스에서 돌 때도 의미가 같고(평균/중앙값 미만 = 관심
적음), 분포가 퇴화해도 무너지지 않는다.

순위 유니버스 종목이 버즈 목록에 아예 없다는 것은 지어낸 값이 아니라 측정이다
— 그 종목은 사람들이 글을 안 쓰고 있다.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.sim8_accumulation import (
    AccumulationSimulator, decide_accumulation, crowd_reference,
)

MIN_SAMPLE_N = 15


def _view(attention=None, median=None, nav=3_000_000):
    return {'portfolio': {}, 'cash': nav, 'initial_cash': 3_000_000, 'nav': nav,
            'cooldown_codes': {}, 'market_index_healthy': True,
            'buzz_attention': attention if attention is not None else {},
            'buzz_median': median}


def _cands(n=MIN_SAMPLE_N, near=0.90, **over):
    """앵커 구간 + info 축이 살아나도록 분산을 준 후보들."""
    out = []
    for i in range(1, n + 1):
        hi = 10000
        # 거래대금에 분산을 준다 — 전부 같으면 _zmap이 퇴화해 돌파 조건의
        # 거래대금 z가 None이 되고 돌파 경로가 통째로 막힌다.
        out.append({'code': f'{i:06d}', 'name': f'종목{i}', 'price': hi * near,
                    'amount': 2_000_000_000 + i * 500_000_000,
                    'w52_hgpr': hi, 'w52_lwpr': hi * 0.4,
                    'frgn_fake_ntby_qty': 1000 * i, 'orgn_fake_ntby_qty': 500 * i,
                    'foreign_change': i * 0.05})
    out[-1].update(over)   # 마지막 종목이 정보축 최상위
    return out


def _prices(cands):
    return {c['code']: c['price'] for c in cands}


# ── 관심 기준선 산출 ───────────────────────────────────────
def test_crowd_reference_reads_buzz_file():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, 'latest_stocks.json'), 'w', encoding='utf-8') as f:
            json.dump([{'code': 'A', 'unique_posters': 10},
                       {'code': 'B', 'unique_posters': 30},
                       {'code': 'C', 'unique_posters': 50}], f)
        attention, median = crowd_reference(d)
        assert attention == {'A': 10, 'B': 30, 'C': 50}
        assert median == 30


def test_crowd_reference_returns_none_when_unreadable():
    """읽지 못하면 '군중 미도달'을 판정할 수 없다 — 지어내지 않는다."""
    with tempfile.TemporaryDirectory() as d:
        assert crowd_reference(d) == ({}, None)


def test_crowd_reference_ignores_rows_without_attention():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, 'latest_stocks.json'), 'w', encoding='utf-8') as f:
            json.dump([{'code': 'A'}, {'code': 'B', 'unique_posters': 0}], f)
        assert crowd_reference(d) == ({}, None)


# ── 매집 진입: 군중 미도달일 때만 ───────────────────────────
def test_accumulation_enters_when_stock_absent_from_buzz():
    """순위 유니버스 종목이 버즈 목록에 없다 = 군중 미도달 = 매집 대상."""
    cands = _cands()
    orders = decide_accumulation(_view(attention={'999999': 100}, median=100),
                                 cands, _prices(cands))
    assert orders, '군중 미도달인데 매집이 안 나갔다'
    assert all('매집' in o['reason'] for o in orders)


def test_accumulation_blocked_when_crowd_already_arrived():
    """이미 군중이 붙은 종목은 '선행'이 아니다."""
    cands = _cands()
    hot = {c['code']: 500 for c in cands}
    assert decide_accumulation(_view(attention=hot, median=100), cands, _prices(cands)) == []


def test_accumulation_blocked_when_crowd_unmeasurable():
    """기준선을 못 구하면 매집은 하지 않는다(돌파 경로는 별도로 살아 있다)."""
    cands = _cands()
    assert decide_accumulation(_view(attention={}, median=None), cands, _prices(cands)) == []


def test_degenerate_attention_no_longer_blocks_entry():
    """회귀 고정 — 전 종목 관심이 0이어도(분산 0) 매집이 막히면 안 된다.

    z 기반 구현이 정확히 여기서 무너졌다: 표준편차 0 → _zmap이 빈 dict →
    cv가 None → 매집 전면 차단.
    """
    cands = _cands()
    zero = {c['code']: 0 for c in cands}
    orders = decide_accumulation(_view(attention=zero, median=100), cands, _prices(cands))
    assert orders, '관심 분산이 0이라고 매집이 막히면 안 된다'
    assert all('매집' in o['reason'] for o in orders)


# ── 돌파 경로는 군중축과 무관 ──────────────────────────────
def test_breakout_does_not_need_crowd():
    """신고가 돌파는 이미 군중이 알아챈 뒤라 군중축을 보지 않는다."""
    cands = _cands(near=1.02)
    orders = decide_accumulation(_view(attention={}, median=None), cands, _prices(cands))
    assert orders, '기준선이 없어도 돌파는 나가야 한다'
    assert all('돌파' in o['reason'] for o in orders)


# ── run()이 기준선을 뷰에 넣는다 ───────────────────────────
def test_run_injects_crowd_reference_into_view():
    with tempfile.TemporaryDirectory() as d:
        sim = AccumulationSimulator(initial_cash=3_000_000)
        sim.data_dir = d
        sim.state_file = os.path.join(d, 's.json')
        sim.log_file = os.path.join(d, 'l.json')
        sim.csv_file = os.path.join(d, 't.csv')
        sim.reset_state()
        with open(os.path.join(d, 'latest_stocks.json'), 'w', encoding='utf-8') as f:
            json.dump([{'code': 'X', 'unique_posters': 40}], f)
        cands = _cands()
        sim.run(cands, current_prices=_prices(cands))
        assert sim.state['portfolio'], 'run()이 기준선을 넣어주지 않아 매집이 막혔다'
