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


# ── Task 2: 진단 로그 경로 분리 ─────────────────────────────
def _diag_files(d):
    return sorted(f for f in os.listdir(d) if f.endswith('.csv'))


def _cand(code, name, posts=300, avg=50, posters=200, likes=600, change='+1.00%'):
    return {'code': code, 'name': name, 'price': 1000, 'amount': 5_000_000_000,
            'recent_posts_count': posts, 'avg_posts': avg, 'unique_posters': posters,
            'total_likes': likes, 'change_rate': change,
            'sparkline_price': [900, 940, 970, 990, 1000],
            'tick_power': 130.0, 'fact_score': 0.5, 'posts': [{'title': '3분기 공시 확인'}]}


def _filler(n=MIN_SAMPLE + 2):
    """횡단면 z 표본. 값에 분산을 준다 — 전부 같으면 표준편차가 0이라
    z가 만들어지지 않고 진단 행이 비어버린다."""
    return [{'code': f'F{i:03d}', 'name': f'중립{i}', 'price': 1000,
             'amount': 2_000_000_000, 'recent_posts_count': 30 + i * 3,
             'avg_posts': 30 + i * 3, 'unique_posters': 24 + i * 2,
             'total_likes': 30 + i * 3, 'change_rate': '+0.50%',
             'sparkline_price': [980, 990, 1000, 1005, 1000], 'tick_power': 130.0,
             'posts': []} for i in range(n)]


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


def test_paper_path_writes_sim1_diag():
    """플래그가 없으면 기존 파일명 그대로다(현행 보존).

    후보를 반드시 넣어야 한다 — 진단 행이 0개면 sim_diag.append가 파일을
    만들지 않고 바로 반환한다.
    """
    from src.data import sim_diag
    with tempfile.TemporaryDirectory() as d:
        sim = _isolated_sim(d)
        data_dir = os.path.join(d, 'data')
        os.makedirs(data_dir)
        orig = sim_diag.DATA_DIR
        sim_diag.DATA_DIR = data_dir
        try:
            sim.run([_cand('005930', '삼성전자')] + _filler(), current_prices={})
            files = _diag_files(data_dir)
            assert any(f.startswith('sim1_diag_') for f in files), files
            assert not any(f.startswith('sim1_program_diag_') for f in files), files
        finally:
            sim_diag.DATA_DIR = orig


def test_program_path_writes_separate_diag_file():
    """exec_path=program이면 별도 파일로 간다 — 같은 사이클 이중계상 방지."""
    from src.data import sim_diag
    with tempfile.TemporaryDirectory() as d:
        sim = _isolated_sim(d)
        data_dir = os.path.join(d, 'data')
        os.makedirs(data_dir)
        orig = sim_diag.DATA_DIR
        sim_diag.DATA_DIR = data_dir
        try:
            sim.state['exec_path'] = 'program'
            sim.run([_cand('005930', '삼성전자')] + _filler(), current_prices={})
            files = _diag_files(data_dir)
            assert any(f.startswith('sim1_program_diag_') for f in files), files
            assert not any(f.startswith('sim1_diag_') for f in files), files
        finally:
            sim_diag.DATA_DIR = orig


def test_diag_columns_unchanged():
    """컬럼을 늘리면 헤더 회전이 일어나 07-29 수확분이 갈라진다."""
    from src.data import sim_diag
    assert sim_diag.COLUMNS[-1] == 'ignition4'
    assert len(sim_diag.COLUMNS) == 33
