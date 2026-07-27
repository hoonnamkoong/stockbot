import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import csv
import json

import pytest

from src.strategy import advisor as advisor_mod
from src.strategy.advisor import GeminiAgent


class FakeUsage:
    def __init__(self, p, o, t):
        self.prompt_token_count = p
        self.candidates_token_count = o
        self.total_token_count = t


class FakeResponse:
    def __init__(self, text, usage=None):
        self.text = text
        self.usage_metadata = usage


def read_rows(path):
    return list(csv.DictReader(open(path, encoding='utf-8')))


def make_agent(monkeypatch, response):
    """client만 가짜로 채운 GeminiAgent."""
    agent = object.__new__(GeminiAgent)
    agent.batch_model_name = 'gemini-2.5-flash-lite'
    agent.report_model_name = 'gemini-2.5-flash'
    agent.exhausted_models = set()

    class FakeModels:
        def generate_content(self, model, contents, config=None):
            return response

    class FakeClient:
        models = FakeModels()

    agent.client = FakeClient()
    return agent


def test_call_records_token_usage(monkeypatch, tmp_path):
    """usage_metadata의 토큰 3종이 기록되어야 한다."""
    path = tmp_path / 'usage.csv'
    monkeypatch.setattr(advisor_mod.usage_log, 'DEFAULT_PATH', str(path))

    agent = make_agent(monkeypatch, FakeResponse('{}', FakeUsage(9000, 1100, 10100)))
    agent._call_gemini_safe('프롬프트', model_type='batch')

    rows = read_rows(path)
    assert len(rows) == 1
    assert rows[0]['event'] == 'batch_call'
    assert rows[0]['model'] == 'gemini-2.5-flash-lite'
    assert rows[0]['prompt_tokens'] == '9000'
    assert rows[0]['output_tokens'] == '1100'
    assert rows[0]['total_tokens'] == '10100'


def test_prompt_chars_recorded_when_usage_missing(monkeypatch, tmp_path):
    """SDK가 usage_metadata를 안 주는 경우에도 프롬프트 길이는 남아야 한다.

    토큰을 0으로 채우면 '측정됨 0'과 '측정 불가'가 구분되지 않는다.
    """
    path = tmp_path / 'usage.csv'
    monkeypatch.setattr(advisor_mod.usage_log, 'DEFAULT_PATH', str(path))

    agent = make_agent(monkeypatch, FakeResponse('{}', None))
    agent._call_gemini_safe('12345', model_type='batch')

    rows = read_rows(path)
    assert rows[0]['total_tokens'] == ''
    assert rows[0]['req_chars'] == '5'


def test_batch_records_requested_and_returned_counts(monkeypatch, tmp_path):
    """10개 요청에 8개만 응답하면 누락이 보여야 한다."""
    path = tmp_path / 'usage.csv'
    monkeypatch.setattr(advisor_mod.usage_log, 'DEFAULT_PATH', str(path))

    returned = [{'code': f'{i:06d}', 'sentiment': 1, 'summary': 's', 'keywords': []}
                for i in range(8)]
    agent = make_agent(monkeypatch,
                       FakeResponse(json.dumps(returned), FakeUsage(100, 20, 120)))

    batch = [{'code': f'{i:06d}', 'name': f'종목{i}',
              'posts': [{'title': 't', 'body': 'b'}]} for i in range(10)]
    agent.analyze_batch_discovery(batch)

    rows = [r for r in read_rows(path) if r['event'] == 'batch_call']
    assert rows[-1]['req_stocks'] == '10'
    assert rows[-1]['resp_stocks'] == '8'


def test_batch_records_posts_sent(monkeypatch, tmp_path):
    """프롬프트에 실제로 실린 게시글 수가 기록되어야 한다 (표본 확대 판단 근거)."""
    path = tmp_path / 'usage.csv'
    monkeypatch.setattr(advisor_mod.usage_log, 'DEFAULT_PATH', str(path))

    agent = make_agent(monkeypatch, FakeResponse('[]', FakeUsage(100, 20, 120)))
    batch = [{'code': '000001', 'name': 'A',
              'posts': [{'title': 't', 'body': 'b'}] * 5},
             {'code': '000002', 'name': 'B',
              'posts': [{'title': 't', 'body': 'b'}] * 3}]
    agent.analyze_batch_discovery(batch)

    rows = [r for r in read_rows(path) if r['event'] == 'batch_call']
    assert rows[-1]['req_posts'] == '8'
