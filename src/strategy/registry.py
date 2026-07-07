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


def get_simulator_ids() -> list[str]:
    """활성화된 시뮬레이터의 ID 목록을 반환합니다."""
    manifest = _load_manifest()
    return [s['id'] for s in manifest.get('simulators', []) if s.get('active', True)]


def get_tradeable_simulator_ids() -> list[str]:
    """프로그램 매매 가능(active && tradeable) 시뮬레이터 ID 목록. 화이트리스트 소스."""
    manifest = _load_manifest()
    return [
        s['id'] for s in manifest.get('simulators', [])
        if s.get('active', True) and s.get('tradeable', False)
    ]


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
