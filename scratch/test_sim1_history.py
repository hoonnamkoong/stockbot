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


if __name__ == '__main__':
    test_new_columns_exist()
    test_header_rotation_on_mismatch()
    test_no_repeat_rotation_on_consecutive_calls()
    test_append_still_works_on_fresh_file()
    test_rename_failure_prevents_data_corruption()
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} 통과")
    sys.exit(1 if failed else 0)
