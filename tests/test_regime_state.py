"""국면 상태를 읽는 창구가 하나이고, 실패를 값으로 둔갑시키지 않는지 지킨다.

Sim0가 쓴 국면 파일의 소비자가 넷이다(Sim6·Sim10의 매매 게이트, 파이프라인
Stage 3.6, 월간 엑셀). 넷이 각자 파일명을 적고 각자 json.load를 하던 것을
src/strategy/regime_state.py 하나로 모았다.

여기서 보는 것은 둘이다 —
  ① 못 읽었을 때 None인가(SIDEWAYS·50점으로 뭉개지 않는가)
  ② 파일명이 매니페스트에서 오는가
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.regime_state import (  # noqa: E402
    read_regime, read_regime_state, regime_state_filename,
)


def _write(tmp_path, payload):
    path = tmp_path / regime_state_filename()
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return str(tmp_path)


# ── ① 실패는 값이 아니다 ──────────────────────────────────────────────

def test_missing_file_is_none_not_a_regime(tmp_path):
    """없는 파일을 SIDEWAYS로 읽으면 Sim6이 보유 인버스를 시장가로 턴다."""
    assert read_regime(str(tmp_path)) == (None, None)
    assert read_regime_state(str(tmp_path)) is None


def test_corrupt_file_is_none(tmp_path):
    (tmp_path / regime_state_filename()).write_text('{절반만 쓰다 만 파일', encoding='utf-8')
    assert read_regime(str(tmp_path)) == (None, None)


def test_unknown_regime_value_is_none(tmp_path):
    """오타·새 값이 그대로 흘러가면 호출자의 == 비교가 전부 빗나간다."""
    d = _write(tmp_path, {'current_regime': 'BANANA', 'bull_score': 80})
    assert read_regime(d)[0] is None


def test_missing_bull_score_is_none_not_fifty(tmp_path):
    """50점은 '보통 장'이라는 주장이다 — 모르는 것과 다르다.

    Stage 3.6이 이 값을 45와 비교해 실제 매수를 결정한다. 폴백 50.0이 있던
    시절에는 조회가 실패한 날에도 지어낸 점수로 강력매수 종목을 샀다.
    """
    d = _write(tmp_path, {'current_regime': 'BULL'})
    assert read_regime(d) == ('BULL', None)


def test_non_numeric_bull_score_is_none(tmp_path):
    d = _write(tmp_path, {'current_regime': 'BULL', 'bull_score': '알 수 없음'})
    assert read_regime(d)[1] is None


def test_reads_valid_state(tmp_path):
    d = _write(tmp_path, {'current_regime': 'BEAR', 'bull_score': 21.5,
                          'metrics': {'breadth_score': 30}})
    assert read_regime(d) == ('BEAR', 21.5)
    assert read_regime_state(d)['metrics']['breadth_score'] == 30


# ── ② 파일명은 매니페스트에서 온다 ────────────────────────────────────

def test_filename_comes_from_the_manifest():
    from src.strategy.registry import get_sim_registry
    analyzers = [s for s in get_sim_registry(include_analyzers=True) if s['analyzer']]
    assert regime_state_filename() == analyzers[0]['state_file']


def test_two_analyzers_is_an_error(monkeypatch):
    """분석기가 둘이면 '어느 국면이냐'는 질문에 답이 없다 — 조용히 첫 번째를 고르지 않는다."""
    import src.strategy.regime_state as rs
    monkeypatch.setattr(rs, 'get_sim_registry', lambda **kw: [
        {'analyzer': True, 'id': 'sim0_libero', 'state_file': 'a.json'},
        {'analyzer': True, 'id': 'sim0_shadow', 'state_file': 'b.json'},
    ])
    with pytest.raises(ValueError, match='분석기 심이 2개'):
        rs.regime_state_filename()


# ── ③ 인계값(REGIME_HINT)이 파일보다 우선한다 ─────────────────────────
# trade_loop이 dispatch inputs로 실어 보낸 국면이다. 파일로만 읽으면 스크래퍼는
# **정상 경로에서 항상** 한 격자 낡은 값을 본다(체크아웃 +30초 < 배포 +75초).
# 소유권 판정만 인계값을 쓰고 심들은 파일을 읽던 시절, 국면 전환 격자에서 Sim10이
# 이전 국면의 하위 전략·유니버스로 실주문을 냈다.

def test_hint_wins_over_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv('REGIME_HINT', 'BEAR')
    d = _write(tmp_path, {'current_regime': 'BULL', 'bull_score': 71.0})
    # bull_score는 인계 대상이 아니다 — 파일값을 그대로 쓴다(지어내지 않는다).
    assert read_regime(d) == ('BEAR', 71.0)


def test_unknown_hint_is_ignored(tmp_path, monkeypatch):
    """오타·빈 문자열이 파일값을 밀어내면 국면이 통째로 사라진다."""
    d = _write(tmp_path, {'current_regime': 'BULL', 'bull_score': 71.0})
    for bad in ('BANANA', '', '   '):
        monkeypatch.setenv('REGIME_HINT', bad)
        assert read_regime(d) == ('BULL', 71.0)


def test_hint_works_without_a_file(tmp_path, monkeypatch):
    """스크래퍼가 db-data를 못 받은 런에서도 인계값만으로 국면을 안다."""
    monkeypatch.setenv('REGIME_HINT', 'SIDEWAYS')
    assert read_regime(str(tmp_path)) == ('SIDEWAYS', None)


def test_sim10_sees_the_hint(tmp_path, monkeypatch):
    """이 테스트가 A2의 본체다 — 인계값이 소유권 판정에서 멈추면 안 된다."""
    from src.strategy.simulators.sim10_orchestrator import Sim10OrchestratorSimulator
    monkeypatch.setenv('REGIME_HINT', 'BEAR')
    sim = Sim10OrchestratorSimulator.__new__(Sim10OrchestratorSimulator)
    sim.data_dir = _write(tmp_path, {'current_regime': 'BULL', 'bull_score': 71.0})
    assert sim._read_regime() == ('BEAR', 71.0)


def test_sim6_sees_the_hint(tmp_path, monkeypatch):
    from src.strategy.simulators.sim6_bear_hedge import BearHedgeSimulator
    monkeypatch.setenv('REGIME_HINT', 'BEAR')
    sim = BearHedgeSimulator.__new__(BearHedgeSimulator)
    sim.data_dir = _write(tmp_path, {'current_regime': 'BULL', 'bull_score': 71.0})
    assert sim._read_regime() == 'BEAR'


# ── 소비자가 계약을 유지하는가 ────────────────────────────────────────

def test_sim6_returns_regime_only(tmp_path):
    """Sim6의 _read_regime은 여전히 스칼라다(run()이 그렇게 쓴다)."""
    from src.strategy.simulators.sim6_bear_hedge import BearHedgeSimulator
    sim = BearHedgeSimulator.__new__(BearHedgeSimulator)
    sim.data_dir = _write(tmp_path, {'current_regime': 'BEAR', 'bull_score': 10})
    assert sim._read_regime() == 'BEAR'


def test_sim10_returns_tuple_and_keeps_its_bull_score_default(tmp_path):
    """Sim10은 튜플이고, 국면을 아는데 점수만 없으면 기록용 50.0으로 채운다."""
    from src.strategy.simulators.sim10_orchestrator import Sim10OrchestratorSimulator
    sim = Sim10OrchestratorSimulator.__new__(Sim10OrchestratorSimulator)
    sim.data_dir = _write(tmp_path, {'current_regime': 'BULL'})
    assert sim._read_regime() == ('BULL', 50.0)
    sim.data_dir = _write(tmp_path, {'current_regime': 'BANANA', 'bull_score': 99})
    assert sim._read_regime() == (None, None)
