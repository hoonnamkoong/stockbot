"""Sim0(리베로)가 쓴 국면 판단을 읽는 유일한 창구.

국면 파일은 생산자가 하나(Sim0)인데 소비자가 넷이다 — Sim6·Sim10의 매매 게이트,
파이프라인 Stage 3.6의 Sim7 게이트, 월간 엑셀. 넷이 각자 파일명을 적고 각자
`json.load(...).get("current_regime")`을 하고 있었다. 심 목록이 여섯 곳에
복제돼 있던 것과 같은 병이다: 생산자 쪽 키가 바뀌면 한 곳만 고치고 나머지는
조용히 옛 값(또는 실패 폴백)으로 돈다.

파일명은 매니페스트가 안다 — 분석기 심의 state_file이다. 여기서 다시 적지 않는다.

**실패는 값이 아니다.** 읽지 못하면 None을 돌려주고, 무엇을 할지는 호출자가
정한다. 국면을 모르는 것과 'SIDEWAYS'는 다르고, bull_score를 모르는 것과
50점은 다르다 — 뭉개면 지어낸 국면으로 실제 주문이 나간다.
"""
import json
import os

from src.strategy.registry import get_sim_registry

VALID_REGIMES = ('BULL', 'SIDEWAYS', 'BEAR')

# 이 파일 기준 ../../data — base_simulator가 self.data_dir을 만드는 방식과 같다.
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data')


def regime_state_filename() -> str:
    """국면 상태 파일명. 매니페스트의 분석기 심에서 파생한다.

    분석기가 정확히 하나라는 전제가 깨지면 여기서 죽는다 — 어느 심의 국면을
    읽을지 코드가 조용히 고르게 두는 것보다 낫다. 매니페스트를 고치는 순간
    CI가 잡는다(tests/test_regime_state.py).
    """
    analyzers = [s for s in get_sim_registry(include_analyzers=True) if s['analyzer']]
    if len(analyzers) != 1:
        raise ValueError(
            f'[RegimeState] 매니페스트의 분석기 심이 {len(analyzers)}개다(1개여야 한다): '
            f"{[s['id'] for s in analyzers]}")
    return analyzers[0]['state_file']


def read_regime_state(data_dir=None) -> dict | None:
    """국면 상태 파일 전체를 dict로 읽는다. 읽지 못하면 None.

    metrics까지 필요한 소비자(월간 엑셀)를 위해 원본을 그대로 준다.
    """
    base = DEFAULT_DATA_DIR if data_dir is None else data_dir
    try:
        with open(os.path.join(base, regime_state_filename()), 'r', encoding='utf-8-sig') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def regime_hint() -> str | None:
    """trade_loop이 dispatch inputs로 실어 보낸 국면. 없거나 알 수 없는 값이면 None.

    파일로만 주고받으면 스크래퍼는 **정상 경로에서 항상** 한 격자 낡은 값을 읽는다
    — 스크래퍼가 db-data를 체크아웃하는 시점(dispatch +30초)이 trade_loop의 배포
    시점(+75초)보다 빠르기 때문이다. 레이스가 아니라 정해진 순서다.

    검증을 여기서 하는 이유는 read_regime과 같다: 알 수 없는 값이 인계값이라는
    이유로 무사통과하면 파일값을 밀어내고 국면이 통째로 사라진다.
    """
    v = (os.environ.get('REGIME_HINT') or '').strip()
    return v if v in VALID_REGIMES else None


def read_regime(data_dir=None) -> tuple:
    """(regime, bull_score). 판단할 수 없으면 각각 None이다.

    regime은 VALID_REGIMES에 있을 때만 돌려준다 — 알 수 없는 값을 그대로 흘리면
    호출자의 == 비교가 전부 빗나가 '아무것도 아닌 국면'이 조용히 생긴다.
    bull_score는 숫자로 읽히지 않으면 None이다(0.0이 아니다 — 0점은 '최악의 장'
    이라는 뜻이고, 모르는 것과 다르다).

    **인계값(REGIME_HINT)이 파일보다 우선한다.** 이 적용을 호출자에 두면 갈린다 —
    실제로 orchestrator의 소유권 판정만 인계값을 쓰고 Sim10·Sim6은 파일을 읽던
    시절, 국면 전환 격자에서 "스크래퍼가 매매한다"고 정해놓고 정작 Sim10은 이전
    국면의 하위 전략·유니버스로 실주문을 냈다. 국면 파일의 유일한 창구가 여기이므로
    여기가 인계값의 유일한 관문이기도 하다.

    bull_score는 인계 대상이 아니다(dispatch inputs에 없다). 파일값을 그대로 쓴다 —
    한 격자 낡을 수 있지만 지어내지 않는다.
    """
    d = read_regime_state(data_dir) or {}
    regime = d.get('current_regime')
    if regime not in VALID_REGIMES:
        regime = None
    try:
        bull_score = float(d['bull_score'])
    except (KeyError, TypeError, ValueError):
        bull_score = None
    return (regime_hint() or regime), bull_score
