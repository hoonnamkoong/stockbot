"""[W1] 같은 글을 하루에 여러 번 다시 분석하지 않는다.

2026-07-28 계측: 하루 39런에서 3,100글이 Gemini로 갔다. 채택 임계값이 시간대별
누적이라 같은 종목이 반복 선정되는데 그 종목의 상위 5개 글은 대개 그대로다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import csv
import json

from src.data import gemini_cache
from src.strategy import advisor as advisor_mod
from src.strategy.advisor import GeminiAgent


# ── 캐시 모듈 ────────────────────────────────────────────
def test_key_ignores_post_order():
    """같은 글 묶음이 다른 순서로 와도 프롬프트 내용은 같다."""
    a = gemini_cache.make_key('005930', [{'nid': '2'}, {'nid': '1'}])
    b = gemini_cache.make_key('005930', [{'nid': '1'}, {'nid': '2'}])
    assert a == b


def test_key_changes_when_posts_change():
    """글이 바뀌면 자동으로 미스가 된다 — 그래서 무효화 로직이 필요 없다."""
    a = gemini_cache.make_key('005930', [{'nid': '1'}])
    b = gemini_cache.make_key('005930', [{'nid': '1'}, {'nid': '9'}])
    assert a != b


def test_key_separates_codes():
    assert gemini_cache.make_key('005930', []) != gemini_cache.make_key('000660', [])


def test_roundtrip(tmp_path):
    p = str(tmp_path / 'c.json')
    gemini_cache.save({'k': {'sentiment': 3}}, path=p, today='20260728')
    assert gemini_cache.load(path=p, today='20260728') == {'k': {'sentiment': 3}}


def test_discarded_on_new_day(tmp_path):
    """날짜가 넘어가면 글·추천수가 리셋되므로 통째로 버린다."""
    p = str(tmp_path / 'c.json')
    gemini_cache.save({'k': {'sentiment': 3}}, path=p, today='20260728')
    assert gemini_cache.load(path=p, today='20260729') == {}


def test_missing_file_returns_empty(tmp_path):
    assert gemini_cache.load(path=str(tmp_path / 'none.json')) == {}


def test_corrupt_file_returns_empty(tmp_path):
    p = tmp_path / 'c.json'
    p.write_text('{깨진', encoding='utf-8')
    assert gemini_cache.load(path=str(p)) == {}


# ── advisor 배선 ─────────────────────────────────────────
class FakeResponse:
    def __init__(self, text):
        self.text = text
        self.usage_metadata = None


def make_agent(response_text, calls):
    agent = object.__new__(GeminiAgent)
    agent.batch_model_name = 'gemini-2.5-flash-lite'
    agent.report_model_name = 'gemini-2.5-flash'
    agent.exhausted_models = set()

    class FakeModels:
        def generate_content(self, model, contents, config=None):
            calls.append(contents)
            return FakeResponse(response_text)

    class FakeClient:
        models = FakeModels()

    agent.client = FakeClient()
    return agent


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(advisor_mod.usage_log, 'DEFAULT_PATH', str(tmp_path / 'usage.csv'))
    monkeypatch.setattr(advisor_mod.gemini_cache, 'DEFAULT_PATH', str(tmp_path / 'cache.json'))


BATCH = [{'code': '005930', 'name': '삼성전자', 'posts': [{'nid': '1', 'title': 'ㄱ'}]}]
ANSWER = json.dumps([{'code': '005930', 'sentiment': 5, 'summary': '요약', 'keywords': []}])


def test_second_run_hits_cache(monkeypatch, tmp_path):
    """같은 nid 묶음이면 두 번째 런은 Gemini를 호출하지 않는다."""
    _isolate(monkeypatch, tmp_path)
    calls = []

    first = make_agent(ANSWER, calls).analyze_batch_discovery(BATCH)
    assert first['005930']['sentiment'] == 5
    assert len(calls) == 1

    second = make_agent(ANSWER, calls).analyze_batch_discovery(BATCH)
    assert second['005930']['sentiment'] == 5
    assert len(calls) == 1, "캐시 적중인데 다시 호출했다"


def test_changed_posts_miss_cache(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    calls = []
    make_agent(ANSWER, calls).analyze_batch_discovery(BATCH)

    changed = [{'code': '005930', 'name': '삼성전자',
                'posts': [{'nid': '1'}, {'nid': '2'}]}]
    make_agent(ANSWER, calls).analyze_batch_discovery(changed)
    assert len(calls) == 2


def test_failed_response_is_not_cached(monkeypatch, tmp_path):
    """실패를 캐시하면 그 종목이 하루 종일 '분석 오류'로 굳는다."""
    _isolate(monkeypatch, tmp_path)
    calls = []

    bad = make_agent('완전히 깨진 응답', calls).analyze_batch_discovery(BATCH)
    assert bad['005930']['summary'] == '분석 오류'

    good = make_agent(ANSWER, calls).analyze_batch_discovery(BATCH)
    assert good['005930']['sentiment'] == 5
    assert len(calls) == 2, "실패 응답이 캐시돼 재시도가 막혔다"


def test_cache_stats_are_logged(monkeypatch, tmp_path):
    """W1의 실제 절감량을 추정이 아니라 실측으로 남긴다."""
    _isolate(monkeypatch, tmp_path)
    calls = []
    make_agent(ANSWER, calls).analyze_batch_discovery(BATCH)
    make_agent(ANSWER, calls).analyze_batch_discovery(BATCH)

    rows = list(csv.DictReader(open(tmp_path / 'usage.csv', encoding='utf-8')))
    stats = [r for r in rows if r['event'] == 'cache_summary']
    assert [(r['cache_hit'], r['cache_miss']) for r in stats] == [('0', '1'), ('1', '0')]
