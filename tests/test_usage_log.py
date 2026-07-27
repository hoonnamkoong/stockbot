import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import csv

from src.data import usage_log


def test_creates_file_with_header(tmp_path):
    """첫 기록에서 헤더가 만들어져야 한다."""
    path = tmp_path / 'gemini_usage.csv'
    usage_log.append({'event': 'batch_call', 'model': 'flash-lite'}, path=str(path))

    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    assert len(rows) == 1
    assert rows[0]['event'] == 'batch_call'
    assert rows[0]['model'] == 'flash-lite'
    assert set(usage_log.COLUMNS) == set(rows[0].keys())


def test_appends_without_duplicating_header(tmp_path):
    """두 번째 기록은 헤더 없이 뒤에 붙어야 한다."""
    path = tmp_path / 'gemini_usage.csv'
    usage_log.append({'event': 'batch_call', 'total_tokens': 100}, path=str(path))
    usage_log.append({'event': 'batch_call', 'total_tokens': 200}, path=str(path))

    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    assert [r['total_tokens'] for r in rows] == ['100', '200']


def test_unknown_field_is_dropped(tmp_path):
    """스키마에 없는 키가 들어와도 CSV 정합성이 깨지면 안 된다."""
    path = tmp_path / 'gemini_usage.csv'
    usage_log.append({'event': 'batch_call', 'nonexistent': 'x'}, path=str(path))

    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    assert 'nonexistent' not in rows[0]
    assert rows[0]['event'] == 'batch_call'


def test_missing_fields_become_blank(tmp_path):
    """일부 필드만 채운 행도 컬럼 수가 맞아야 한다."""
    path = tmp_path / 'gemini_usage.csv'
    usage_log.append({'event': 'run_summary', 'body_ok': 3, 'body_fail': 2}, path=str(path))

    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    assert rows[0]['prompt_tokens'] == ''
    assert rows[0]['body_ok'] == '3'


def test_timestamp_is_filled(tmp_path):
    """호출부가 timestamp를 안 넘겨도 기록 시각이 남아야 한다."""
    path = tmp_path / 'gemini_usage.csv'
    usage_log.append({'event': 'batch_call'}, path=str(path))

    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    assert rows[0]['timestamp']


def test_write_failure_is_swallowed(tmp_path):
    """계측 실패가 스크래퍼 런을 죽이면 안 된다."""
    bad = tmp_path / 'nonexistent_dir' / 'x.csv'
    usage_log.append({'event': 'batch_call'}, path=str(bad))  # 예외가 나면 테스트 실패
