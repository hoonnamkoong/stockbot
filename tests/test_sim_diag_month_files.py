"""컬럼이 바뀐 달의 진단 로그는 두 파일로 갈라진다 — 읽는 쪽이 둘 다 봐야 한다.

append()는 빈 파일에만 헤더를 쓴다. 그래서 COLUMNS가 늘어나면
_move_stale_if_needed가 옛 파일을 _v1으로 비켜놓고 정규 경로를 새로 시작한다
(안 그러면 열이 조용히 어긋난다). 2026-08에 cycle_id가 추가되며 실제로
sim1_diag_2026-08.csv가 이렇게 갈라졌는데, 정규 경로만 읽는 분석은 컬럼 변경
이전 행을 통째로 놓친다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data import sim_diag


def test_month_files_includes_split_off_versions(tmp_path, monkeypatch):
    monkeypatch.setattr(sim_diag, 'DATA_DIR', str(tmp_path))

    # 옛 헤더를 가진 파일이 이미 있는 상태에서 한 줄 쓰면 갈라진다.
    canonical = sim_diag.month_path('sim1', '20260810')
    with open(canonical, 'w', encoding='utf-8') as f:
        f.write('ts,sim,code\n2026-08-01 09:00:00,sim1,005930\n')

    sim_diag.append('sim1', [{'code': '000660'}], path=canonical)

    files = sim_diag.month_files('sim1', '20260810')
    assert len(files) == 2, f'갈라진 파일을 모두 돌려줘야 한다: {files}'
    assert files[0].endswith('_v1.csv'), '옛 파일이 먼저 와야 한다(시간순)'
    assert files[-1] == canonical


def test_month_files_is_empty_when_nothing_written(tmp_path, monkeypatch):
    monkeypatch.setattr(sim_diag, 'DATA_DIR', str(tmp_path))
    assert sim_diag.month_files('sim1', '20260810') == []
