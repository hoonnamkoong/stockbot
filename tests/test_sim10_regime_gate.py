"""Sim10의 국면 라우팅 — 전략이 든 슬롯과 그 전략이 허용되는 국면이 같아야 한다.

2026-11-24 발견. 심10은 **오늘의 3단계** 국면으로 하위 전략을 골랐는데, SIDEWAYS
슬롯이 부르는 `decide_sideways`의 진입 게이트는 **어제 확정 6단계가 하락·매우하락**
일 때만 열린다(심5 `ALLOWED_REGIMES6`). 6단계 하락·매우하락은 3단계로 BEAR이고,
심10은 3단계 BEAR를 현금 슬롯으로 보냈다. **두 조건이 구조적으로 배타적이다.**

그래서 `5cabc3aa2`(2026-10-02, 약한횡보를 허용 집합에서 뺀 커밋) 이후 심10은
눌림목 진입을 한 번도 못 했다 — 마지막 매수가 그 커밋과 같은 날 10:03이다.
11-23에 국면 writer가 복구되어(PR #148) 게이트가 열린 바로 그날, 심5는 같은
함수로 5종목을 샀고 심10은 0종목이었다. **게이트가 열렸기 때문에 못 샀다.**

이 파일의 옛 버전은 그 결함을 '정상'으로 인코딩하고 있었다 — 통과 케이스
`('BEAR', 'STRONG_SIDEWAYS', True)`는 전일 하락·당일 횡보인 **전환일**만 뚫리는
경우였고 테스트는 초록이었다. 아무도 "그 날이 얼마나 오는가"를 묻지 않았다.
그래서 여기 불변식을 둔다: **눌림목 슬롯은 진입이 허용되는 국면에서만 선택된다.**
심5가 허용 집합을 또 바꾸면 심10의 라우팅이 따라 움직인다(한 축·한 소유자).

라우팅 축을 6단계 확정값 하나로 통일한다(2026-11-24 사용자 결정 A안):
  상승·매우상승 → 단타(심4-1) / 하락·매우하락 → 눌림목(심5) / 횡보계 → 현금
"""
import json
import os
import sys
import tempfile
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.program_trader import _resolve_active_tag
from src.strategy.regime_state import VALID_REGIMES6
from src.strategy.simulators import sim10_orchestrator
from src.strategy.simulators.sim0_libero import regime6_label
from src.strategy.simulators.sim10_orchestrator import Sim10OrchestratorSimulator
from src.strategy.simulators.sim5_sideways_swing import ALLOWED_REGIMES6

# 6단계 라벨을 만드는 확정 상태(`regime6_state.base`). 라벨 규칙의 정본은
# sim0_libero.regime6_label이므로, 이 픽스처가 정말 그 라벨을 만드는지 아래에서
# 직접 검증한다 — 픽스처가 내 오해를 복제하면 테스트는 초록인 채 거짓이 된다.
_BASE6 = {
    'STRONG_BEAR': {'level': -2, 'vol10': 1.0},
    'BEAR': {'level': -1, 'vol10': 1.0},
    'WEAK_SIDEWAYS': {'level': 0, 'vol10': 0.5},
    'STRONG_SIDEWAYS': {'level': 0, 'vol10': 1.5},
    'BULL': {'level': 1, 'vol10': 1.0},
    'STRONG_BULL': {'level': 2, 'vol10': 1.0},
}

# 슬롯 이름 ↔ 기대 국면. 라우팅의 기대값을 한곳에 둔다.
_SLOT_OF = {
    'STRONG_BEAR': 'sideways', 'BEAR': 'sideways',
    'WEAK_SIDEWAYS': 'cash', 'STRONG_SIDEWAYS': 'cash',
    'BULL': 'daytrade', 'STRONG_BULL': 'daytrade',
}


@pytest.mark.parametrize('r6', sorted(_BASE6))
def test_픽스처가_의도한_6단계_라벨을_만든다(r6):
    b = _BASE6[r6]
    assert regime6_label(b['level'], b['vol10']) == r6


def test_픽스처가_6단계_전부를_덮는다():
    assert set(_BASE6) == set(VALID_REGIMES6)


def _sim(tmpdir, r6=None, regime3='SIDEWAYS', prior_regime='BEAR', bull_score=71.5,
         write_libero=True, corrupt=False):
    sim = Sim10OrchestratorSimulator(initial_cash=3_000_000)
    sim.data_dir = tmpdir
    sim.state_file = os.path.join(tmpdir, 'sim_orchestrator_state.json')
    sim.log_file = os.path.join(tmpdir, 'sim_orchestrator_log.json')
    sim.csv_file = os.path.join(tmpdir, 'trade_history_sim_orchestrator.csv')
    sim.reset_state()
    sim.state['active_regime'] = prior_regime
    path = os.path.join(tmpdir, 'sim_libero_state.json')
    if corrupt:
        with open(path, 'w', encoding='utf-8') as f:
            f.write('{깨진 JSON')
        return sim
    if write_libero:
        payload = {'current_regime': regime3, 'bull_score': bull_score}
        if r6 is not None:
            # 장중 regime6는 일부러 다른 값으로 둔다 — 라우팅이 확정값(base)만 보는지 본다.
            payload['regime6'] = 'STRONG_BULL'
            payload['regime6_state'] = {'base': _BASE6[r6], 'today': None}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
    return sim


def _run_watching(sim, candidates=None, prices=None):
    """하위 전략을 감시하며 run(). 어느 것이 불렸는지로 슬롯을 판정한다."""
    with mock.patch.object(sim10_orchestrator, 'decide_bull_daytrade', return_value=[]) as bull, \
         mock.patch.object(sim10_orchestrator, 'decide_sideways', return_value=[]) as side, \
         mock.patch.object(sim10_orchestrator, 'decide_bear_cash', return_value=[]) as cash:
        sim.run(candidates or [], current_prices=prices or {})
    return {'daytrade': bull, 'sideways': side, 'cash': cash}


# ── 판단 불가면 어떤 하위 전략도 돌지 않는다 ──────────────────────────────

@pytest.mark.parametrize('setup', ['libero 없음', '깨진 JSON', '3단계 모름', '6단계 base 없음'])
def test_판단_불가면_하위_전략이_돌지_않는다(setup):
    with tempfile.TemporaryDirectory() as d:
        if setup == 'libero 없음':
            sim = _sim(d, write_libero=False)
        elif setup == '깨진 JSON':
            sim = _sim(d, corrupt=True)
        elif setup == '3단계 모름':
            sim = _sim(d, r6='BEAR', regime3='BANANA')
        else:
            sim = _sim(d, r6=None)          # regime6_state가 없다 → 라우팅 축이 없다
        called = _run_watching(sim)
        assert not any(m.called for m in called.values())


@pytest.mark.parametrize('setup', ['libero 없음', '6단계 base 없음'])
def test_판단_불가면_귀속_태그를_덮어쓰지_않는다(setup):
    """실거래 턴 회계가 이 값들을 손익 귀속 태그로 읽는다 — 지어낸 값을 박으면 안 된다."""
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, write_libero=(setup != 'libero 없음'), r6=None, prior_regime='BEAR')
        _run_watching(sim)
        assert sim.state['active_regime'] == 'BEAR'
        assert 'active_slot' not in sim.state


# ── 라우팅 축은 6단계 확정값이다 ──────────────────────────────────────────

@pytest.mark.parametrize('r6', sorted(_BASE6))
def test_6단계가_슬롯을_정한다(r6):
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, r6=r6)
        called = _run_watching(sim)
        assert called[_SLOT_OF[r6]].called, f'{r6} → {_SLOT_OF[r6]} 슬롯이어야 한다'
        assert [k for k, m in called.items() if m.called] == [_SLOT_OF[r6]]
        assert sim.state['active_slot'] == _SLOT_OF[r6]


@pytest.mark.parametrize('regime3', ['BULL', 'SIDEWAYS', 'BEAR'])
def test_오늘_3단계는_슬롯을_바꾸지_않는다(regime3):
    """회귀: 전에는 3단계가 슬롯을 골라서, 6단계 하락(게이트 열림)이 3단계 BEAR와
    만나면 현금 슬롯으로 갔다. 그래서 게이트가 열린 날에 못 샀다."""
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, r6='BEAR', regime3=regime3)
        called = _run_watching(sim)
        assert called['sideways'].called
        assert not called['cash'].called


def test_3단계와_bull_score는_그대로_기록된다():
    """라우팅에서는 빠졌지만 대시보드·리포트가 읽는 값이라 계속 남긴다."""
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, r6='BEAR', regime3='SIDEWAYS', bull_score=71.5)
        _run_watching(sim)
        assert sim.state['active_regime'] == 'SIDEWAYS'
        assert sim.state['active_bull_score'] == 71.5


# ── 불변식: 눌림목 슬롯은 진입이 허용되는 국면에서만 선택된다 ──────────────
#
# 이것이 2026-11-24에 찾은 결함 그 자체다. 34/38일 동안 decide_sideways가
# allow_entry=False로 불렸다 — 전략은 돌지만 살 수 없는 상태였다.

@pytest.mark.parametrize('r6', sorted(_BASE6))
def test_눌림목이_불리면_진입은_반드시_허용된다(r6):
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, r6=r6)
        side = _run_watching(sim)['sideways']
        if side.called:
            assert side.call_args.kwargs['allow_entry'] is True, (
                f'{r6}에서 눌림목이 진입 금지로 불렸다 — 살 수 없는 전략을 돌리는 것이다')


@pytest.mark.parametrize('r6', sorted(ALLOWED_REGIMES6))
def test_심5_게이트가_열리는_국면은_모두_눌림목_슬롯이다(r6):
    """소유자는 심5다. 심5가 허용 집합을 바꾸면 심10 라우팅이 따라 움직여야 한다 —
    2026-10-02에 약한횡보가 빠졌을 때 심10만 뒤에 남아 53일 침묵했다."""
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, r6=r6)
        assert _run_watching(sim)['sideways'].called


@pytest.mark.parametrize('r6', sorted(set(_BASE6) - set(ALLOWED_REGIMES6)))
def test_진입이_막힌_국면에서는_눌림목을_부르지_않는다(r6):
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, r6=r6)
        assert not _run_watching(sim)['sideways'].called


# ── 실제로 사는지 ────────────────────────────────────────────────────────
# 11-23 재현: 심5가 같은 함수로 5종목 산 그 국면에서 심10도 사야 한다.

_BOX = [1100, 1200, 1150, 1200, 1100, 1180, 1050, 1160, 1100, 1200,
        1150, 1190, 1100, 1160, 1080, 1060, 1040, 1025, 1010, 1000]


def _box_cand():
    return [{'code': '222', 'name': '레인지', 'price': 1000, 'amount': 2_000_000_000,
             'price_history': [{'date': f'202010{i + 1:02d}', 'close': c} for i, c in enumerate(_BOX)], 'change_rate': '+0.5%'}]


@pytest.mark.parametrize('r6', sorted(ALLOWED_REGIMES6))
def test_하락계에서는_박스권_저점을_실제로_산다(r6):
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, r6=r6, regime3='BEAR')
        sim.run(_box_cand(), current_prices={'222': 1000})
        assert '222' in sim.state['portfolio']


@pytest.mark.parametrize('r6', ['WEAK_SIDEWAYS', 'STRONG_SIDEWAYS'])
def test_횡보계에서는_같은_후보를_사지_않는다(r6):
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, r6=r6, regime3='SIDEWAYS')
        sim.run(_box_cand(), current_prices={'222': 1000})
        assert sim.state['portfolio'] == {}


# ── 청산 ────────────────────────────────────────────────────────────────

def _held(code, qty=10, avg=1000):
    return {code: {'name': code, 'quantity': qty, 'avg_price': avg, 'peak_price': avg,
                   'entry_date': '2026-09-28', 'is_scaled_out': False}}


def _with_holdings(sim, portfolio):
    sim.state['portfolio'] = portfolio
    sim.state['invested'] = sum(p['quantity'] * p['avg_price'] for p in portfolio.values())
    sim.state['cash'] = 3_000_000 - sim.state['invested']
    return sim


@pytest.mark.parametrize('r6', sorted(ALLOWED_REGIMES6))
def test_하락계에서_손절은_항상_나간다(r6):
    with tempfile.TemporaryDirectory() as d:
        sim = _with_holdings(_sim(d, r6=r6), _held('005930'))
        sim.run([], current_prices={'005930': 940})
        assert '005930' not in sim.state['portfolio']


@pytest.mark.parametrize('r6', ['WEAK_SIDEWAYS', 'STRONG_SIDEWAYS'])
def test_횡보계는_보유분을_전량_청산한다(r6):
    """A안 결정: 횡보계는 현금 대기다(10-01의 BEAR 현금 결정을 이 축으로 옮긴 것)."""
    with tempfile.TemporaryDirectory() as d:
        sim = _with_holdings(_sim(d, r6=r6), {**_held('005930'), **_held('114800', avg=6000)})
        sim.run([], current_prices={'005930': 1000, '114800': 6000})
        assert sim.state['portfolio'] == {}


@pytest.mark.parametrize('r6', ['WEAK_SIDEWAYS', 'STRONG_SIDEWAYS'])
def test_가격을_모르는_종목은_팔지_않는다(r6):
    with tempfile.TemporaryDirectory() as d:
        sim = _with_holdings(_sim(d, r6=r6), {**_held('005930'), **_held('000660')})
        sim.run([], current_prices={'005930': 1000})
        assert '000660' in sim.state['portfolio']
        assert '005930' not in sim.state['portfolio']


# ── 원장 귀속 태그 ───────────────────────────────────────────────────────

@pytest.mark.parametrize('slot,tag', [
    ('daytrade', 'sim4_bull_daytrading'),
    ('sideways', 'sim5_sideways'),
    ('cash', 'sim6'),
])
def test_턴_태그는_슬롯을_따른다(slot, tag):
    assert _resolve_active_tag('sim10_orchestrator', {'active_slot': slot}) == tag


def test_슬롯이_없는_옛_스냅샷은_3단계로_폴백한다():
    """이 변경 전에 쓰인 스냅샷에는 active_slot이 없다 — 원장을 거슬러 읽을 수 있어야 한다."""
    assert _resolve_active_tag('sim10_orchestrator',
                               {'active_regime': 'SIDEWAYS'}) == 'sim5_sideways'


def test_슬롯이_이기고_3단계는_무시된다():
    assert _resolve_active_tag('sim10_orchestrator',
                               {'active_slot': 'cash',
                                'active_regime': 'BULL'}) == 'sim6'


def test_다른_심은_자기_id가_태그다():
    assert _resolve_active_tag('sim_risk', {'active_slot': 'cash'}) == 'sim_risk'


# ── 라우팅 축을 기록에 남긴다 ────────────────────────────────────────────

def test_국면_기록에_6단계와_슬롯이_남는다():
    """2026-11-24 조사에서 regime_log에 3단계·bull_score만 있어 라우팅 축을 코드로
    재구성해야 했다. 다음 사람은 로그만 보고 알 수 있어야 한다."""
    with tempfile.TemporaryDirectory() as d:
        sim = _sim(d, r6='BEAR', regime3='SIDEWAYS')
        _run_watching(sim)
        row = sim.state['regime_log'][-1]
        assert row['regime6'] == 'BEAR'
        assert row['slot'] == 'sideways'
