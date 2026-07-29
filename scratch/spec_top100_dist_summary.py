"""Sim0 학습로그 Phase A — top100 단면 분포 요약(Ⓐ)의 **미구현 스펙**.

동결하려던 피처: 임계별 breadth·모멘트·분위·꼬리. 종목별 정체성은 제외(국면 목적).

⚠ TradeEngineWorker._dist_summary는 아직 존재하지 않는다. git 히스토리 전체에도
   없다(2026-07-29 확인) — 계획만 있고 구현이 안 된 것이다. 이 파일은 그때 쓴
   테스트가 tests/에 미추적으로 남아 스위트를 상시 빨갛게 만들던 것을 옮겨온
   것이다. 값 기대치는 그대로 쓸 수 있는 스펙이므로 버리지 않고 보존한다.

   구현하게 되면 이 파일을 tests/로 되돌리고 pytest로 돌릴 것.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.pipeline.workers.trade_engine import TradeEngineWorker


def _w():
    # __init__ 우회, 순수 staticmethod만 검증
    return TradeEngineWorker.__new__(TradeEngineWorker)


def test_dist_summary_basic():
    d = _w()._dist_summary([2.0, -1.0, 3.0, -4.0, 0.0])
    assert d['up'] == 2 and d['down'] == 2 and d['flat'] == 1
    assert d['mean'] == 0.0
    assert d['median'] == 0.0
    assert d['breadth_0'] == 40.0          # r>0 → 기존 breadth와 동일
    assert d['breadth_1'] == 40.0          # r>1: {2,3}
    assert d['breadth_3'] == 0.0           # r>3: 없음 (3.0은 미포함, strict)
    assert d['downtail_3'] == 1            # r<=-3: {-4}
    # nearest-rank 분위 (정렬 [-4,-1,0,2,3])
    assert d['p10'] == -4.0
    assert d['p90'] == 3.0


def test_dist_summary_empty_returns_none():
    assert _w()._dist_summary([]) is None
