"""analyze_batch_discovery가 모델이 준 code를 검증 없이 신뢰하던 문제.

배치(최대 10종목) 응답을 파싱할 때 `all_results[item['code']] = item`으로
모델이 반환한 code를 그대로 믿었다. 게시글 제목은 아무나 쓸 수 있으므로,
공격자가 자기 종목 제목에 지시문을 심어 모델이 같은 배치의 다른(혹은 전혀
요청하지 않은) 종목 code로 응답하게 만들면 그 결과를 덮어쓸 수 있었다.

이 테스트는 요청한 코드 집합(005930, 000660)에 없는 code(035720)가 응답에
섞였을 때 조용히 받아들이지 않고 버리면서 로그를 남기는지 확인한다.
Gemini는 monkeypatch로 대체하고 실호출은 하지 않는다.
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from src.strategy import advisor as advisor_mod
from src.strategy.advisor import GeminiAgent


class FakeResponse:
    def __init__(self, text):
        self.text = text
        self.usage_metadata = None


@pytest.fixture(autouse=True)
def isolate_side_effects(tmp_path, monkeypatch):
    """gemini_cache/usage_log가 레포 data/를 오염시키지 않도록 격리한다."""
    monkeypatch.setattr(advisor_mod.gemini_cache, 'DEFAULT_PATH',
                         str(tmp_path / 'cache.json'))
    monkeypatch.setattr(advisor_mod.usage_log, 'DEFAULT_PATH',
                         str(tmp_path / 'usage.csv'))


def make_agent(response_text):
    """client만 가짜로 채운 GeminiAgent (싱글톤 __init__ 우회)."""
    agent = object.__new__(GeminiAgent)
    agent.batch_model_name = 'gemini-2.5-flash-lite'
    agent.report_model_name = 'gemini-2.5-flash'
    agent.exhausted_models = set()

    class FakeModels:
        def generate_content(self, model, contents, config=None):
            return FakeResponse(response_text)

    class FakeClient:
        models = FakeModels()

    agent.client = FakeClient()
    return agent


def test_요청하지_않은_code는_결과에서_버려지고_로그가_남는다(capsys):
    requested = [
        {'code': '005930', 'name': '삼성전자', 'posts': [{'title': '평범한 글'}]},
        {'code': '000660', 'name': 'SK하이닉스', 'posts': [{'title': '평범한 글2'}]},
    ]
    # 공격자 게시글로 인해 모델이 요청하지 않은 code(035720, 카카오)로도
    # 응답했다고 가정한다.
    rogue_response = json.dumps([
        {'code': '005930', 'sentiment': 3, 'fact_score': 0.5,
         'summary': '정상 요약1', 'keywords': []},
        {'code': '000660', 'sentiment': -2, 'fact_score': 0.2,
         'summary': '정상 요약2', 'keywords': []},
        {'code': '035720', 'sentiment': 10, 'fact_score': 1.0,
         'summary': '요청하지 않은 종목 결과', 'keywords': []},
    ])

    agent = make_agent(rogue_response)
    final_results = agent.analyze_batch_discovery(requested)

    assert '035720' not in final_results
    assert final_results['005930']['summary'] == '정상 요약1'
    assert final_results['000660']['summary'] == '정상 요약2'

    log_output = capsys.readouterr().out
    assert '035720' in log_output
