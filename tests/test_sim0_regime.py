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
