"""Sim0(리베로)가 쓴 국면 판단을 읽는 유일한 창구.

국면 파일은 생산자가 하나(Sim0)인데 소비자가 여럿이다 — Sim6·Sim10의 매매
게이트, 월간 엑셀. 각자 파일명을 적고 각자
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

# 6단계 국면 — **정본**이다(2026-09-29, docs/superpowers/specs/2026-09-29-libero-regime6-design.md).
# 위의 3단계(current_regime)는 to_regime3()로 여기서 파생된다.
#
# ⚠ 'BEAR'·'BULL'은 3단계 값과 철자가 같지만 뜻이 좁다 — 6단계의 'BEAR'는 '하락'
# 하나이고 '매우하락'(STRONG_BEAR)을 포함하지 않는다. 약세 전체를 보려면
# to_regime3(r6) == 'BEAR'로 비교할 것.
STRONG_BEAR = 'STRONG_BEAR'
BEAR = 'BEAR'
WEAK_SIDEWAYS = 'WEAK_SIDEWAYS'
STRONG_SIDEWAYS = 'STRONG_SIDEWAYS'
BULL = 'BULL'
STRONG_BULL = 'STRONG_BULL'
VALID_REGIMES6 = (STRONG_BEAR, BEAR, WEAK_SIDEWAYS, STRONG_SIDEWAYS, BULL, STRONG_BULL)

REGIME6_LABEL_KO = {
    STRONG_BEAR: '매우하락', BEAR: '하락', WEAK_SIDEWAYS: '약한횡보',
    STRONG_SIDEWAYS: '강한횡보', BULL: '상승', STRONG_BULL: '매우상승',
}

_REGIME6_TO_3 = {
    STRONG_BEAR: 'BEAR', BEAR: 'BEAR',
    WEAK_SIDEWAYS: 'SIDEWAYS', STRONG_SIDEWAYS: 'SIDEWAYS',
    BULL: 'BULL', STRONG_BULL: 'BULL',
}


def to_regime3(regime6) -> str | None:
    """6단계 → 3단계(BULL/SIDEWAYS/BEAR). 모르는 값·None은 None이다."""
    return _REGIME6_TO_3.get(regime6)

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


def read_regime6(data_dir=None) -> str | None:
    """6단계 국면(VALID_REGIMES6 중 하나) — 10시 이후 오늘 장중 판정이 섞일 수 있다.
    판단할 수 없으면 None.

    **심의 진입 게이트는 이것을 쓰지 않는다** — 전일 확정값 read_regime6_confirmed를
    쓴다(10-01 결정). 이 함수는 대시보드 등 '지금 국면'을 보여주는 용도다. None을
    어떻게 다룰지(대개 진입 금지 = fail-closed)는 호출자가 정한다 — 여기서
    WEAK_SIDEWAYS 같은 기본값으로 채우지 않는다.

    **REGIME_HINT(인계값)는 적용하지 않는다.** 인계값은 3단계뿐이라 6단계를
    복원할 수 없다. 그래서 스크래퍼 경로에서는 이 값이 한 격자 낡을 수 있다
    (read_regime 독스트링의 순서 문제). 3단계와 6단계를 함께 쓰는 호출자는
    to_regime3(read_regime6())와 read_regime()[0]이 그 격자에서 어긋날 수 있다는
    것을 알아야 한다.
    """
    d = read_regime_state(data_dir) or {}
    r6 = d.get('regime6')
    return r6 if r6 in VALID_REGIMES6 else None


def read_regime6_confirmed(data_dir=None) -> str | None:
    """리베로가 **어제까지** 확정한 6단계 국면. 판단할 수 없으면 None.

    **심의 6단계 진입 게이트는 전부 이것을 읽는다**(심5·심10·Sim14, 10-01 사용자
    결정). 연구 하네스는 t−1일 라벨로 t일 신규 진입을 걸었다(룩어헤드 금지). 상태
    파일의 `regime6`(read_regime6)는 10시 이후 오늘 장중 판정이 섞일 수 있어
    (advance_regime6) 백테스트와 다른 게이트가 된다. 그래서 리베로가 남긴 확정
    상태(`regime6_state.base` — 마지막으로 끝난 날까지 반영)에서 라벨을 다시 만든다.

    라벨 규칙은 리베로의 regime6_label 그대로다(여기서 다시 적지 않는다). sim0_libero가
    이 모듈을 import하므로 순환을 피하려고 지연 import한다.

    base가 없거나 깨졌거나 라벨이 나오지 않으면 None — 장중 `regime6`로 대신 채우지
    않는다. None을 진입 금지로 다루는 것(fail-closed)은 호출자 몫이다.
    """
    from src.strategy.simulators.sim0_libero import regime6_label
    d = read_regime_state(data_dir) or {}
    r6state = d.get('regime6_state')
    base = r6state.get('base') if isinstance(r6state, dict) else None
    if not isinstance(base, dict):
        return None
    try:
        label = regime6_label(base.get('level'), base.get('vol10'))
    except Exception:
        return None
    return label if label in VALID_REGIMES6 else None
