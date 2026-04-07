from .base_simulator import BaseSimulator

class PlaceholderSimulator(BaseSimulator):
    """
    [Sim 3] 향후 추가될 새로운 전략의 Placeholder
    - 현재는 Sim 1, 2와 동일한 인터페이스를 유지하며 빈 로직으로 구성됩니다.
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("Placeholder", initial_cash)

    def execute_strategy(self, candidates):
        # 미래의 전략을 위해 비워둠
        pass

    def check_liquidation(self, current_stocks):
        # 미래의 전략을 위해 비워둠
        pass

    def calculate_stats(self):
        """
        [DNA Logic] 우선은 차트의 시각화를 위해 임의의 샘플 데이터를 반환합니다.
        """
        return {
            "win_rate": 55, # 55%
            "profit_factor": 1.8,
            "mdd": 8.0, # 8%
            "frequency": 1.5,
            "turnover": 4.0
        }
