import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from src.pipeline.workers import llm_analyzer
from src.pipeline.workers.llm_analyzer import LLMAnalyzerWorker


class FakeCtx:
    scrape_pages_failed = 0
    scrape_pages_total = 100
    today_str = '20260710'
    now_kst = None

    def log(self, msg): pass

    def scrape_degraded(self):
        from src.pipeline.context import PipelineContext
        return PipelineContext.scrape_degraded(self)


class FakeStorage:
    def __init__(self): self.saved = []
    def save_latest_stocks(self, stocks, now_kst): self.saved.append(stocks)


@pytest.fixture(autouse=True)
def chdir_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def make_worker():
    w = object.__new__(LLMAnalyzerWorker)
    w.ctx = FakeCtx()
    w.storage = FakeStorage()
    return w


def test_ai_batch_receives_active_only(monkeypatch):
    """추적 종목은 Gemini 배치 대상이 아니다."""
    seen = []
    monkeypatch.setattr(llm_analyzer, 'analyze_batch', lambda c: seen.extend(x['code'] for x in c) or {})
    w = make_worker()
    active = [{'code': '111111', 'status': '활성'}]
    tracked = [{'code': '222222', 'status': '추적'}]

    w._analyze_active(active + tracked)

    assert seen == ['111111']


def test_tracked_stock_reuses_cached_summary(monkeypatch):
    from src.data import adopted_registry
    adopted_registry.save('20260710', {
        '222222': {'name': '비엘팜텍', 'market': 'KOSDAQ',
                   'ai': {'posts_summary': '캐시된 요약', 'sentiment': 'Positive', 'keywords': ['텅스텐']}},
    })
    w = make_worker()
    tracked = [{'code': '222222', 'status': '추적'}]

    w._apply_cached_ai(tracked)

    assert tracked[0]['posts_summary'] == '캐시된 요약'
    assert tracked[0]['sentiment'] == 'Positive'


def test_persist_updates_registry(monkeypatch):
    from src.data import adopted_registry
    monkeypatch.setattr(llm_analyzer.analyzer, 'analyze_discussion_trend', lambda c: (c, None))
    monkeypatch.setattr(llm_analyzer.analyzer, 'save_data', lambda df: None)
    w = make_worker()

    w._persist([{'code': '111111', 'name': '금호건설', 'market': 'KOSPI', 'status': '활성',
                 'posts_summary': '요약', 'sentiment': 'Positive', 'keywords': []}])

    assert '111111' in adopted_registry.load('20260710')


def test_degraded_run_does_not_touch_registry(monkeypatch):
    from src.data import adopted_registry
    w = make_worker()
    w.ctx.scrape_pages_failed = 50

    assert w._persist([{'code': '111111', 'status': '활성'}]) is False
    assert adopted_registry.load('20260710') == {}


def test_round_trip_active_then_tracked_keeps_ai_summary(monkeypatch):
    """09시에 활성 상태로 저장된 AI 요약/감성/키워드가 11시 추적 상태까지 그대로 이어져야 한다."""
    monkeypatch.setattr(llm_analyzer.analyzer, 'analyze_discussion_trend', lambda c: (c, None))
    monkeypatch.setattr(llm_analyzer.analyzer, 'save_data', lambda df: None)
    w = make_worker()

    # 1차 런(09:00): 활성 종목으로 AI 분석 결과를 저장한다.
    w._persist([{
        'code': '111111', 'status': '활성',
        'posts_summary': '요약1', 'sentiment': 'Positive',
        'keywords': ['키워드1', '키워드2'],
    }])

    # 2차 런(11:00): 같은 종목이 추적 상태로 넘어온다 (AI 필드 없이 새로 만든 dict).
    tracked = {'code': '111111', 'status': '추적'}
    w._apply_cached_ai([tracked])
    w._persist([tracked])

    saved = w.storage.saved[-1]
    assert saved[0]['posts_summary'] == '요약1'
    assert saved[0]['sentiment'] == 'Positive'
    assert saved[0]['keywords'] == ['키워드1', '키워드2']


def test_missing_keywords_key_does_not_erase_cached_keywords(monkeypatch):
    """Gemini가 일부 종목을 배치 결과에서 누락하면 s에는 'keywords' 키 자체가 없다
    (StockData.to_dict()는 top_keywords만 만든다). 이런 반쪽 결과가 레지스트리에
    이미 저장된 keywords를 빈 리스트로 덮어써서는 안 된다."""
    monkeypatch.setattr(llm_analyzer.analyzer, 'analyze_discussion_trend', lambda c: (c, None))
    monkeypatch.setattr(llm_analyzer.analyzer, 'save_data', lambda df: None)
    from src.data import adopted_registry
    w = make_worker()

    # 1차 런: 정상적으로 키워드가 캐시된 상태를 만든다.
    w._persist([{
        'code': '111111', 'status': '활성',
        'posts_summary': '요약1', 'sentiment': 'Positive',
        'keywords': ['키워드1', '키워드2'],
    }])

    # 2차 런: Gemini가 이 종목을 배치 결과에서 누락 -> 'keywords' 키 자체가 없음
    w._persist([{
        'code': '111111', 'status': '활성',
        'posts_summary': '요약2', 'sentiment': 'Neutral',
        # 'keywords' 키 없음
    }])

    registry = adopted_registry.load('20260710')
    assert registry['111111']['ai']['keywords'] == ['키워드1', '키워드2']
