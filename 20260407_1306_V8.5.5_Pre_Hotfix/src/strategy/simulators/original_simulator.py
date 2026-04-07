from .base_simulator import BaseSimulator

class OriginalSimulator(BaseSimulator):
    """
    [Sim 1] 오리지널 전략 (1/N 동일 비중)
    - 1차 Buzz Filter 통과 종목 대상 동일 비중 매수
    - 매도: 전략적 신호 또는 일정 수익률/손절률 도달 시
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("Original", initial_cash)

    def execute_strategy(self, candidates):
        """
        [Standard] 1/N 분산 투자 로직
        """
        if not candidates: return
        
        # 가용 현금을 통과 종목 수로 나누어 균등 배분 (최대 10종목)
        slot_count = min(len(candidates), 10)
        target_amount = self.initial_cash / 10 # 종목당 10% 비중
        
        for stock in candidates[:slot_count]:
            code = stock['code']
            if code in self.state['portfolio']: continue
            
            # 현금 확인
            price = float(stock.get('price', 0))
            if price <= 0: continue
            
            qty = int(target_amount / price)
            if qty > 0:
                reason = f"[오리지널] 1단계 Buzz Filter 통과 ({stock.get('recent_posts_count')} posts) 동일 비중 진입"
                self.buy(code, stock['name'], price, qty, reason=reason)

    def check_liquidation(self, candidates_codes):
        """
        [Standard] 리밸런싱 및 청산 로직
        """
        codes = list(self.state['portfolio'].keys())
        for code in codes:
            # 1차 필터 탈락 시 전량 매도 (추세 이탈)
            if code not in candidates_codes:
                p_item = self.state['portfolio'][code]
                # 현재가는 candidates 또는 실시간 조회 필요 (여기서는 state 가격 활용 또는 외부 주입)
                self.sell(code, p_item['price'], reason="[오리지널] Buzz Filter 이탈로 인한 추세 매도")
