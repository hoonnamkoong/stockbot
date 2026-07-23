import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.pipeline.workers.trade_engine import breadth_from_csv_text


HEADER = "date,A,B,C,D"
# 전일 대비: A↑ B↓ C↑ D↑ → 3/4 상승 = 75.0%
PREV = "20260721,100,200,300,400"
CURR = "20260722,110,190,330,440"


def test_fresh_csv_returns_breadth():
    text = "\n".join([HEADER, PREV, CURR])
    assert breadth_from_csv_text(text, "20260722") == 75.0


def test_stale_csv_returns_none():
    """마지막 행 날짜가 기대일과 다르면 stale → None (가짜 정답 금지)."""
    text = "\n".join([HEADER, PREV, CURR])
    assert breadth_from_csv_text(text, "20260723") is None


def test_insufficient_rows_returns_none():
    text = "\n".join([HEADER, CURR])
    assert breadth_from_csv_text(text, "20260722") is None


def test_zero_prev_columns_skipped():
    """전일가 0/결측 컬럼은 분모에서 제외."""
    prev = "20260721,0,200,300"
    curr = "20260722,110,190,330"  # B↓ C↑ → 유효 2개 중 1 상승 = 50%
    text = "\n".join(["date,A,B,C", prev, curr])
    assert breadth_from_csv_text(text, "20260722") == 50.0
