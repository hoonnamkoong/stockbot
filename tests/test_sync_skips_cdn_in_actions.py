"""GitHub Actions 안에서는 CDN 동기화를 하지 않는다.

2026-08-08 점검에서 나온 문제. 워크플로는 런 시작에 이미
`git checkout db-data -- data/` 로 진짜 최신본을 받아온다. 그런데 Stage 1의
sync_from_github()이 그걸 raw.githubusercontent 사본으로 **덮어쓴다**. 이 CDN은
캐시버스터(`?t=`)로도 안 깨진다는 게 2026-07-10에 이미 확인됐다.

예전엔 동기화 목록이 하드코딩된 옛 심 3개뿐이라 피해가 작았다. 2026-08-07에
목록을 매니페스트 기반으로 바꾸면서 13개 심 전부가 대상이 됐고, 거기엔 실전
계좌가 돌리는 심의 상태 파일도 들어 있다. 여기에 오프틱 매매가 2분마다 그
상태를 db-data에 밀기 시작하면, 10분 뒤 스크래핑 런이 몇 분 묵은 CDN 사본으로
되감고 그 되감긴 상태를 다시 배포한다 — 그 사이의 페이퍼 거래가 사라진다.
"""
import os
import sys
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data.storage_manager import StorageManager


def test_skips_http_sync_inside_github_actions(monkeypatch, tmp_path):
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.chdir(tmp_path)
    sm = StorageManager()

    with mock.patch('urllib.request.urlopen') as urlopen:
        sm.sync_from_github(['sim_bulldaytrade_state.json'])

    urlopen.assert_not_called()


def test_still_syncs_outside_actions(monkeypatch, tmp_path):
    """로컬 실행에는 git 체크아웃이 없다 — 그쪽은 CDN이 유일한 경로다."""
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    monkeypatch.chdir(tmp_path)
    sm = StorageManager()

    with mock.patch('urllib.request.urlopen', side_effect=OSError('offline')) as urlopen:
        sm.sync_from_github(['sim_bulldaytrade_state.json'])

    urlopen.assert_called_once()


def test_live_sim_state_is_in_the_sync_list():
    """이 테스트가 깨지면 위 회귀 설명이 낡은 것이다.

    실전 선택 심의 상태 파일이 동기화 대상에 들어 있다는 사실 자체가
    CDN 되감기를 위험하게 만든 원인이다.
    """
    files = StorageManager().get_sync_files_list(datetime(2026, 8, 10))
    assert 'sim_bulldaytrade_state.json' in files
