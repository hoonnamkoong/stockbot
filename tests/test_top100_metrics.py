import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.pipeline.workers.trade_engine import TradeEngineWorker


def _worker():
    return TradeEngineWorker.__new__(TradeEngineWorker)  # __init__ 우회, 순수 메서드만


def test_breadth_momentum_from_rates():
    w = _worker()
    breadth, momentum = w._breadth_momentum([2.0, -1.0, 3.0, -4.0])
    assert breadth == 50.0            # 2/4 상승
    assert momentum == 0.5            # median([-4,-1,2,3]) = (-1+2)/2


def test_breadth_momentum_empty_returns_none():
    assert _worker()._breadth_momentum([]) is None


def test_trend_from_csv(tmp_path):
    csv = tmp_path / "top100.csv"
    # 3종목 × 4일. A 우상향(추세강), B 톱니(추세약)
    csv.write_text(
        "date,A,B,C\n"
        "20260101,100,100,100\n"
        "20260102,110,90,100\n"
        "20260103,120,100,100\n"
        "20260104,130,90,100\n", encoding='utf-8')
    w = _worker()
    trend = w._top100_trend_from_csv(str(csv), lookback=4)
    # A: |130-100|/(10+10+10)=100, B: |90-100|/(10+10+10)=33.3, C: 0 → median=33.3
    assert 33.0 <= trend <= 34.0
