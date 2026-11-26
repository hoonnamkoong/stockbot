# -*- coding: utf-8 -*-
"""돈 루프가 db-data에서 받는 범위(sparse 패턴)의 불변식.

2026-11-26: db-data `data/`가 713MB·2,471파일로 커져 trading.yml의 복원(38초)과
배포 clone(38초)이 3분 예산을 9초 초과했다 — 장중 80런 중 **성공 1건**이었고 매 런이
`Deploy state`에서 잘렸다. 주문은 나가고 심 상태만 db-data에 도달하지 못하는 모양이다.

타임아웃은 늘릴 수 없다(원장 락 리스 4분보다 짧아야 중복 주문이 안 난다). 그래서
받는 양을 줄이는데, **범위를 화이트리스트로 짜면 빠뜨린 파일이 조용히 백지가 된다** —
그게 2026-08-05 심9-1(배포 목록과 복원 목록이 갈림)과 같은 고장이다. 그래서 무거운
계열만 배제하고, 이 테스트가 "매니페스트가 낼 수 있는 모든 파일이 범위 안"을 지킨다.

매니페스트를 다시 열거하지 않고 **실제 생성 함수를 호출해서** 검사하는 이유: 심이
늘거나 파일명 규칙이 바뀌면 열거본은 조용히 낡는다. 호출본은 같이 따라온다.
"""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts import db_data_sparse as sparse  # noqa: E402
import scripts.trade_loop as trade_loop  # noqa: E402

TODAY = '20261126'


def _all_manifest_names(tmp_path, monkeypatch) -> list[str]:
    """이 런이 낼 수 있는 배포 대상 전체(심 전원 + 국면 + 브리핑 + 순위 + 알림)."""
    monkeypatch.chdir(tmp_path)
    from src.strategy.registry import get_sim_registry
    now = dt.datetime(2026, 11, 26, 10, 30)
    every_sim = {s['id'] for s in get_sim_registry(include_analyzers=True)}
    trade_loop._write_deploy_manifest(
        None, log=lambda *a: None, now=now,
        include_regime=True, include_us_brief=True,
        include_money=now, include_alerts=True,
        extra_sim_ids=every_sim)
    text = (tmp_path / 'data' / '.lite_deploy_manifest').read_text(
        encoding='utf-8')
    names = [n for n in text.split('\n') if n.strip()]
    assert names, '매니페스트가 비어 있으면 이 테스트는 아무것도 지키지 않는다'
    return names


def test_every_deployed_file_survives_the_sparse_range(tmp_path, monkeypatch):
    """배포 대상이 범위 밖이면 그 파일은 **조용히** 안 올라간다.

    skip-worktree가 걸린 경로는 `git add`가 말없이 무시한다 — 런은 초록이고
    심 상태만 사라진다. 배포 목록 ⊆ 복원 범위가 이 설계의 핵심 불변식이다.
    """
    missed = [n for n in _all_manifest_names(tmp_path, monkeypatch)
              if not sparse.keeps(n, TODAY)]
    assert not missed, f'배포하는데 범위 밖인 파일: {missed}'


@pytest.mark.parametrize('name', [
    # 루프가 읽는 입력. 빠지면 국면이 조용히 폴백값으로 고정된다(2026-08-10).
    'kospi_top100_close.csv',
    'sim11_watchlist.json',
    'sim_reset_epoch.json',   # reset_epoch_guard.py가 배포 직전에 읽는다
    'alert_dedup.json',
    'rank_state.json',
    'dart_fundamentals.json',  # 심3 TTM·심11 EPS의 유일한 원천(KIS 404 이후)
])
def test_loop_inputs_stay_in_range(name):
    assert sparse.keeps(name, TODAY), f'{name}이 범위 밖이면 백지에서 시작한다'


@pytest.mark.parametrize('name', [
    'minute_2026-11.csv',       # 43MB — KIS API로 직접 받는다, 파일은 안 읽는다
    'post_titles_2026-11.csv',  # 18MB — 스크래퍼 산출물, 루프는 안 읽는다
    'decisions_20261125_10_actions-trading.csv',  # 어제 것
    'money_2026-08.csv',        # 월별 누적
    'money_2026-11-25.csv',     # 어제 일별
])
def test_heavy_families_are_excluded(name):
    """배제가 실제로 걸려야 절감이 생긴다 — 안 걸리면 예산이 그대로다."""
    assert not sparse.keeps(name, TODAY), f'{name}이 범위 안이면 절감이 없다'


@pytest.mark.parametrize('name', [
    'decisions_20261126_10_actions-trading.csv',
    'decisions_20261126_09_phone.csv',
    'money_2026-11-26.csv',
])
def test_todays_append_files_are_restored(name):
    """오늘 파일은 **그 안에서 append**된다 — 복원 안 하면 매 런이 앞부분을 자른다.

    2026-08-05 심9-1 매매기록 8건이 2행만 남아 있던 고장이 정확히 이것이다.
    """
    assert sparse.keeps(name, TODAY), f'{name}을 복원하지 않으면 잘린다'


def test_patterns_are_rooted_so_they_cannot_match_outside_data():
    """`data/` 밖을 건드리면 루프가 쓰지도 않는 트리를 받거나 지운다."""
    for pat in sparse.patterns(TODAY):
        body = pat[1:] if pat.startswith('!') else pat
        assert body.startswith('/data/'), f'범위를 벗어난 패턴: {pat}'


def test_first_pattern_opens_the_range():
    """git 비-cone 규칙은 마지막 일치가 이긴다 — 여는 패턴이 맨 앞이어야 한다.

    이게 뒤로 밀리면 모든 배제가 무효가 되고 절감이 조용히 0이 된다.
    """
    assert sparse.patterns(TODAY)[0] == '/data/*'
