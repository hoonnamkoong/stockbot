from .base_simulator import BaseSimulator

class OriginalSimulator(BaseSimulator):
    """
    [Sim 1] 안정 지향형 (Original - Buzz Filter 기반)
from .base_simulator import BaseSimulator

class OriginalSimulator(BaseSimulator):
    """
    [Sim 1] 안정 지향형 (Original - Buzz Filter 기반)
    - 3M 초기화 후 개시
    - 1/N 동일 비중 (10개 슬롯)
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("Original", initial_cash) # 파일명: sim_original_state.json

    def run(self, candidates, current_prices=None):
        """
        [Standard] 통합 인터페이스
        """
        # 1. 청산 로직 (Buzz Filter 이탈 시)
        candidate_codes = [s['code'] for s in candidates]
        portfolio_codes = list(self.state['portfolio'].keys())
        
        for code in portfolio_codes:
            if code not in candidate_codes:
                p_item = self.state['portfolio'][code]
                stock = next((s for s in candidates if s['code'] == code), None)
                current_price = stock.get('price', stock.get('현재가', 0)) if stock else 0
                if current_price == 0: continue
                
                self.sell(code, current_price, reason="[안정] Buzz Filter 이탈")

        # 2. 진입 로직
        if not candidates: return
        
        target_amount = self.initial_cash / 10 # 종목당 10% 비중
        for stock in candidates[:10]:
            code = stock['code']
            if code in self.state['portfolio']: continue
            
            price = float(stock.get('price', stock.get('현재가', 0)))
            if price <= 0: continue
            
            qty = int(target_amount / price)
            if qty > 0:
                # AI 분석 요약이 있으면 사유에 포함
                ai_summary = stock.get('posts_summary', 'Buzz 필터 통과')
                self.buy(code, stock.get('name', stock.get('종목명', 'Unknown')), price, qty, reason=f"[안정] {ai_summary}")

        # [V8.9.9.48 Hotfix] 매매 결과와 관계없이 성과 지표 상시 업데이트 및 저장
        # TypeError: run() got an unexpected keyword argument 'current_prices' 에러 해결
        if current_prices is None:
            current_prices = {s['code']: s.get('price', s.get('현재가', 0)) for s in candidates}
            
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
