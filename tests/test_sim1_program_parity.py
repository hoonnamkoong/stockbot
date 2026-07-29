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


# ── Task 3: 승계 + 파리티 ───────────────────────────────────
def _view(prev_day=None, last_run=None, nav=3_000_000):
    return {'portfolio': {}, 'cash': nav, 'initial_cash': 3_000_000, 'nav': nav,
            'cooldown_codes': {}, 'market_index_healthy': True,
            'psych_prev_day': prev_day, 'psych_last_run': last_run}


PARITY_KEYS = ('decision', 'reason', 'd_sov', 'd_hype', 'accel', 'accel_d1',
               'hist_missing', 'hist_days_ago', 'ignition', 'ignition4')


def test_carry_returns_consumed_pair():
    from src.pipeline.workers.program_trader import _psych_carry
    prev = _snap('20260728')
    last = _snap('20260729', z_sov=0.5)
    carry = _psych_carry({'psych_prev_day': prev, 'psych_last_run': last,
                          'psych_snapshot': _snap('20260729', z_sov=9.9)})
    assert carry == {'psych_prev_day': prev, 'psych_snapshot': last}


def test_carry_is_empty_when_state_absent():
    """페이퍼 state가 없거나 dict가 아니면 현행대로 동작한다(예외 없음)."""
    from src.pipeline.workers.program_trader import _psych_carry
    assert _psych_carry(None) == {}
    assert _psych_carry('nope') == {}
    assert _psych_carry({'cash': 100}) == {}


def test_program_path_reproduces_paper_history_terms():
    """파리티의 실제 증명 — 같은 후보·같은 시각에 두 경로의 진단값이 전부 같다."""
    from src.pipeline.workers.program_trader import _psych_carry

    today = '20260729'
    prev_day = _snap('20260728', z_sov=0.2, z_posters=0.3, z_hype=0.1)
    prev_run = _snap(today, z_sov=0.9, z_posters=1.1, z_hype=0.4)
    cands = [_cand('005930', '삼성전자')] + _filler()
    prices = {'005930': 1000}

    # (1) 페이퍼 run()이 하는 일
    p_prev, p_last = resolve_history(prev_day, prev_run, today)
    o1, d1, new_snap = decide_psych(_view(p_prev, p_last), cands, prices,
                                    today=today, hhmm='1030', ts='t')
    # 페이퍼가 state에 써놓는 것 (Task 1 이후)
    paper_state = {'psych_prev_day': p_prev, 'psych_last_run': p_last,
                   'psych_snapshot': new_snap}

    # (2) 프로그램: 승계 → 다시 resolve_history 통과 → 같은 입력
    carry = _psych_carry(paper_state)
    g_prev, g_last = resolve_history(carry['psych_prev_day'], carry['psych_snapshot'], today)
    o2, d2, _ = decide_psych(_view(g_prev, g_last), cands, prices,
                             today=today, hhmm='1030', ts='t')

    assert (g_prev, g_last) == (p_prev, p_last)   # 재승격이 없다
    assert o1 == o2
    for k in PARITY_KEYS:
        assert [x[k] for x in d1] == [x[k] for x in d2], k


def test_carrying_psych_snapshot_would_collapse_accel():
    """기각한 대안 B를 코드로 못 박는다.

    페이퍼가 방금 덮어쓴 psych_snapshot을 승계하면 accel이 전 종목 0이 된다.
    Phase 2에서 accel>0 게이트가 들어가면 프로그램은 영구 무매매가 된다.
    """
    today = '20260729'
    prev_day = _snap('20260728', z_sov=0.2, z_posters=0.3)
    prev_run = _snap(today, z_sov=0.9, z_posters=1.1)
    cands = [_cand('005930', '삼성전자')] + _filler()
    prices = {'005930': 1000}

    p_prev, p_last = resolve_history(prev_day, prev_run, today)
    _, d_paper, new_snap = decide_psych(_view(p_prev, p_last), cands, prices,
                                        today=today, hhmm='1030', ts='t')
    # 잘못된 승계: last_run 대신 방금 쓴 snapshot
    b_prev, b_last = resolve_history(p_prev, new_snap, today)
    _, d_bad, _ = decide_psych(_view(b_prev, b_last), cands, prices,
                               today=today, hhmm='1030', ts='t')

    assert all(float(x['accel']) == 0 for x in d_bad)
    assert any(float(x['accel']) != 0 for x in d_paper)


def test_program_adapter_end_to_end_carries_history():
    """실제 배선 검증 — _make_adapter로 조립한 프로그램 경로가 페이퍼 run()의

    산출물을 실제로 소비하는지 확인한다. 위 파리티 테스트들은 resolve_history/
    decide_psych를 직접 호출해 수학만 재현할 뿐 run()도 _make_adapter도 타지
    않는다 — 그래서 _psych_carry의 반환 키 이름, program_trader가 심는
    'exec_path' 리터럴, sim1_psych.run()이 읽는 키 이름이 어긋나도(예:
    psych_snapshot을 psych_snapshoot으로 오타) 아무 테스트도 잡지 못한다.

    페이퍼를 같은 날 두 번 돌린다 — 1회차가 어제 스냅샷을 psych_prev_day로
    승격시키고, 2회차가 1회차의 결과물을 psych_last_run으로 소비한다(참값이
    None이 아니어야 승계 오류를 구분할 수 있다. history_terms의 hist_missing/
    d_sov는 psych_prev_day에서만 나오므로 psych_prev_day 하나만 갖고는
    psych_snapshot 쪽 키 오타를 못 잡는다 — accel은 psych_snapshot/last_run을
    쓰지만 09:30 게이트가 실벽시계라 여기서 검증하지 않는다. 그래서 carry된
    psych_snapshot을 paper.state['psych_last_run']과 직접 비교해 오타를 잡는다).
    """
    from src.data import sim_diag
    from src.pipeline.workers.program_trader import _make_adapter, _psych_carry
    import csv
    import datetime as _dt

    today = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9))).strftime('%Y%m%d')
    yesterday = (_dt.datetime.strptime(today, '%Y%m%d') - _dt.timedelta(days=1)).strftime('%Y%m%d')
    cands = [_cand('005930', '삼성전자')] + _filler()
    prices = {'005930': 1000}

    with tempfile.TemporaryDirectory() as d:
        paper_dir = os.path.join(d, 'paper')
        prog_dir = os.path.join(d, 'prog')
        paper_diag_dir = os.path.join(d, 'paper_diag')
        prog_diag_dir = os.path.join(d, 'prog_diag')
        for p in (paper_dir, prog_dir, paper_diag_dir, prog_diag_dir):
            os.makedirs(p)
        orig = sim_diag.DATA_DIR
        try:
            # 페이퍼 2회 — 실제 run() 결과만 쓴다(수동 조립 금지).
            sim_diag.DATA_DIR = paper_diag_dir
            paper = _isolated_sim(paper_dir)
            paper.state['psych_snapshot'] = _snap(yesterday)
            paper.run(cands, current_prices=prices)   # 1회차: yesterday → psych_prev_day 승격
            paper.run(cands, current_prices=prices)   # 2회차: 1회차 산출물 → psych_last_run 소비
            assert paper.state['psych_last_run'] is not None, \
                "이 테스트가 오타를 잡으려면 last_run이 실제 값이어야 한다"

            carry = _psych_carry(paper.state)
            # 핵심 배선 검증: carry된 psych_snapshot이 페이퍼가 실제로 소비한
            # last_run과 같아야 한다. _psych_carry가 'psych_snapshot' 키를
            # 오타 내면(예: psych_snapshoot) carry.get('psych_snapshot')은
            # None이 되어 여기서 즉시 실패한다.
            assert carry.get('psych_snapshot') == paper.state['psych_last_run']
            assert carry.get('psych_prev_day') == paper.state['psych_prev_day']

            # 프로그램: 승계한 값을 스냅샷에 심고 _make_adapter로 배선 + 실행.
            snapshot = {'cash': 3_000_000, 'invested': 0, 'portfolio': {}, 'total_fees': 0,
                        'history': [3_000_000], 'daily_trades': [], 'peak_nav': 3_000_000,
                        'market_index_healthy': True, 'cooldown_codes': {},
                        'exec_path': 'program', **carry}
            prog = _isolated_sim(prog_dir)
            _make_adapter(prog, snapshot, today)
            sim_diag.DATA_DIR = prog_diag_dir
            prog.run(cands, current_prices=prices)

            # (a) 진단이 프로그램 파일로 갔다(이 디렉터리엔 프로그램 런만 썼다).
            files = _diag_files(prog_diag_dir)
            assert any(f.startswith('sim1_program_diag_') for f in files), files
            assert not any(f.startswith('sim1_diag_') for f in files), files

            # (b) 이력이 실제로 살아남았다 — hist_missing==0인 행이 있어야 한다.
            prog_file = next(f for f in files if f.startswith('sim1_program_diag_'))
            with open(os.path.join(prog_diag_dir, prog_file), encoding='utf-8') as f:
                rows = list(csv.DictReader(f))
            assert any(r['code'] == '005930' and r['hist_missing'] == '0' for r in rows), rows
        finally:
            sim_diag.DATA_DIR = orig
