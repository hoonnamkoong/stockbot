"""실거래 기록을 비공개 레포에 직접 쓰는 경로.

핵심은 '덮어쓰지 않는 것'이다. 조회 실패를 빈 파일로 읽고 쓰면 기존 기록이
통째로 날아간다 — 2026-07-08에 179만원어치 청산이 집계에서 사라진 것과 같은 종류의
사고다. 그리고 충돌은 최신본을 다시 읽어 그 위에 얹어야 한다.
"""
import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.trade import secret_store


def _quiet(*a, **k):
    pass


def test_fetch_distinguishes_missing_from_failure():
    """404(없음)와 500(실패)를 가른다 — 실패를 빈 내용으로 읽으면 안 된다."""
    with mock.patch.object(secret_store, '_token', return_value='t'), \
         mock.patch.object(secret_store.requests, 'get',
                           return_value=mock.Mock(status_code=404)):
        assert secret_store.fetch_text('x.json', _quiet) == ('', None)

    with mock.patch.object(secret_store, '_token', return_value='t'), \
         mock.patch.object(secret_store.requests, 'get',
                           return_value=mock.Mock(status_code=500)):
        assert secret_store.fetch_text('x.json', _quiet) == (None, None)


def test_update_aborts_when_fetch_fails():
    """조회 실패 시 쓰지 않는다. 쓰면 기존 기록을 백지로 덮는다."""
    with mock.patch.object(secret_store, 'fetch_text', return_value=(None, None)), \
         mock.patch.object(secret_store, 'put_text') as put:
        ok = secret_store.update_text('x.json', lambda c: 'new', 'msg', _quiet)

    assert ok is False
    put.assert_not_called()


def test_update_retries_on_conflict_with_fresh_content():
    """충돌하면 최신본을 다시 읽어 그 위에 얹는다 (덮어쓰기 금지)."""
    seen = []
    fetches = [('A', 'sha1'), ('A-then-B', 'sha2')]

    def fake_fetch(path, log=print):
        return fetches.pop(0)

    def fake_put(path, content, sha, message, log=print):
        seen.append((content, sha))
        return sha == 'sha2'  # 첫 시도는 충돌

    with mock.patch.object(secret_store, 'fetch_text', side_effect=fake_fetch), \
         mock.patch.object(secret_store, 'put_text', side_effect=fake_put):
        ok = secret_store.update_text('x.txt', lambda c: c + '+mine', 'msg', _quiet)

    assert ok is True
    assert seen[0] == ('A+mine', 'sha1')
    assert seen[1] == ('A-then-B+mine', 'sha2'), '재시도는 최신본 위에 얹어야 한다'


def test_append_json_list_preserves_existing_records():
    captured = {}

    def fake_update(path, transform, message, log=print):
        captured['out'] = transform(json.dumps([{'code': 'old'}]))
        return True

    with mock.patch.object(secret_store, 'update_text', side_effect=fake_update):
        secret_store.append_json_list('order_history.json', {'code': 'new'}, 'msg', _quiet)

    items = json.loads(captured['out'])
    assert [i['code'] for i in items] == ['new', 'old'], '최신이 앞, 기존은 보존'


def test_append_json_list_does_not_wipe_on_parse_failure():
    """파싱 못 하는 파일을 빈 배열로 갈아엎지 않는다."""
    def fake_update(path, transform, message, log=print):
        transform('{{{ not json')
        return True

    with mock.patch.object(secret_store, 'update_text', side_effect=fake_update):
        ok = secret_store.append_json_list('order_history.json', {'code': 'new'}, 'msg', _quiet)

    assert ok is False


def test_append_csv_row_writes_header_only_when_empty():
    captured = []

    def fake_update(path, transform, message, log=print):
        captured.append(transform(''))
        captured.append(transform('h1,h2\na,b\n'))
        return True

    with mock.patch.object(secret_store, 'update_text', side_effect=fake_update):
        secret_store.append_csv_row('t.csv', 'x,y', 'h1,h2', 'msg', _quiet)

    assert captured[0].endswith('h1,h2\nx,y\n')
    assert captured[1] == 'h1,h2\na,b\nx,y\n', '기존 행 뒤에 붙어야 한다'


def test_append_csv_row_handles_file_without_trailing_newline():
    captured = {}

    def fake_update(path, transform, message, log=print):
        captured['out'] = transform('h1,h2\na,b')
        return True

    with mock.patch.object(secret_store, 'update_text', side_effect=fake_update):
        secret_store.append_csv_row('t.csv', 'x,y', 'h1,h2', 'msg', _quiet)

    assert captured['out'] == 'h1,h2\na,b\nx,y\n'
