"""국면 생산자(Sim0)와 소비자의 실행 순서.

심6은 2026-10-01 GTAA-KR5(상시 자산배분, 국면 무관)로 재목적화돼 더는 국면을 읽지
않는다 — 구 인버스 심의 국면 게이트 테스트는 그때 정리했다(국면 무관 동작은
tests/test_sim6_gtaa.py가 본다). 남은 국면 소비자는 Sim10이다.
"""
import os

import yaml

_MANIFEST = os.path.join(os.path.dirname(__file__), '..', 'src', 'strategy', 'strategy_manifest.yaml')


def test_libero_runs_before_its_consumers():
    """Sim0가 뒤에 있으면 Sim10은 항상 직전 사이클의 국면으로 판단한다.

    get_active_simulators가 매니페스트 순서를 그대로 보존하고, 그 순서가
    trade_engine의 실행 순서다(소비자 1곳). 국면이 뒤집히는 사이클에서
    한 박자 늦는 것을 막는다.
    """
    with open(_MANIFEST, encoding='utf-8') as f:
        ids = [s['id'] for s in yaml.safe_load(f)['simulators']]
    producer = ids.index('sim0_libero')
    assert producer < ids.index('sim10_orchestrator'), \
        "sim0_libero가 sim10_orchestrator보다 뒤에 있다 — 국면이 한 사이클 낡는다"


def test_sim6_no_longer_reads_regime():
    src = open(os.path.join(os.path.dirname(__file__), '..', 'src', 'strategy',
                            'simulators', 'sim6_bear_hedge.py'), encoding='utf-8').read()
    assert 'read_regime' not in src
