import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.strategy.simulators.sim0_libero import classify_by_score


def test_band_bull():
    assert classify_by_score(72.0, 60.0, 35.0) == "BULL"

def test_band_bear():
    assert classify_by_score(30.0, 60.0, 35.0) == "BEAR"

def test_band_sideways():
    assert classify_by_score(50.0, 60.0, 35.0) == "SIDEWAYS"

def test_band_boundaries_inclusive():
    # 경계값은 각각 BULL/BEAR에 포함
    assert classify_by_score(60.0, 60.0, 35.0) == "BULL"
    assert classify_by_score(35.0, 60.0, 35.0) == "BEAR"


# ── AND 게이트(classify_regime) — Sim6의 유일한 입구 ──────────────
def _libero():
    from src.strategy.simulators.sim0_libero import LiberoSimulator
    return LiberoSimulator(initial_cash=0)


def test_bear_fires_on_a_weak_but_not_crashing_tape():
    """약세장인데 급락은 아닌 날도 BEAR로 잡는다.

    2026-09-15 실측: 09-03 이후 12일간 BEAR 출현이 0회였고 Sim6는 그 기간
    거래가 0건이었다. 관측 281행에서 breadth<=40은 자주 충족됐지만
    (09-10 38/40행, 09-14 26/40행) momentum이 -2.0까지 내려간 행은 1행뿐이라
    AND 게이트가 momentum 하나로 닫혀 있었다. 09-10의 최저 momentum은
    -1.88이었다 — 시장은 약했는데 등락률 중앙값이 -2%에 못 미친 날이다.
    """
    assert _libero().classify_regime(breadth=38, momentum=-1.88, trend=19) == "BEAR"


def test_bear_does_not_fire_on_a_merely_flat_tape():
    """완화가 '아무 때나 BEAR'가 되면 안 된다 — 상승장 인버스 매수는 손실이다."""
    assert _libero().classify_regime(breadth=38, momentum=-1.2, trend=19) == "SIDEWAYS"


def test_bear_still_requires_breadth_and_trend():
    """momentum만으로는 BEAR가 아니다 — 나머지 두 조건은 그대로다."""
    lib = _libero()
    assert lib.classify_regime(breadth=55, momentum=-1.88, trend=19) == "SIDEWAYS"
    assert lib.classify_regime(breadth=38, momentum=-1.88, trend=10) == "SIDEWAYS"


def test_bull_threshold_is_unchanged():
    """완화한 건 BEAR 쪽뿐이다 — BULL은 +2.0 그대로다."""
    lib = _libero()
    assert lib.classify_regime(breadth=65, momentum=1.88, trend=25) == "SIDEWAYS"
    assert lib.classify_regime(breadth=65, momentum=2.0, trend=25) == "BULL"
