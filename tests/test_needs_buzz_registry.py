"""E1 (2026-08-04 스크래퍼 지연 재설계): needs_buzz 마킹표와 조회 함수.

매니페스트가 유일한 원천이고, registry.needs_buzz()가 유일한 조회 창구다.
심 종류에 따라 실행 순서(매매 먼저 vs 스크래핑 먼저)를 가변시키는 E3의 입력이라
값이 확정된 표와 정확히 일치해야 한다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.registry import needs_buzz, _load_manifest


# 2026-08-04 office-hours 설계 문서에서 확정한 마킹표.
# sim9_gap_fade는 2026-08-05에 True→False로 바뀌었다: 진입신호(open_price/
# day_high/day_low/prev_close)가 버즈 텍스트를 안 쓰는데 버즈 풀(런당 16~24개)에
# 묶여 신호 빈도 추정이 틀렸다 — get_universe()를 KIS 상승률 상위로 옮겼다.
EXPECTED_STATIC = {
    'sim0_libero': False,
    'sim_psych': True,
    'sim_spillover': False,
    'sim_risk': False,
    'sim4_bull': False,
    'sim5_sideways': True,
    'sim6_bear': False,
    'sim4_bull_daytrading': False,
    'sim7_report_follower': True,
    'sim8_accumulation': False,
    'sim9_gap_fade': False,
    'sim9_1_donchian': True,
}


def test_static_marking_matches_confirmed_table():
    for sim_id, expected in EXPECTED_STATIC.items():
        assert needs_buzz(sim_id) is expected, f'{sim_id}: 마킹표와 불일치'


def test_sim10_is_dynamic_and_follows_regime():
    """Sim10은 국면에 따라 필요 여부가 바뀐다 — 상수로 마킹하면 안 된다."""
    assert needs_buzz('sim10_orchestrator', regime='BULL') is False
    assert needs_buzz('sim10_orchestrator', regime='BEAR') is False
    assert needs_buzz('sim10_orchestrator', regime='SIDEWAYS') is True


def test_sim10_unknown_regime_fails_safe_to_needs_buzz():
    """국면을 모르면(regime=None) 버즈 필요로 취급 — 스크래핑을 건너뛰었다가
    실제로는 SIDEWAYS라 유니버스가 비는 사고를 막는다."""
    assert needs_buzz('sim10_orchestrator', regime=None) is True


def test_unknown_sim_id_raises():
    import pytest
    with pytest.raises(KeyError):
        needs_buzz('no_such_sim')


def test_every_active_sim_declares_needs_buzz():
    """마킹을 빠뜨린 새 심이 조용히 fail-safe(True)로만 넘어가지 않게, 매니페스트에
    명시적으로 적혀 있는지 자체를 확인한다."""
    manifest = _load_manifest()
    missing = [s['id'] for s in manifest['simulators']
               if s.get('active', True) and 'needs_buzz' not in s]
    assert not missing, f'needs_buzz 마킹 누락: {missing}'


def test_dynamic_sims_have_classmethod():
    """needs_buzz: dynamic인 심은 반드시 needs_buzz(regime) classmethod가 있어야
    실행 시점에 죽지 않는다."""
    manifest = _load_manifest()
    dynamic_ids = [s['id'] for s in manifest['simulators'] if s.get('needs_buzz') == 'dynamic']
    assert dynamic_ids, 'dynamic 마킹 심이 없다 — Sim10이 있어야 한다'
    for sim_id in dynamic_ids:
        # 예외 없이 호출되면 충분 — registry.needs_buzz()가 내부에서 classmethod를 찾는다.
        needs_buzz(sim_id, regime='SIDEWAYS')
