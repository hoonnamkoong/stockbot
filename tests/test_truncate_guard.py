# -*- coding: utf-8 -*-
"""이력 절단은 force-push다 — 남이 쓰고 있으면 그 커밋이 사라진다.

db-data에는 하루 100회 넘게 push가 들어온다(trading 2분 루프, scraper, premarket,
eod, us_*). 그 사이에 force-push하면 **그 사이 들어온 커밋이 통째로 없어진다.**
심 상태·매매 기록이 거기 있다.

그래서 절단 전에 두 겹으로 막는다:
  1. db-data에 쓰는 워크플로가 하나라도 돌고 있으면 거부한다(이 파일)
  2. clone 시점의 원격 HEAD가 push 직전까지 그대로인지 확인한다(워크플로 셸)

2번만으로도 안전하지만, 1번이 없으면 마감 후 창을 놓친 실행이 매번 2번에서
막히기만 하고 왜 막혔는지 안 보인다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.truncate_data_branch import DB_DATA_WRITERS, busy_writers


def _run(name, status, conclusion=None):
    return {'name': name, 'status': status, 'conclusion': conclusion}


def test_쓰는_워크플로가_돌고_있으면_이름을_돌려준다():
    runs = [_run('Trading (실전 매매)', 'in_progress'),
            _run('Stock Scraper Schedule', 'completed', 'success')]
    assert busy_writers(runs, {'Trading (실전 매매)', 'Stock Scraper Schedule'}) \
        == ['Trading (실전 매매)']


def test_대기중도_바쁜_것으로_센다():
    """queued는 곧 시작한다 — 절단 도중에 깨어나면 같은 사고다."""
    runs = [_run('Stock Scraper Schedule', 'queued')]
    assert busy_writers(runs, {'Stock Scraper Schedule'}) == ['Stock Scraper Schedule']


def test_다_끝났으면_비어_있다():
    runs = [_run('Trading (실전 매매)', 'completed', 'success'),
            _run('EOD Data Collection', 'completed', 'cancelled')]
    assert busy_writers(runs, DB_DATA_WRITERS) == []


def test_db_data를_안_쓰는_워크플로는_무시한다():
    """Tests·PR Checklist가 돌고 있다고 절단을 막을 이유는 없다."""
    runs = [_run('Tests', 'in_progress'), _run('PR Checklist', 'in_progress')]
    assert busy_writers(runs, DB_DATA_WRITERS) == []


def test_쓰는_워크플로_목록이_실제_배포_경로를_덮는다():
    """새 워크플로가 db-data에 쓰기 시작하면 이 목록도 같이 늘어야 한다.

    목록이 낡으면 가드가 조용히 헐거워진다 — 이 레포가 여러 번 겪은 모양이다
    (sync-files-list-stale-hardcode).
    """
    import yaml
    wf_dir = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')
    writers = set()
    for n in sorted(os.listdir(wf_dir)):
        if not n.endswith('.yml'):
            continue
        raw = open(os.path.join(wf_dir, n), encoding='utf-8').read()
        if 'push origin db-data' not in raw:
            continue
        writers.add(yaml.safe_load(raw)['name'])
    missing = writers - set(DB_DATA_WRITERS)
    assert not missing, (
        f'{sorted(missing)}가 db-data에 push하는데 DB_DATA_WRITERS에 없다 — '
        '절단이 그 커밋을 지운다')
