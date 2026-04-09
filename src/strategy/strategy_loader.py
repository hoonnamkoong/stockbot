import importlib
import datetime
import os
import sys

def load_monthly_strategy():
    """
    현재 날짜(월)를 기준으로 해당하는 알고리즘 전략 객체를 동적으로 로드합니다.
    예: 4월 -> src.strategy.monthly.algo_04_v2.Algo04V2
    """
    now = datetime.datetime.now()
    month_str = now.strftime('%m') # '04', '05' 등
    
    # 전략 파일 매핑 규칙 (확장 가능)
    # 실제 파일명에 따라 업데이트가 필요할 수 있습니다.
    strategy_map = {
        "04": {"module": "src.strategy.monthly.algo_04_v2", "class": "Algo04V2"},
        "05": {"module": "src.strategy.monthly.algo_05_v1", "class": "Algo05V1"}, # 예시
    }
    
    target = strategy_map.get(month_str)
    
    if not target:
        print(f"[StrategyLoader] ⚠️ {month_str}월 전용 전략이 정의되지 않았습니다. 기본 전략(04월)을 로드합니다.")
        target = strategy_map["04"]

    try:
        module = importlib.import_module(target["module"])
        strategy_class = getattr(module, target["class"])
        print(f"[StrategyLoader] ✅ {month_str}월 전략 로드 완료: {target['class']}")
        return strategy_class()
    except Exception as e:
        print(f"[StrategyLoader] 🚨 전략 로드 실패: {e}")
        # Fallback: 4월 전략 직접 임포트 시도
        from src.strategy.monthly.algo_04_v2 import Algo04V2
        return Algo04V2()
