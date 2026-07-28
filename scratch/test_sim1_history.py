"""Sim1 전일 스냅샷 · 진단 로그 확장 단위 테스트 — 네트워크 없음.
실행: PYTHONPATH=. python scratch/test_sim1_history.py

설계: docs/superpowers/specs/2026-07-28-sim1-history-snapshot-design.md
"""
import csv
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, '.')

from src.data import sim_diag

results = []


def check(name, cond):
    results.append((name, cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


# ── Task 1: 진단 로그 컬럼 확장 ────────────────────────────
def test_new_columns_exist():
    need = ['d_sov', 'd_hype', 'accel', 'accel_d1', 'z_hype',
            'hist_missing', 'hist_days_ago', 'ignition4']
    check('신규 컬럼 8개가 COLUMNS에 있다',
          all(c in sim_diag.COLUMNS for c in need))


def test_header_rotation_on_mismatch():
    """헤더가 다른 기존 파일이 있으면 옆으로 옮기고 정규 경로에 새로 쓴다."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'sim1_diag_2026-07.csv')
        # 구 헤더로 기존 파일 작성
        with open(path, 'w', newline='', encoding='utf-8') as f:
            f.write('ts,sim,code\nold,sim1,005930\n')

        # 첫 번째 append: 헤더 불일치 감지 → 옛 파일 옮김 → 정규 경로에 새 헤더 쓰기
        sim_diag.append('sim1', [{'code': '005930', 'd_sov': '1.5'}], path=path)

        # 정규 경로에 새 헤더와 새 행이 쓰임
        with open(path, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        check('정규 경로에 새 헤더와 새 행이 기록됨',
              len(rows) == 1 and rows[0]['d_sov'] == '1.5')

        # 옛 파일이 옆으로 옮겨짐
        rotated = [n for n in os.listdir(d) if n != os.path.basename(path)]
        check('옛 파일이 옆으로 옮겨짐', len(rotated) == 1)
        with open(os.path.join(d, rotated[0]), encoding='utf-8') as f:
            old_rows = list(csv.DictReader(f))
        check('옛 파일에 구 데이터가 그대로 남아있음',
              len(old_rows) == 1 and old_rows[0]['code'] == '005930')


def test_no_repeat_rotation_on_consecutive_calls():
    """연속 호출에서 파일이 더 늘어나지 않는다 (회귀 방지)."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'sim1_diag_2026-07.csv')
        # 구 헤더로 기존 파일 작성
        with open(path, 'w', newline='', encoding='utf-8') as f:
            f.write('ts,sim,code\nold,sim1,005930\n')

        # 3회 연속 append
        sim_diag.append('sim1', [{'code': '005930', 'd_sov': '1.5'}], path=path)
        sim_diag.append('sim1', [{'code': '005931', 'd_sov': '2.0'}], path=path)
        sim_diag.append('sim1', [{'code': '005932', 'd_sov': '2.5'}], path=path)

        # 파일은 정확히 2개여야 함 (정규 경로 1개 + 옛 파일 1개)
        files = os.listdir(d)
        check('연속 호출 후 파일 개수는 2개 (회전 1회만)',
              len(files) == 2)

        # 정규 경로에 3행 모두 기록됨
        with open(path, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        check('정규 경로에 3행 모두 기록됨',
              len(rows) == 3)


def test_append_still_works_on_fresh_file():
    """기존 동작 회귀: 빈 파일이면 그대로 헤더를 쓴다."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'sim1_diag_2026-07.csv')
        n = sim_diag.append('sim1', [{'code': '005930', 'decision': 'entry'}], path=path)
        with open(path, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        check('신규 파일에 정상 기록', n == 1 and rows[0]['decision'] == 'entry')


def test_rename_failure_prevents_data_corruption():
    """rename 실패 시 정규 경로에 로그를 쓰지 않아 데이터 정합성을 유지한다."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'sim1_diag_2026-07.csv')
        # 구 헤더로 기존 파일 작성
        with open(path, 'w', newline='', encoding='utf-8') as f:
            f.write('ts,sim,code\nold,sim1,005930\n')

        # 옛 내용 읽기
        with open(path, encoding='utf-8') as f:
            old_content = f.read()

        # os.rename을 실패하게 mock
        with mock.patch('os.rename', side_effect=OSError('Permission denied')):
            n = sim_diag.append('sim1', [{'code': '005931', 'd_sov': '2.0'}], path=path)

        # append가 0을 반환 (로그 안 씀)
        check('rename 실패 시 append는 0을 반환',
              n == 0)

        # 옛 파일의 내용이 그대로 (새 행 추가 안 됨)
        with open(path, encoding='utf-8') as f:
            new_content = f.read()
        check('옛 파일에 새 행이 추가되지 않음',
              old_content == new_content)

        # 예외가 호출자에게 전파되지 않음
        check('예외가 시뮬레이터를 죽이지 않음',
              True)  # 위의 append 호출이 예외 없이 완료됨


# ── Task 2: 스냅샷 승격 · 파생 3항 ─────────────────────────
from src.strategy.simulators import sim1_psych as sp


def _snap(date, ts='15:37', **codes):
    """{code: (z_sov, z_posters, z_hype)} → 스냅샷 dict"""
    return {'date': date, 'ts': ts,
            'z': {c: {'z_sov': v[0], 'z_posters': v[1], 'z_hype': v[2]}
                  for c, v in codes.items()}}


def test_promote_on_date_change():
    """직전 런이 어제 것이면 그것이 전일 확정값으로 승격된다."""
    old_prev = _snap('20260724', A=(0.1, 0.1, 0.1))
    yesterday = _snap('20260727', A=(1.0, 1.0, 1.0))
    prev, last = sp.resolve_history(old_prev, yesterday, '20260728')
    check('날짜가 바뀌면 직전 런이 prev_day로 승격', prev is yesterday)
    check('그날 첫 런에는 직전 런이 없다', last is None)


def test_no_promote_same_day():
    """같은 날 두 번째 런에서는 prev_day가 유지된다."""
    prev_day = _snap('20260727', A=(1.0, 1.0, 1.0))
    same_day = _snap('20260728', ts='10:21', A=(2.0, 2.0, 2.0))
    prev, last = sp.resolve_history(prev_day, same_day, '20260728')
    check('같은 날엔 prev_day 유지', prev is prev_day)
    check('같은 날엔 직전 런이 살아 있다', last is same_day)


def test_first_ever_run():
    prev, last = sp.resolve_history(None, None, '20260728')
    check('이력이 아예 없으면 둘 다 None', prev is None and last is None)


def test_derived_terms_basic():
    prev_day = _snap('20260727', A=(1.0, 0.5, 0.2))
    last_run = _snap('20260728', ts='10:21', A=(1.4, 0.9, 0.3))
    rows = [{'code': 'A', 'z_sov': 1.5, 'z_posters': 1.2, 'z_hype': 0.6, 'z_likes': 0.4}]
    sp.history_terms(rows, prev_day, last_run, '20260728', '1030')
    r = rows[0]
    check('d_sov = 오늘 − 전일', abs(r['d_sov'] - 0.5) < 1e-9)
    check('d_hype = 오늘 − 전일', abs(r['d_hype'] - 0.4) < 1e-9)
    check('accel = 오늘 − 직전 런', abs(r['accel'] - 0.3) < 1e-9)
    check('accel_d1 = 오늘 − 전일', abs(r['accel_d1'] - 0.7) < 1e-9)
    check('이력 있으면 hist_missing=0', r['hist_missing'] == 0)
    check('hist_days_ago = 1', r['hist_days_ago'] == 1)


def test_missing_history_is_neutral_zero():
    prev_day = _snap('20260727', A=(1.0, 0.5, 0.2))
    rows = [{'code': 'B', 'z_sov': 1.5, 'z_posters': 1.2, 'z_hype': 0.6, 'z_likes': 0.4}]
    sp.history_terms(rows, prev_day, None, '20260728', '1030')
    r = rows[0]
    check('신규 유입은 d_sov=0', r['d_sov'] == 0)
    check('신규 유입은 d_hype=0', r['d_hype'] == 0)
    check('신규 유입은 hist_missing=1', r['hist_missing'] == 1)


def test_stale_history_treated_missing():
    """5일 초과 이력은 '전일'이라 부를 수 없다."""
    prev_day = _snap('20260720', A=(1.0, 0.5, 0.2))
    rows = [{'code': 'A', 'z_sov': 1.5, 'z_posters': 1.2, 'z_hype': 0.6, 'z_likes': 0.4}]
    sp.history_terms(rows, prev_day, None, '20260728', '1030')
    check('8일 전 이력은 결측 취급', rows[0]['hist_missing'] == 1 and rows[0]['d_sov'] == 0)
    check('hist_days_ago는 그대로 기록', rows[0]['hist_days_ago'] == 8)


def test_accel_suppressed_before_0930():
    prev_day = _snap('20260727', A=(1.0, 0.5, 0.2))
    last_run = _snap('20260728', ts='09:15', A=(1.4, 0.9, 0.3))
    rows = [{'code': 'A', 'z_sov': 1.5, 'z_posters': 1.2, 'z_hype': 0.6, 'z_likes': 0.4}]
    sp.history_terms(rows, prev_day, last_run, '20260728', '0915')
    check('09:30 이전 accel=0', rows[0]['accel'] == 0)
    check('09:30 이전에도 accel_d1은 계산', abs(rows[0]['accel_d1'] - 0.7) < 1e-9)

    rows2 = [{'code': 'A', 'z_sov': 1.5, 'z_posters': 1.2, 'z_hype': 0.6, 'z_likes': 0.4}]
    sp.history_terms(rows2, prev_day, last_run, '20260728', '0930')
    check('09:30부터 accel 정상', abs(rows2[0]['accel'] - 0.3) < 1e-9)


def test_delta_z_excludes_missing():
    """z(d_sov)는 이력 있는 종목만으로 계산한다.

    이전 버전은 이력 10종목의 d_sov를 전부 1.0으로 통일해 분산이 0이 되고
    `_zmap`이 `{}`를 반환했다 — 그래서 raw 멤버십(포함/제외)만 확인할 뿐
    실제 z 분포가 결측 종목에 흔들리지 않는지는 전혀 검증하지 못하는
    공허한 테스트였다(구현이 결측의 0을 분포에 섞도록 바뀌어도 통과했다).

    이번 버전은 이력 종목의 d_sov를 서로 다르게 만들어(분산 > 0) `_zmap`이
    실제 값을 반환하게 하고, 결측 종목(NEW)이 있든 없든 이력 종목들의
    ignition4가 동일한지를 비교한다. NEW의 0-델타가 분포에 섞이면 평균·표준편차가
    바뀌어 이 비교가 깨진다.
    """
    prev_day = _snap('20260727', **{f"H{i}": (i * 0.1, 0.5, 0.2) for i in range(10)})

    def _rows(include_new):
        rows = [{'code': f"H{i}", 'z_sov': 1.0 + i * 0.2, 'z_posters': 1.0,
                 'z_hype': 0.7, 'z_likes': 0.4} for i in range(10)]
        if include_new:
            rows.append({'code': 'NEW', 'z_sov': 2.0, 'z_posters': 1.0,
                        'z_hype': 0.7, 'z_likes': 0.4})
        return rows

    with_new = _rows(True)
    without_new = _rows(False)
    sp.history_terms(with_new, prev_day, None, '20260728', '1030')
    sp.history_terms(without_new, prev_day, None, '20260728', '1030')

    new_row = with_new[-1]
    check('결측 종목의 d_sov는 0', new_row['d_sov'] == 0)
    hist_with = [r['ignition4'] for r in with_new if r['code'] != 'NEW']
    hist_without = [r['ignition4'] for r in without_new]
    check('결측 종목이 섞여도 이력 종목의 ignition4는 그대로다(분포에서 실제로 제외됨)',
          all(abs(a - b) < 1e-9 for a, b in zip(hist_with, hist_without)))
    check('모든 행에 ignition4가 있다', all('ignition4' in r for r in with_new))


def test_build_snapshot():
    """(Important 1 반영) 한 항이 None이어도 나머지 항은 스냅샷에 남는다 —
    이전에는 AND 조건이 종목 전체를 통째로 버렸다."""
    rows = [{'code': 'A', 'z_sov': 1.5, 'z_posters': 1.2, 'z_hype': 0.6},
            {'code': 'B', 'z_sov': None, 'z_posters': 0.3, 'z_hype': 0.1},
            {'code': 'C', 'z_sov': None, 'z_posters': None, 'z_hype': None}]
    snap = sp.build_snapshot(rows, '20260728', '2026-07-28 10:30:00')
    check('스냅샷 날짜', snap['date'] == '20260728')
    check('스냅샷에 z만 담긴다', set(snap['z']['A']) == {'z_sov', 'z_posters', 'z_hype'})
    check('z_sov만 None인 종목은 나머지 항만 담고 살아남는다',
          'B' in snap['z'] and set(snap['z']['B']) == {'z_posters', 'z_hype'})
    check('셋 다 None인 종목만 통째로 빠진다', 'C' not in snap['z'])


def test_none_z_values_no_crash():
    """`_zmap`이 표본 부족(<MIN_SAMPLE)·분산 0으로 {}를 반환하면 오늘 행의
    z_sov·z_posters·z_hype가 (키는 있되) None으로 남는다. 개장 초반·후보가
    적은 날 실제로 벌어지는 상황이며, 이 경우도 크래시 없이 중립 0을
    기준으로 파생값을 계산해야 한다(`.get(key, 0)`은 키가 존재하면 저장된
    None을 그대로 돌려줘 크래시를 낸다 — `.get(key) or 0`이어야 한다)."""
    prev_day = _snap('20260727', A=(1.0, 0.5, 0.2))
    last_run = _snap('20260728', ts='10:21', A=(1.4, 0.9, 0.3))
    rows = [{'code': 'A', 'z_sov': None, 'z_posters': None, 'z_hype': None, 'z_likes': None}]
    sp.history_terms(rows, prev_day, last_run, '20260728', '1030')
    r = rows[0]
    check('z_sov=None이어도 d_sov는 0 기준으로 계산(크래시 없음)',
          abs(r['d_sov'] - (0 - 1.0)) < 1e-9)
    check('z_hype=None이어도 d_hype는 0 기준으로 계산(크래시 없음)',
          abs(r['d_hype'] - (0 - 0.2)) < 1e-9)
    check('z_posters=None이어도 accel_d1은 0 기준으로 계산(크래시 없음)',
          abs(r['accel_d1'] - (0 - 0.5)) < 1e-9)
    check('z_posters=None이어도 accel은 0 기준으로 계산(크래시 없음)',
          abs(r['accel'] - (0 - 0.9)) < 1e-9)
    check('ignition4도 크래시 없이 계산된다', abs(r['ignition4'] - 0.0) < 1e-9)


def test_build_snapshot_keeps_other_terms_when_z_hype_degenerate():
    """z_hype 하나가 퇴화(None)해도 z_sov·z_posters는 스냅샷에 남아야 한다.

    hype는 게시글 제목에서 나오는데(data_fetcher.py), status != '활성'인
    후보는 posts=[]를 받아 hype_score가 정확히 0.0이 된다. 후보 전부가
    그 상태면(개장 직후·글이 얇은 런·스크랩 부분 실패) z_hype 분산이 0 →
    `_zmap`이 {} → 모든 행의 z_hype가 None이 된다. 이전 버전은 이때 z_sov·
    z_posters가 정상 계산됐어도 AND 조건 때문에 종목 자체를 스냅샷에서
    통째로 버렸다(Important 1)."""
    rows = [{'code': f"C{i}", 'z_sov': 1.0 + i * 0.1, 'z_posters': 0.5 + i * 0.1,
             'z_hype': None} for i in range(12)]
    snap = sp.build_snapshot(rows, '20260728', '2026-07-28 09:05:00')
    check('z_hype 전멸에도 스냅샷에 종목 전부가 담긴다', len(snap['z']) == 12)
    check('z_sov·z_posters는 보존되고 z_hype만 빠진다',
          all(set(snap['z'][f"C{i}"]) == {'z_sov', 'z_posters'} for i in range(12)))

    # 다음 런에서 이 스냅샷이 전일값으로 쓰이면 d_sov가 정상 계산돼야 한다
    # (버려졌다면 hist_missing=1·d_sov=0으로 결측 취급됐을 것이다).
    today_rows = [{'code': f"C{i}", 'z_sov': 2.0 + i * 0.1, 'z_posters': 1.0,
                  'z_hype': 0.3, 'z_likes': 0.4} for i in range(12)]
    sp.history_terms(today_rows, snap, None, '20260729', '1030')
    check('z_hype가 빠진 전일 스냅샷이어도 hist_missing=0(z_sov는 있다)',
          all(r['hist_missing'] == 0 for r in today_rows))
    check('d_sov = 오늘 − 전일(z_sov 기준)이 정상 계산된다',
          abs(today_rows[0]['d_sov'] - 1.0) < 1e-9)


def test_history_terms_tolerates_partial_prev_entry():
    """전일 스냅샷의 한 종목에 z_hype 키 자체가 없어도(z_hype 퇴화 런의
    산물) 크래시 없이 d_sov는 계산되고, 없는 z_hype는 중립 0 기준으로
    처리된다(그 항만 결측 흡수 — hist_missing은 z_sov 유무로만 판정)."""
    prev_day = {'date': '20260727', 'ts': '15:30',
                'z': {'A': {'z_sov': 1.0, 'z_posters': 0.5}}}  # z_hype 키 없음
    rows = [{'code': 'A', 'z_sov': 1.5, 'z_posters': 1.2, 'z_hype': 0.6, 'z_likes': 0.4}]
    sp.history_terms(rows, prev_day, None, '20260728', '1030')
    r = rows[0]
    check('z_hype 없는 전일 항목도 hist_missing=0(z_sov 기준)', r['hist_missing'] == 0)
    check('d_sov는 정상 계산(1.5-1.0)', abs(r['d_sov'] - 0.5) < 1e-9)
    check('d_hype는 전일 z_hype 결측을 0으로 흡수(0.6-0)',
          abs(r['d_hype'] - 0.6) < 1e-9)


# ── Task 3: 배선 + 진입 불변 회귀 ──────────────────────────
def _cand(code, posts, posters, likes, price=10000, change='+1.00%'):
    return {'code': code, 'name': code, 'price': price, 'amount': 5_000_000_000,
            'recent_posts_count': posts, 'unique_posters': posters,
            'total_likes': likes, 'avg_posts': 10, 'change_rate': change,
            'sparkline_price': [price] * 5, 'tick_power': 200, 'posts': []}


def _view(**kw):
    v = {'portfolio': {}, 'cash': 3000000, 'initial_cash': 3000000,
         'nav': 3000000, 'cooldown_codes': {}, 'market_index_healthy': True,
         'psych_prev_day': None, 'psych_last_run': None}
    v.update(kw)
    return v


def test_decide_returns_snapshot():
    cands = [_cand(f"{i:06d}", 50 + i * 7, 20 + i, 100 + i * 5) for i in range(12)]
    prices = {c['code']: c['price'] for c in cands}
    orders, diags, snap = sp.decide_psych(_view(), cands, prices,
                                          today='20260728', hhmm='1030',
                                          ts='2026-07-28 10:30:00')
    check('3-tuple 반환', isinstance(snap, dict) and 'z' in snap)
    check('스냅샷 날짜가 주입값', snap['date'] == '20260728')
    check('diag에 이력 컬럼이 실린다',
          all('d_sov' in d and 'ignition4' in d and 'hist_missing' in d for d in diags))


def test_entry_decisions_unchanged_by_history():
    """★ 진입 불변 회귀 — 이력이 있든 없든 진입/청산 결정이 같아야 한다.

    이번 변경은 기록만 한다. ignition(3항)과 decision이 달라지면 실패다.
    """
    cands = [_cand(f"{i:06d}", 50 + i * 7, 20 + i, 100 + i * 5) for i in range(12)]
    prices = {c['code']: c['price'] for c in cands}

    o1, d1, snap1 = sp.decide_psych(_view(), cands, prices, today='20260728',
                                    hhmm='1030', ts='t1')
    prev = {'date': '20260727', 'ts': 't0',
            'z': {c['code']: {'z_sov': -2.0, 'z_posters': -2.0, 'z_hype': -2.0}
                  for c in cands}}
    o2, d2, _ = sp.decide_psych(_view(psych_prev_day=prev, psych_last_run=prev),
                                cands, prices, today='20260728',
                                hhmm='1030', ts='t1')

    check('주문이 동일', o1 == o2)
    check('진입 결정이 동일', [d['decision'] for d in d1] == [d['decision'] for d in d2])
    check('skip 사유가 동일', [d['reason'] for d in d1] == [d['reason'] for d in d2])
    check('3항 ignition이 동일',
          [d['ignition'] for d in d1] == [d['ignition'] for d in d2])
    check('이력이 붙으면 d_sov는 달라진다(계산은 되고 있다)',
          any(d['d_sov'] != 0 for d in d2))


def test_empty_candidates_do_not_wipe_snapshot():
    """정상 스냅샷이 state에 있는 상태에서 빈 후보 런이 돌아도 psych_snapshot이
    비워지면 안 된다(Important 2). 승격은 '그날 마지막 런의 스냅샷'을 전일값
    으로 만들기 때문에, 하루 중 마지막 한 번의 빈 런이 그날 축적한 이력
    전부를 무효화할 수 있었다.

    실제 data/sim_psych_state.json은 절대 건드리지 않는다 — 인스턴스 생성
    직후 state_file·log_file·csv_file을 임시 디렉터리로 즉시 교체하고,
    그 뒤에만 reset_state()/save_state()로 파일을 쓴다.
    """
    from src.strategy.simulators.sim1_psych import PsychDivergenceSimulator
    with tempfile.TemporaryDirectory() as d:
        sim = PsychDivergenceSimulator(initial_cash=3_000_000)
        sim.state_file = os.path.join(d, 'sim_psych_state.json')
        sim.log_file = os.path.join(d, 'sim_psych_log.json')
        sim.csv_file = os.path.join(d, 'trade_history_sim_psych.csv')
        sim.reset_state()  # 격리된 경로로 클린 상태 시작(실제 파일 미사용)

        good_snapshot = {'date': '20260727', 'ts': '15:30:00',
                         'z': {'005930': {'z_sov': 1.0, 'z_posters': 1.0, 'z_hype': 1.0}}}
        sim.state['psych_snapshot'] = good_snapshot
        sim.save_state()

        sim.run([], current_prices={})  # 후보 0개 런

        check('빈 후보 런에도 기존 psych_snapshot이 그대로 유지된다',
              sim.state['psych_snapshot'] == good_snapshot)


if __name__ == '__main__':
    test_new_columns_exist()
    test_header_rotation_on_mismatch()
    test_no_repeat_rotation_on_consecutive_calls()
    test_append_still_works_on_fresh_file()
    test_rename_failure_prevents_data_corruption()
    test_promote_on_date_change()
    test_no_promote_same_day()
    test_first_ever_run()
    test_derived_terms_basic()
    test_missing_history_is_neutral_zero()
    test_stale_history_treated_missing()
    test_accel_suppressed_before_0930()
    test_delta_z_excludes_missing()
    test_build_snapshot()
    test_none_z_values_no_crash()
    test_build_snapshot_keeps_other_terms_when_z_hype_degenerate()
    test_history_terms_tolerates_partial_prev_entry()
    test_decide_returns_snapshot()
    test_entry_decisions_unchanged_by_history()
    test_empty_candidates_do_not_wipe_snapshot()
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} 통과")
    sys.exit(1 if failed else 0)
