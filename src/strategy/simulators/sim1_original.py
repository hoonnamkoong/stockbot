from .base_simulator import BaseSimulator

class OriginalSimulator(BaseSimulator):
    """
    [Sim 1] 안정 지향형 (Original - Buzz Filter 기반)
    - 3M 초기화 후 개시
    - 1/N 동일 비중 (10개 슬롯)
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("Original", initial_cash) # 파일명: sim_original_state.json

    def run(self, candidates):
        """
        [Standard] 통합 인터페이스
        """
        # 1. 청산 로직 (Buzz Filter 이탈 시)
        candidate_codes = [s['code'] for s in candidates]
        portfolio_codes = list(self.state['portfolio'].keys())
        
        for code in portfolio_codes:
            if code not in candidate_codes:
                p_item = self.state['portfolio'][code]
                # 현재가가 candidates에 있으면 사용, 없으면 보수적으로 평단가 사용
                current_price = next((s['price'] for s in candidates if s['code'] == code), 0)
                if current_price == 0: continue
                
                self.sell(code, current_price, reason="[안정] Buzz Filter 이탈")

        # 2. 진입 로직
        if not candidates: return
        
        target_amount = self.initial_cash / 10 # 종목당 10% 비중
        for stock in candidates[:10]:
            code = stock['code']
            if code in self.state['portfolio']: continue
            
            price = float(stock.get('price', 0))
            if price <= 0: continue
            
            qty = int(target_amount / price)
            if qty > 0:
                self.buy(code, stock.get('name', stock.get('종목명', 'Unknown')), price, qty, reason="[안정] Buzz 필터 통과")

        return self.calculate_stats()
