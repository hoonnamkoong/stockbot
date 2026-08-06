"""동기화 파일 목록은 매니페스트에서 파생돼야 한다 — 하드코딩된 심 이름이 아니라.

2026-07-30에 심 목록 중복을 매니페스트로 통합했는데 get_sync_files_list()가
빠졌다(7번째 자리). 2026-08-04 실측(런 40개 전수, 100% 재현)으로 한 사이클당
26개 동기화 시도 중 11개(42%)가 무의미했다:
  - 영구 404 5개: 존재한 적 없는 CSV, db-data에 애초에 없는 실거래 CSV,
    전략 시작 전인 1~3월 월별 리포트
  - 성공하지만 헛수고 6개: 매니페스트에 없는 폐기된 심 3개의 state+CSV
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data.storage_manager import StorageManager
from src.strategy.registry import get_sim_registry

NOW = datetime(2026, 8, 6)


def _files():
    return StorageManager().get_sync_files_list(NOW)


def test_covers_every_sim_in_the_manifest():
    """매니페스트에 있는 심은 전부 동기화된다 (심 추가 시 누락 방지)."""
    files = _files()
    for sim in get_sim_registry(include_analyzers=True):
        assert sim['state_file'] in files, f"{sim['id']} state 누락"
        assert sim['csv_file'] in files, f"{sim['id']} csv 누락"


def test_has_no_retired_sims():
    """폐기된 심(original/conservative/aggressive/conviction)을 더는 부르지 않는다."""
    files = _files()
    for dead in ('original', 'conservative', 'aggressive', 'conviction'):
        assert f'sim_{dead}_state.json' not in files, f'{dead}는 매니페스트에 없다'
        assert f'trade_history_sim_{dead}.csv' not in files


def test_does_not_fetch_real_trade_csv_from_db_data():
    """trade_history_real.csv는 db-data에 애초에 올라가지 않는다.

    비공개 레포 전용이고, 이제는 주문 낸 프로세스가 API로 직접 쓴다.
    여기서 부르면 매 사이클 404다.
    """
    assert 'trade_history_real.csv' not in _files()


def test_monthly_reports_start_at_active_strategy_since():
    """월별 리포트는 전략 시작월부터다. 그 전 달 파일은 존재한 적이 없다."""
    files = [f for f in _files() if 'monthly_research' in f]

    assert 'reports/monthly_research_2026-01.xlsx' not in files
    assert 'reports/monthly_research_2026-03.xlsx' not in files
    assert 'reports/monthly_research_2026-04.xlsx' in files, '전략 시작월(2026-04)부터'
    assert 'reports/monthly_research_2026-08.xlsx' in files, '이번 달까지'


def test_keeps_base_files():
    files = _files()
    assert 'sync_state.json' in files
    assert 'consecutive_registry.json' in files
    assert 'reservations.json' in files


def test_no_duplicates():
    files = _files()
    assert len(files) == len(set(files))
