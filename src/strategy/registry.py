"""
[V50] 전략 & 시뮬레이터 플러그인 레지스트리 (YAML Manifest 기반)
=======================================================
strategy_manifest.yaml을 읽어 전략과 시뮬레이터를 동적으로 로드합니다.

[사용 방법]
  from src.strategy.registry import get_current_strategy, get_active_simulators

  strategy = get_current_strategy()   # 현재 달에 맞는 전략 인스턴스
  simulators = get_active_simulators() # 활성화된 시뮬레이터 목록
"""

import importlib
import os
import yaml
from typing import Any


# YAML 파일 위치 (이 파일 기준으로 같은 디렉토리)
MANIFEST_PATH = os.path.join(os.path.dirname(__file__), 'strategy_manifest.yaml')


def _load_manifest() -> dict:
    """
    strategy_manifest.yaml을 로드합니다.
    파일이 없거나 파싱 오류 시 명확한 에러를 발생시킵니다.
    """
    if not os.path.exists(MANIFEST_PATH):
        raise FileNotFoundError(
            f"[Registry] strategy_manifest.yaml을 찾을 수 없습니다: {MANIFEST_PATH}\n"
            "새 전략 추가 시 이 파일을 수정하세요."
        )
    with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def _load_class(module_path: str, class_name: str) -> type:
    """모듈 경로와 클래스명으로 클래스를 동적 로드합니다."""
    try:
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except ImportError as e:
        raise ImportError(
            f"[Registry] 모듈 로드 실패: {module_path}\n"
            f"파일이 존재하는지 확인하세요. 원인: {e}"
        )
    except AttributeError:
        raise AttributeError(
            f"[Registry] 클래스를 찾을 수 없습니다: {class_name} in {module_path}"
        )


def get_current_strategy() -> Any:
    """
    strategy_manifest.yaml의 active_strategy 키에 해당하는
    전략 클래스 인스턴스를 반환합니다.

    Returns:
        현재 활성 전략 인스턴스 (BaseStrategy 하위 클래스)
    """
    manifest = _load_manifest()
    active_key = manifest.get('active_strategy')

    if not active_key:
        raise ValueError("[Registry] strategy_manifest.yaml에 active_strategy가 설정되지 않았습니다.")

    strategies = manifest.get('strategies', {})
    if active_key not in strategies:
        available = list(strategies.keys())
        raise KeyError(
            f"[Registry] 전략 키 '{active_key}'를 찾을 수 없습니다.\n"
            f"사용 가능한 키: {available}"
        )

    cfg = strategies[active_key]
    cls = _load_class(cfg['module'], cfg['class'])
    print(f"[Registry] 전략 로드: {cfg['class']} ({cfg.get('description', '')})")
    return cls()


def get_active_simulators() -> list:
    """
    strategy_manifest.yaml의 simulators 목록 중
    active: true인 시뮬레이터 인스턴스 목록을 반환합니다.

    Returns:
        활성화된 시뮬레이터 인스턴스 목록
    """
    manifest = _load_manifest()
    simulators = []

    for sim_cfg in manifest.get('simulators', []):
        if not sim_cfg.get('active', True):
            print(f"[Registry] 시뮬레이터 비활성화 (Skip): {sim_cfg['id']}")
            continue
        try:
            cls = _load_class(sim_cfg['module'], sim_cfg['class'])
            simulators.append(cls())
            print(f"[Registry] 시뮬레이터 로드: {sim_cfg['id']} ({sim_cfg.get('description', '')})")
        except Exception as e:
            print(f"[Registry] 시뮬레이터 로드 실패: {sim_cfg['id']} ({e})")

    return simulators


def get_sim_registry(include_analyzers: bool = False) -> list[dict]:
    """활성 심의 '신원' 목록. 매니페스트가 유일한 원천이다.

    항목 키: id, label, state_file, csv_file, tradeable, analyzer, display_order
             + 매매심만: ui_key, short_desc, chart_group, color

    순서는 display_order다 — 매니페스트의 나열 순서가 아니다. 매니페스트 순서는
    실행 순서(국면 생산자를 소비자보다 먼저)라 사람이 읽는 순서와 다르다.
    리베로 다음에 Sim1, Sim4 다음에 Sim4-1처럼 번호순으로 보이게 한다.

    심 목록이 대시보드·리셋·브리프에 각각 복제돼 있다가 2026-07-29에 실제로
    어긋났다(심8·심9·심9-1이 리셋·브리프에서 누락). 소비자는 자기 목록을
    갖지 말고 이 함수를 쓸 것. 대시보드(TS)는 이 함수의 산출을 그대로 옮긴
    src/lib/sim-registry.generated.ts를 읽는다 — scripts/gen_sim_registry.py가 만든다.

    include_analyzers=False면 매매하지 않는 심(리베로)을 뺀다 — 리셋·브리프처럼
    '매매 성과'를 다루는 소비자의 기본값이다. 분석기는 UI 필드를 요구하지 않는다
    (성과 카드·순위표에 오르지 않고 국면 표시로만 쓰인다).
    """
    out = []
    for s in _load_manifest().get('simulators', []):
        if not s.get('active', True):
            continue
        is_analyzer = bool(s.get('analyzer', False))
        if is_analyzer and not include_analyzers:
            continue
        required = ['state_file', 'csv_file', 'label']
        if not is_analyzer:
            required += ['ui_key', 'short_desc', 'chart_group', 'color']
        missing = [k for k in required if not s.get(k)]
        if missing:
            raise ValueError(f"[Registry] {s['id']}: 매니페스트에 {missing} 누락")
        entry = {
            'id': s['id'],
            'label': s['label'],
            'state_file': s['state_file'],
            'csv_file': s['csv_file'],
            'tradeable': bool(s.get('tradeable', False)),
            'analyzer': is_analyzer,
            'display_order': s.get('display_order', 9999),
        }
        if not is_analyzer:
            entry.update({
                'ui_key': s['ui_key'],
                'short_desc': s['short_desc'],
                'chart_group': s['chart_group'],
                'color': s['color'],
            })
        out.append(entry)
    return sorted(out, key=lambda x: x['display_order'])


def get_tradeable_simulator_ids() -> list[str]:
    """프로그램 매매 가능(active && tradeable) 시뮬레이터 ID 목록. 화이트리스트 소스."""
    manifest = _load_manifest()
    return [
        s['id'] for s in manifest.get('simulators', [])
        if s.get('active', True) and s.get('tradeable', False)
    ]


def get_analyzer_simulator():
    """유일한 분석기 심(현재 Sim0 리베로) 인스턴스.

    tradeable 화이트리스트와 무관하게 로드한다 — 국면 판단을 스크래핑보다
    먼저 돌리는 Stage 0(trade_engine.run_regime_stage)의 유일한 진입점이다.
    분석기가 정확히 하나라는 전제는 regime_state.regime_state_filename()과 같다.
    """
    manifest = _load_manifest()
    analyzers = [s for s in manifest.get('simulators', [])
                 if s.get('active', True) and s.get('analyzer', False)]
    if len(analyzers) != 1:
        raise ValueError(
            f"[Registry] 분석기 심이 {len(analyzers)}개다(1개여야 한다): "
            f"{[s['id'] for s in analyzers]}")
    s = analyzers[0]
    cls = _load_class(s['module'], s['class'])
    return cls()


def needs_buzz(sim_id: str, regime: str | None = None) -> bool:
    """이 심이 이번 실행에 버즈(네이버 게시글) 후보가 필요한가.

    매니페스트의 needs_buzz 값이 'dynamic'이면 심 클래스의 needs_buzz(regime)
    classmethod를 호출한다 — Sim10처럼 국면에 따라 필요 여부가 바뀌는 심.
    정적 값(true/false)이면 그대로 쓴다. 매니페스트에 필드가 없으면 fail-safe로
    필요(True) 취급한다 — 신호에 뭘 쓰는지 모르는 새 심이 스크래핑을 건너뛰는
    사고를 막는다.
    """
    manifest = _load_manifest()
    for s in manifest.get('simulators', []):
        if s['id'] != sim_id:
            continue
        v = s.get('needs_buzz', True)
        if v == 'dynamic':
            cls = _load_class(s['module'], s['class'])
            fn = getattr(cls, 'needs_buzz', None)
            if fn is None:
                raise ValueError(
                    f"[Registry] {sim_id}: needs_buzz=dynamic인데 클래스에 "
                    f"needs_buzz(regime) classmethod가 없다")
            return bool(fn(regime))
        return bool(v)
    raise KeyError(f"[Registry] 심 '{sim_id}'를 매니페스트에서 찾을 수 없습니다.")


def get_simulator_by_id(sim_id: str, initial_cash: int | None = None):
    """id로 매매 가능 시뮬레이터 인스턴스를 반환. active && tradeable 이 아니면 None(화이트리스트 강제).

    initial_cash 지정 시 인스턴스 생성 후 속성만 덮어쓴다(프로그램 매매의 예산 스케일 사이징용).
    생성자 인자로 넘기지 않는 이유: 가상 상태 파일이 없을 때 reset_state()가 그 값으로
    상태 파일을 만들어 가상 심 자본을 오염시키는 것을 방지 — 사이징(self.initial_cash 참조)만 바꾼다.
    """
    manifest = _load_manifest()
    for s in manifest.get('simulators', []):
        if s['id'] == sim_id and s.get('active', True) and s.get('tradeable', False):
            cls = _load_class(s['module'], s['class'])
            sim = cls()
            if initial_cash is not None:
                sim.initial_cash = initial_cash
            return sim
    return None
