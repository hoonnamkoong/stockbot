"""
[Reset] 모든 활성 시뮬레이터(strategy_manifest.yaml)의 포트폴리오/히스토리를
초기화하고 초기 자본을 300만원으로 통일한다. (동일 조건 비교용)

실행: python scripts/reset_simulators.py
"""
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.strategy.registry import get_active_simulators
from src.strategy.simulators.base_simulator import DEFAULT_INITIAL_CASH

# 리셋이 상태 파일에 적는 initial_cash는 **대시보드가 수익률의 분모로 쓰는 값**이다.
# 여기에 숫자를 다시 적으면 파이썬에서 금액을 바꿔도 리셋된 심만 옛 분모로
# 남는다 — 그 사고는 이미 한 번 났다(리셋 예수금 200만 전환).
INITIAL_CASH = DEFAULT_INITIAL_CASH


def reset_simulators():
    sims = get_active_simulators()
    print(f"\n[Reset] 활성 시뮬레이터 {len(sims)}개 초기화 (매매형 자본 {INITIAL_CASH:,}원 통일).")
    for sim in sims:
        if getattr(sim, 'IS_ANALYZER', False):
            sim.reset_state()                # 분석기(리베로)는 자본 0 유지
            print(f"  - {sim.name}: (분석기) 초기화 완료")
            continue
        sim.initial_cash = INITIAL_CASH      # 수익률 분모 통일
        sim.state['initial_cash'] = INITIAL_CASH
        sim.reset_state()                    # portfolio/history 초기화 + 로그/CSV 삭제
        print(f"  - {sim.name}: 초기화 완료 (state={os.path.basename(sim.state_file)})")
    print("\n[Success] 전체 시뮬레이터가 동일 자본으로 클린 리셋되었습니다.")


if __name__ == "__main__":
    reset_simulators()
