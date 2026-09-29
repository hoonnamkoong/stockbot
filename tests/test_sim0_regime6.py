"""리베로 6단계 국면(권장안 R) — 판정 함수·확정 규칙·run 배선.

설계서: docs/superpowers/specs/2026-09-29-libero-regime6-design.md §4.
정본은 6단계이고 current_regime(3단계)은 거기서 파생된다.

여기서 지키는 것:
  ① 방향 단계 문턱(대칭 ±0.40/±0.90)과 횡보 약/강(vol10 0.98)
  ② 히스테리시스 0.05 + 같은 단계 2일 연속이어야 확정
  ③ 10:00 전에는 전일 확정값 유지, 10:00부터 장중 현재가 반영
  ④ 판정 불가(입력 부족·조회 실패)는 SIDEWAYS가 아니다 — 직전 확정 유지, 없으면 None
"""
import datetime as dt
import json
import os
import statistics
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy import regime_state as rs  # noqa: E402
from src.strategy.simulators import sim0_libero as lib  # noqa: E402
from src.strategy.simulators.sim0_libero import (  # noqa: E402
    LiberoSimulator, advance_regime6, direction_level, load_top100_closes,
    regime6_label, regime6_metrics, regime6_step,
)

KST = dt.timezone(dt.timedelta(hours=9))


def _at(day, hhmm):
    h, m = map(int, hhmm.split(':'))
    return dt.datetime(2026, 9, day, h, m, tzinfo=KST)


# ── ① 방향 단계·라벨 ──────────────────────────────────────────────────

@pytest.mark.parametrize('d, level', [
    (-1.5, -2), (-0.9001, -2), (-0.90, -1), (-0.4001, -1),
    (-0.40, 0), (0.0, 0), (0.3999, 0), (0.40, 1), (0.8999, 1), (0.90, 2), (1.5, 2),
])
def test_direction_level_symmetric_cuts(d, level):
    assert direction_level(d) == level


def test_sideways_splits_on_vol10_above_098():
    assert regime6_label(0, 0.99) == rs.STRONG_SIDEWAYS
    assert regime6_label(0, 0.98) == rs.WEAK_SIDEWAYS   # 초과(>)일 때만 강한횡보
    assert regime6_label(-2, 5.0) == rs.STRONG_BEAR
    assert regime6_label(-1, 0.1) == rs.BEAR
    assert regime6_label(1, 0.1) == rs.BULL
    assert regime6_label(2, 0.1) == rs.STRONG_BULL


def test_sideways_without_vol10_is_unknown_not_weak():
    """vol10을 모르면 약/강을 지어내지 않는다."""
    assert regime6_label(0, None) is None
    assert regime6_label(None, 1.0) is None


@pytest.mark.parametrize('r6, r3', [
    ('STRONG_BEAR', 'BEAR'), ('BEAR', 'BEAR'),
    ('WEAK_SIDEWAYS', 'SIDEWAYS'), ('STRONG_SIDEWAYS', 'SIDEWAYS'),
    ('BULL', 'BULL'), ('STRONG_BULL', 'BULL'),
    (None, None), ('BANANA', None),
])
def test_regime6_to_regime3_mapping(r6, r3):
    assert rs.to_regime3(r6) == r3


def test_korean_labels_cover_all_six():
    assert [rs.REGIME6_LABEL_KO[r] for r in rs.VALID_REGIMES6] == [
        '매우하락', '하락', '약한횡보', '강한횡보', '상승', '매우상승']


# ── ② 히스테리시스 + 2일 확정 ────────────────────────────────────────

def _base(level, cand=None, days=0):
    return {'level': level, 'candidate': cand, 'candidate_days': days,
            'confirmed_since': '2026-09-01'}


def test_hysteresis_band_blocks_marginal_move():
    """0.42는 원시로 상승이지만 0.05 당기면 0.37 → 횡보. 이동 후보조차 아니다."""
    s, raw = regime6_step(_base(0), 0.42, '2026-09-02')
    assert raw == 1
    assert s['level'] == 0 and s['candidate'] is None and s['candidate_days'] == 0


def test_one_day_is_only_a_candidate():
    s, _ = regime6_step(_base(0), 0.46, '2026-09-02')
    assert s['level'] == 0
    assert s['candidate'] == 1 and s['candidate_days'] == 1


def test_two_consecutive_days_confirm():
    s, _ = regime6_step(_base(0), 0.46, '2026-09-02')
    s, _ = regime6_step(s, 0.60, '2026-09-03')
    assert s['level'] == 1
    assert s['candidate'] is None and s['candidate_days'] == 0
    assert s['confirmed_since'] == '2026-09-03'


def test_return_to_current_level_resets_candidate():
    s, _ = regime6_step(_base(0), 0.46, '2026-09-02')
    s, _ = regime6_step(s, 0.10, '2026-09-03')
    assert s['candidate'] is None
    s, _ = regime6_step(s, 0.50, '2026-09-04')
    assert s['level'] == 0 and s['candidate_days'] == 1


def test_different_target_restarts_count():
    s, _ = regime6_step(_base(0), 0.50, '2026-09-02')     # 후보 +1
    s, _ = regime6_step(s, 1.00, '2026-09-03')            # 후보 +2(1일째)
    assert s['level'] == 0
    assert s['candidate'] == 2 and s['candidate_days'] == 1


def test_unknown_day_resets_candidate():
    """판정 불가일은 연속을 끊는다 — 증거 없이 국면이 바뀌지 않게."""
    s, _ = regime6_step(_base(0), 0.50, '2026-09-02')
    s, raw = regime6_step(s, None, '2026-09-03')
    assert raw is None
    assert s['level'] == 0 and s['candidate'] is None


# ── 지표 계산 ───────────────────────────────────────────────────────

def _paths(n_rows, up_frac, n=100, step=0.01):
    """k개 종목은 매일 +1%, 나머지는 −1%. 행 = 날짜, 열 = 종목."""
    k = round(n * up_frac)
    rows = []
    for t in range(n_rows):
        rows.append([100 * (1 + step) ** t if i < k else 100 * (1 - step) ** t
                     for i in range(n)])
    return rows


def test_metrics_match_hand_formula():
    rows = _paths(21, 0.7)
    m, why = regime6_metrics(rows)
    assert why is None
    assert m['ab20'] == pytest.approx(70.0)
    e = 0.7 * 0.01 - 0.3 * 0.01
    assert m['ret10'] == pytest.approx((1 + e) ** 10 - 1)
    assert m['vol10'] == pytest.approx(0.0, abs=1e-9)
    d = 0.5 * (70 - 50) / 25 + 0.5 * min(1, ((1 + e) ** 10 - 1) / 0.06)
    assert m['D'] == pytest.approx(d)


def test_metrics_vol10_is_sample_std_percent():
    rows = _paths(21, 0.5)
    # 마지막 10일의 균등지수 수익률을 흔든다: 짝수 날 전 종목 +2%, 홀수 날 −1%
    for t in range(11, 21):
        f = 1.02 if t % 2 == 0 else 0.99
        rows[t] = [p * f for p in rows[t - 1]]
    m, _ = regime6_metrics(rows)
    ew = [0.02 if t % 2 == 0 else -0.01 for t in range(11, 21)]
    assert m['vol10'] == pytest.approx(statistics.stdev(ew) * 100)


def test_metrics_need_21_rows():
    m, why = regime6_metrics(_paths(20, 0.5))
    assert m is None and 'rows' in why


def test_metrics_need_80_stocks_with_sma20():
    rows = _paths(21, 0.5)
    for r in rows[5:]:
        for i in range(25):
            r[i] = None
    m, why = regime6_metrics(rows)
    assert m is None and 'sample' in why


# ── CSV 로더 ────────────────────────────────────────────────────────

def test_load_top100_closes_parses_wide_csv(tmp_path):
    p = tmp_path / 'c.csv'
    p.write_text('﻿date,005930_삼성전자,000660_SK하이닉스\n'
                 '20260928,270000,\n20260929,273000,1771000\n', encoding='utf-8')
    c = load_top100_closes(str(p))
    assert c['codes'] == ['005930', '000660']
    assert c['dates'] == ['2026-09-28', '2026-09-29']
    assert c['rows'] == [[270000.0, None], [273000.0, 1771000.0]]


def test_load_top100_closes_missing_file_is_none(tmp_path):
    assert load_top100_closes(str(tmp_path / 'nope.csv')) is None


# ── ③④ advance_regime6: 날짜 경계·10시·결손 ─────────────────────────
# 오케스트레이션만 본다 — 지표는 가짜로 바꿔 행의 표지값에서 D·vol10을 읽는다.
# 표지: 열0 = 1000*(D+2), 열1 = vol10*100. 나머지 열은 가격 100.

N = 100


def _marker_row(d, vol=0.5):
    return [1000 * (d + 2), vol * 100] + [100.0] * (N - 2)


def _fake_metrics(rows):
    if len(rows) < 21:
        return None, 'rows<21'
    last = rows[-1]
    if last[0] is None:
        return None, 'sample<80'
    return {'D': last[0] / 1000 - 2, 'ab20': 50.0, 'ret10': 0.0,
            'vol10': last[1] / 100}, None


@pytest.fixture
def fake_metrics(monkeypatch):
    monkeypatch.setattr(lib, 'regime6_metrics', _fake_metrics)


def _closes(ds):
    """ds: [(day, D)] 9월 날짜. 앞에 21행을 D=0으로 채워 부트스트랩을 횡보로 만든다."""
    dates, rows = [], []
    for i in range(21):
        dates.append(f'2026-08-{i + 1:02d}')
        rows.append(_marker_row(0.0))
    for day, d in ds:
        dates.append(f'2026-09-{day:02d}')
        rows.append(_marker_row(d))
    return {'dates': dates, 'codes': [f'{i:06d}' for i in range(N)], 'rows': rows}


def _live_from(closes, d, vol=0.5):
    """전일 종가(CSV 마지막 행)와 맞는 등락률을 가진 장중 현재가."""
    prev = closes['rows'][-1]
    now = _marker_row(d, vol)
    return {c: {'price': p, 'change_rate': (p / q - 1) * 100}
            for c, p, q in zip(closes['codes'], now, prev)}


def test_bootstrap_replays_csv(fake_metrics):
    c = _closes([(1, 0.6), (2, 0.6)])
    out = advance_regime6(None, c, None, _at(3, '09:05'))
    assert out['level'] == 1
    assert out['regime6'] == rs.BULL
    assert out['status'] == 'hold_pre10'


def test_before_10_keeps_yesterday_confirmed_even_with_live(fake_metrics):
    c = _closes([(1, 0.0)])
    live = _live_from(c, 1.4)
    out = advance_regime6(None, c, live, _at(2, '09:50'))
    assert out['level'] == 0
    assert out['status'] == 'hold_pre10'
    assert out['raw_level'] is None


def test_after_10_live_is_only_a_candidate_on_first_day(fake_metrics):
    c = _closes([(1, 0.0)])
    out = advance_regime6(None, c, _live_from(c, 0.6), _at(2, '10:00'))
    assert out['status'] == 'ok'
    assert out['level'] == 0
    assert out['candidate'] == rs.BULL and out['candidate_days'] == 1
    assert out['raw_level'] == 1


def test_intraday_confirms_when_yesterday_was_candidate(fake_metrics):
    """어제 종가가 이미 이동 후보였으면 오늘 장중에 확정된다(설계서 §4.4)."""
    c = _closes([(1, 0.0), (2, 0.6)])
    out = advance_regime6(None, c, _live_from(c, 0.6), _at(3, '11:00'))
    assert out['level'] == 1 and out['regime6'] == rs.BULL
    assert out['confirmed_since'] == '2026-09-03'


def test_intraday_runs_do_not_stack_within_a_day(fake_metrics):
    """같은 날 여러 런은 모두 '어제까지 확정 + 오늘 원시'로 다시 계산된다."""
    c = _closes([(1, 0.0)])
    s = None
    for hhmm in ('10:00', '10:10', '10:20', '11:00'):
        out = advance_regime6(s, c, _live_from(c, 0.6), _at(2, hhmm))
        s = out['state']
    assert out['level'] == 0 and out['candidate_days'] == 1


def test_next_day_commits_yesterday_from_csv_close(fake_metrics):
    """어제 장중엔 후보였어도 종가가 되돌아왔으면 후보는 사라진다(종가가 정본)."""
    c1 = _closes([(1, 0.0)])
    s = advance_regime6(None, c1, _live_from(c1, 0.6), _at(2, '14:00'))['state']
    c2 = _closes([(1, 0.0), (2, 0.1)])                   # 어제 종가 D=0.1
    out = advance_regime6(s, c2, _live_from(c2, 0.6), _at(3, '10:30'))
    assert out['level'] == 0 and out['candidate_days'] == 1   # 연속 아님


def test_next_day_uses_last_intraday_if_csv_lacks_yesterday(fake_metrics):
    c1 = _closes([(1, 0.0)])
    s = advance_regime6(None, c1, _live_from(c1, 0.6), _at(2, '15:20'))['state']
    # CSV가 어제(2일) 종가를 아직 못 받았다 → 저장해 둔 어제 장중 판정으로 커밋
    out = advance_regime6(s, c1, None, _at(3, '09:10'))
    assert out['level'] == 0
    assert out['candidate'] == rs.BULL and out['candidate_days'] == 1
    assert out['status'] == 'hold_pre10'


def test_csv_row_for_today_wins_over_live(fake_metrics):
    c = _closes([(1, 0.0), (2, 0.6), (3, 0.6)])
    out = advance_regime6(None, c, _live_from(c, -1.4), _at(3, '17:00'))
    assert out['level'] == 1
    assert out['metrics']['source'] == 'close_csv'


def test_live_failure_keeps_confirmed_and_marks_stale(fake_metrics):
    c = _closes([(1, 0.0)])
    out = advance_regime6(None, c, None, _at(2, '11:00'))
    assert out['level'] == 0 and out['regime6'] == rs.WEAK_SIDEWAYS
    assert out['status'] == 'stale'
    assert 'live' in out['metrics']['reason']


def test_live_failure_later_same_day_keeps_earlier_intraday(fake_metrics):
    c = _closes([(1, 0.0), (2, 0.6)])
    s = advance_regime6(None, c, _live_from(c, 0.6), _at(3, '10:10'))['state']
    out = advance_regime6(s, c, None, _at(3, '10:20'))
    assert out['level'] == 1
    assert out['status'] == 'stale'


def test_csv_not_matching_yesterday_close_blocks_intraday(fake_metrics):
    """CSV 마지막 행이 전일 종가가 아니면(낡음) 장중 행을 붙이지 않는다."""
    c = _closes([(1, 0.0), (2, 0.6)])
    live = _live_from(c, 0.6)
    for v in live.values():
        v['change_rate'] += 3.0      # 네이버 기준 전일 종가가 CSV와 다르다
    out = advance_regime6(None, c, live, _at(3, '11:00'))
    assert out['level'] == 0
    assert out['status'] == 'stale'
    assert 'csv' in out['metrics']['reason']


def test_unreadable_csv_keeps_previous_regime6(fake_metrics):
    c = _closes([(1, 0.6), (2, 0.6)])
    s = advance_regime6(None, c, None, _at(3, '09:05'))['state']
    out = advance_regime6(s, None, None, _at(3, '11:00'))
    assert out['regime6'] == rs.BULL
    assert out['status'] == 'stale'


def test_no_history_and_no_input_is_none_not_sideways(fake_metrics):
    out = advance_regime6(None, None, None, _at(3, '11:00'))
    assert out['regime6'] is None and out['level'] is None
    assert out['status'] == 'stale'


def test_short_csv_is_undeterminable(fake_metrics):
    c = _closes([])
    c = {**c, 'dates': c['dates'][:20], 'rows': c['rows'][:20]}
    out = advance_regime6(None, c, None, _at(3, '11:00'))
    assert out['regime6'] is None
    assert 'rows' in out['metrics']['reason']


# ── run() 배선 ──────────────────────────────────────────────────────

def _sim(tmp_path):
    s = LiberoSimulator()
    s.state_file = str(tmp_path / 'libero.json')
    s.csv_file = str(tmp_path / 'libero.csv')
    s.log_file = str(tmp_path / 'libero.log')
    s.state = {'last_run': None, 'current_regime': None}
    return s


def _real_closes(n_rows, up_frac):
    rows = _paths(n_rows, up_frac)
    dates = [(dt.date(2026, 8, 1) + dt.timedelta(days=i)).isoformat() for i in range(n_rows)]
    return {'dates': dates, 'codes': [f'{i:06d}' for i in range(N)], 'rows': rows}


def test_run_writes_regime6_and_derives_current_regime(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, 'get_kst_now', lambda: _at(29, '09:30'))
    s = _sim(tmp_path)
    s.live_market_metrics = {'breadth': 50.0, 'momentum': 0.0, 'trend': 10.0, 'sample': 100}
    s.regime6_inputs = {'closes': _real_closes(30, 0.9), 'live': None}
    st = s.run([], current_prices={})
    assert st['regime6'] == rs.STRONG_BULL
    assert st['regime6_level'] == 2
    assert st['current_regime'] == 'BULL'
    assert st['regime6_metrics']['D'] > 0.9
    assert st['regime6_metrics']['judged_at'] == '2026-09-29 09:30:00'
    assert 'regime6_candidate' in st
    assert st['daily_regime_log'][-1]['regime6'] == rs.STRONG_BULL
    assert st['recommended_sims'] == LiberoSimulator.REGIME_TO_SIMS['BULL']
    # 파일로도 남는다(db-data 배포 대상 파일)
    with open(s.state_file, encoding='utf-8') as f:
        assert json.load(f)['regime6'] == rs.STRONG_BULL


def test_run_bearish_tape_maps_to_bear(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, 'get_kst_now', lambda: _at(29, '09:30'))
    s = _sim(tmp_path)
    s.live_market_metrics = None
    s.regime6_inputs = {'closes': _real_closes(30, 0.1), 'live': None}
    st = s.run([], current_prices={})
    assert st['regime6'] == rs.STRONG_BEAR
    assert st['current_regime'] == 'BEAR'


def test_run_without_inputs_keeps_previous_regime6(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, 'get_kst_now', lambda: _at(29, '11:00'))
    s = _sim(tmp_path)
    s.regime6_inputs = {'closes': _real_closes(30, 0.9), 'live': None}
    s.run([], current_prices={})
    s.regime6_inputs = None           # 다음 런: CSV도 라이브도 없다
    s.live_market_metrics = None
    st = s.run([], current_prices={})
    assert st['regime6'] == rs.STRONG_BULL
    assert st['current_regime'] == 'BULL'
    assert st['regime6_status'] == 'stale'


def test_run_first_ever_without_inputs_is_none(tmp_path, monkeypatch):
    """직전 확정값도 없으면 모른다 — SIDEWAYS로 채우지 않는다."""
    monkeypatch.setattr(lib, 'get_kst_now', lambda: _at(29, '11:00'))
    s = _sim(tmp_path)
    s.state['current_regime'] = 'SIDEWAYS'   # 옛 모델이 남긴 값
    s.live_market_metrics = {'breadth': 50.0, 'momentum': 0.0, 'trend': 10.0, 'sample': 100}
    st = s.run([], current_prices={})
    assert st['regime6'] is None
    assert st['current_regime'] is None
    assert st['recommended_sims'] == []


# ── read_regime6 ────────────────────────────────────────────────────

def _write_state(tmp_path, payload):
    (tmp_path / rs.regime_state_filename()).write_text(
        json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return str(tmp_path)


def test_read_regime6_valid(tmp_path):
    d = _write_state(tmp_path, {'regime6': 'WEAK_SIDEWAYS', 'current_regime': 'SIDEWAYS'})
    assert rs.read_regime6(d) == 'WEAK_SIDEWAYS'


def test_read_regime6_missing_file_is_none(tmp_path):
    assert rs.read_regime6(str(tmp_path)) is None


def test_read_regime6_missing_or_unknown_field_is_none(tmp_path):
    assert rs.read_regime6(_write_state(tmp_path, {'current_regime': 'SIDEWAYS'})) is None
    assert rs.read_regime6(_write_state(tmp_path, {'regime6': 'SIDEWAYS'})) is None
    assert rs.read_regime6(_write_state(tmp_path, {'regime6': None})) is None
