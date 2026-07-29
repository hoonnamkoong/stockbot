"""Sim1 프로그램 매매 파리티.

프로그램 경로는 sim.state가 실계좌 스냅샷으로 갈아끼워져 이력 슬롯이 없다.
그래서 d_sov·d_hype·accel이 항상 0이었다. Phase 2에서 accel>0 게이트가
들어가면 프로그램 Sim1은 영구 무매매가 된다 — 조용히 안 사는 것은 잘못
사는 것만큼 나쁘다.

설계: docs/superpowers/specs/2026-07-29-sim1-program-parity-design.md
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.sim1_psych import (
    PsychDivergenceSimulator, resolve_history, decide_psych, MIN_SAMPLE,
)


def _isolated_sim(tmpdir):
    """실제 data/sim_psych_state.json을 건드리지 않는 격리 인스턴스."""
    sim = PsychDivergenceSimulator(initial_cash=3_000_000)
    sim.state_file = os.path.join(tmpdir, 'sim_psych_state.json')
    sim.log_file = os.path.join(tmpdir, 'sim_psych_log.json')
    sim.csv_file = os.path.join(tmpdir, 'trade_history_sim_psych.csv')
    sim.reset_state()
    return sim


def _snap(date, z_sov=1.0, z_posters=1.0, z_hype=0.5):
    return {'date': date, 'ts': f'{date} 10:00:00',
            'z': {'005930': {'z_sov': z_sov, 'z_posters': z_posters, 'z_hype': z_hype}}}


# ── Task 1: 소비한 쌍을 state에 남긴다 ──────────────────────
def test_run_stores_consumed_last_run():
    """같은 날 두 번째 런이면 소비한 last_run은 직전 런 스냅샷이다."""
    with tempfile.TemporaryDirectory() as d:
        sim = _isolated_sim(d)
        import datetime as _dt
        today = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9))).strftime('%Y%m%d')
        earlier = _snap(today, z_sov=1.0)
        sim.state['psych_snapshot'] = earlier

        sim.run([], current_prices={})

        assert sim.state['psych_last_run'] == earlier


def test_run_stores_none_on_first_run_of_day():
    """전일 스냅샷만 있으면 승격이 일어나고 소비한 last_run은 None이다."""
    with tempfile.TemporaryDirectory() as d:
        sim = _isolated_sim(d)
        yesterday = _snap('20260101')  # 오늘일 수 없는 날짜
        sim.state['psych_snapshot'] = yesterday

        sim.run([], current_prices={})

        assert sim.state['psych_last_run'] is None
        assert sim.state['psych_prev_day'] == yesterday
