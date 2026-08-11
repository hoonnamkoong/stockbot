"""AI 장애 시 규칙 기반 폴백이 외인수급 부호를 감정인 척 채우지 않는다.

과거엔 `s['sentiment'] = "Positive" if foreign_change > 0 else "Negative"`였다 —
이건 감정 측정이 아니라 수급 축의 사본이라, Gemini가 막힌 날에도 마치 감정을
잰 것처럼 보이는 값이 나갔다. "측정 불가"로 명시해야 소비자가 그날 값을
믿으면 안 된다는 걸 알 수 있다.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from src.pipeline.workers import llm_analyzer
from src.pipeline.workers.llm_analyzer import LLMAnalyzerWorker


class FakeCtx:
    scrape_pages_failed = 0
    scrape_pages_total = 100
    today_str = '20260811'
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


def test_fallback_marks_sentiment_as_unmeasured_not_foreign_flow_direction():
    w = make_worker()
    candidates = [
        {'code': '005930', 'name': '삼성전자', 'status': '활성', 'foreign_change': 1.5},
        {'code': '000660', 'name': 'SK하이닉스', 'status': '활성', 'foreign_change': -0.8},
    ]

    out = w._run_rule_based_fallback(candidates)

    for c in out:
        assert c['sentiment'] == '측정 불가'


def test_fallback_never_writes_positive_or_negative_strings():
    """예전 폴백 값('Positive'/'Negative')이 다시 새어나오면 안 된다 —
    그건 외인수급 부호의 사본이지 감정이 아니다."""
    w = make_worker()
    candidates = [{'code': 'A', 'status': '활성', 'foreign_change': 5.0},
                  {'code': 'B', 'status': '활성', 'foreign_change': -5.0}]

    out = w._run_rule_based_fallback(candidates)

    sentiments = {c['sentiment'] for c in out}
    assert 'Positive' not in sentiments
    assert 'Negative' not in sentiments
