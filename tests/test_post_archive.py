import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import csv

from src.data import post_archive


def rows(path):
    return list(csv.DictReader(open(path, encoding='utf-8')))


def test_writes_header_and_row(tmp_path):
    p = tmp_path / 'titles.csv'
    post_archive.append([
        {'date': '2026-07-27', 'code': '005930', 'name': '삼성전자',
         'nid': '1', 'title': '가즈아', 'likes': 5},
    ], path=str(p))

    r = rows(p)
    assert len(r) == 1
    assert r[0]['nid'] == '1' and r[0]['title'] == '가즈아'
    assert set(post_archive.COLUMNS) == set(r[0].keys())


def test_dedupes_against_existing_nids(tmp_path):
    """스크래퍼는 하루 여러 번 돌며 같은 글을 다시 본다. 중복 적재하면
    사전 검증의 빈도 통계가 실행 횟수에 비례해 부풀려진다."""
    p = tmp_path / 'titles.csv'
    batch = [{'date': '2026-07-27', 'code': '005930', 'name': '삼성전자',
              'nid': '1', 'title': 'A', 'likes': 1}]
    post_archive.append(batch, path=str(p))
    post_archive.append(batch, path=str(p))          # 같은 런 재실행
    post_archive.append(batch + [
        {'date': '2026-07-27', 'code': '005930', 'name': '삼성전자',
         'nid': '2', 'title': 'B', 'likes': 2}], path=str(p))

    r = rows(p)
    assert [x['nid'] for x in r] == ['1', '2']


def test_dedupes_within_one_batch(tmp_path):
    p = tmp_path / 'titles.csv'
    post_archive.append([
        {'date': '2026-07-27', 'code': '005930', 'name': 'A', 'nid': '9',
         'title': 'x', 'likes': 0},
        {'date': '2026-07-27', 'code': '005930', 'name': 'A', 'nid': '9',
         'title': 'x', 'likes': 0},
    ], path=str(p))

    assert len(rows(p)) == 1


def test_newline_in_title_does_not_break_columns(tmp_path):
    """게시글 제목에 개행이 섞여도 CSV 열이 밀리면 안 된다."""
    p = tmp_path / 'titles.csv'
    post_archive.append([
        {'date': '2026-07-27', 'code': '005930', 'name': 'A', 'nid': '3',
         'title': '줄1\n줄2', 'likes': 1},
    ], path=str(p))

    r = rows(p)
    assert len(r) == 1
    assert r[0]['likes'] == '1'


def test_empty_batch_creates_nothing(tmp_path):
    p = tmp_path / 'titles.csv'
    post_archive.append([], path=str(p))
    assert not p.exists()


def test_failure_is_swallowed(tmp_path):
    """아카이브 실패가 스크래퍼 런을 죽이면 안 된다."""
    post_archive.append(
        [{'date': 'd', 'code': 'c', 'name': 'n', 'nid': '1', 'title': 't', 'likes': 0}],
        path=str(tmp_path / 'no_such_dir' / 'x.csv'))


def test_month_path_from_date():
    assert post_archive.month_path('2026-07-27').endswith('post_titles_2026-07.csv')


def test_worker_queues_all_titles_not_just_top5(monkeypatch):
    """상위 5개로 자르기 전 전수가 큐에 담겨야 한다.
    사전 검증에는 전수가 필요하다."""
    from src.pipeline.workers.data_fetcher import DataFetcherWorker

    w = object.__new__(DataFetcherWorker)
    w._reset_body_stats()

    class Ctx:
        today_str = '2026-07-27'
    w.ctx = Ctx()

    posts = [{'nid': str(i), 'title': f't{i}', 'likes': i} for i in range(12)]
    w._queue_titles({'code': '005930', 'name': '삼성전자'}, posts)

    assert len(w._title_rows) == 12
    assert w._title_rows[0]['date'] == '2026-07-27'
    assert w._title_rows[0]['code'] == '005930'


def test_worker_queue_handles_empty(monkeypatch):
    from src.pipeline.workers.data_fetcher import DataFetcherWorker
    w = object.__new__(DataFetcherWorker)
    w._reset_body_stats()

    class Ctx:
        today_str = '2026-07-27'
    w.ctx = Ctx()

    w._queue_titles({'code': 'c', 'name': 'n'}, [])
    assert w._title_rows == []
