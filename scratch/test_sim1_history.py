"""Sim1 전일 스냅샷 · 진단 로그 확장 단위 테스트 — 네트워크 없음.
실행: PYTHONPATH=. python scratch/test_sim1_history.py

설계: docs/superpowers/specs/2026-07-28-sim1-history-snapshot-design.md
"""
import csv
import os
import sys
import tempfile

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
    """헤더가 다른 기존 파일이 있으면 새 파일로 회전한다."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'sim1_diag_2026-07.csv')
        with open(path, 'w', newline='', encoding='utf-8') as f:
            f.write('ts,sim,code\nold,sim1,005930\n')      # 구 헤더
        sim_diag.append('sim1', [{'code': '005930', 'd_sov': '1.5'}], path=path)

        with open(path, encoding='utf-8') as f:
            head = f.readline().strip().split(',')
        check('헤더 불일치 시 기존 파일을 덮지 않는다', head == ['ts', 'sim', 'code'])

        rotated = [n for n in os.listdir(d) if n != os.path.basename(path)]
        check('회전 파일이 생성된다', len(rotated) == 1)
        with open(os.path.join(d, rotated[0]), encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        check('회전 파일에 새 컬럼이 기록된다',
              len(rows) == 1 and rows[0]['d_sov'] == '1.5')


def test_append_still_works_on_fresh_file():
    """기존 동작 회귀: 빈 파일이면 그대로 헤더를 쓴다."""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'sim1_diag_2026-07.csv')
        n = sim_diag.append('sim1', [{'code': '005930', 'decision': 'entry'}], path=path)
        with open(path, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        check('신규 파일에 정상 기록', n == 1 and rows[0]['decision'] == 'entry')


if __name__ == '__main__':
    test_new_columns_exist()
    test_header_rotation_on_mismatch()
    test_append_still_works_on_fresh_file()
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} 통과")
    sys.exit(1 if failed else 0)
