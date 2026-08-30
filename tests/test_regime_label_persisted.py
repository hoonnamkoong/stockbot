# -*- coding: utf-8 -*-
"""관측 이력에 **봇이 그 순간 쓰던 국면 라벨**이 함께 남는다.

2026-08-30에 "심6이 BEAR 창(08-18~21)에 왜 거래 0건이었나"를 소급으로 답할 수
없었다. 봇이 실제로 판정한 국면이 어디에도 안 남기 때문이다 —
regime_gate_state.json엔 마지막 시각만, sim_libero_state엔 최근 5개만 있고,
regime_observations에는 원시 관측치(breadth·momentum·trend)만 있었다.

관측치로 오늘 코드를 다시 돌려 추정할 수는 있다. 하지만 그건 **당시 봇의 판단이
아니다** — 임계값도 분류 코드도 그 뒤로 바뀐다. 국면은 심의 소유권과 매매 여부를
가르므로 사후에 재현 가능해야 한다.
"""
from unittest import mock

from src.pipeline.workers.trade_engine import TradeEngineWorker


def _worker():
    w = TradeEngineWorker.__new__(TradeEngineWorker)   # __init__ 우회
    w.log = lambda *a, **k: None
    w.log_error = lambda *a, **k: None
    w._top100_trend_from_csv = lambda: 22.0
    return w


LIVE = {'breadth': 33.0, 'momentum': -3.1, 'sample': 100, 'extra': {'up': 20, 'down': 70}}


def _capture(regime_ret):
    calls = {}

    def fake_append(path, ts, breadth, momentum, trend, sample, source, extra=None):
        calls['extra'] = extra
        return True

    import datetime as dt
    with mock.patch('src.strategy.regime_observations.append_observation', fake_append), \
         mock.patch('src.strategy.regime_state.read_regime', return_value=regime_ret):
        _worker()._append_regime_observation(dt.datetime(2026, 8, 19, 10, 0), LIVE)
    return calls.get('extra') or {}


def test_국면과_점수가_관측에_함께_남는다():
    extra = _capture(('BEAR', 21.4))
    assert extra['regime'] == 'BEAR'
    assert extra['bull_score'] == 21.4
    # 기존 열을 밀어내지 않는다.
    assert extra['up'] == 20 and extra['down'] == 70


def test_판정_불가는_빈_값으로_남는다():
    """SIDEWAYS로 채우면 '모른다'와 '횡보였다'가 한 값이 된다."""
    extra = _capture((None, None))
    assert extra['regime'] is None
    assert extra['bull_score'] is None


def test_원본_extra를_변형하지_않는다():
    """live_breadth['extra']를 그대로 쓰면 호출자의 dict가 오염된다."""
    original = dict(LIVE['extra'])
    _capture(('BULL', 71.0))
    assert LIVE['extra'] == original
