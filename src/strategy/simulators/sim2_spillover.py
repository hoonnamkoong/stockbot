from .base_simulator import BaseSimulator
from datetime import datetime

class SectorSpilloverSimulator(BaseSimulator):
    """
    [Sim 2] MFHS2 (다중 필터 하이브리드 수급 동승 전략)
    - 과거 섹터 전이형에서 변경됨.
    - 기관/외국인 수급과 감정 발산(Divergence) 지표를 융합하여 선도 진입.
    """
    def __init__(self, initial_cash=5000000):
        super().__init__("Spillover", initial_cash)

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        candidate_map = {s['code']: s for s in candidates}
        portfolio_codes = list(self.state['portfolio'].keys())
        sold_today = set()

        # 고점 갱신
        self.update_peak_prices(current_prices)
        
        now = datetime.now()
        current_month = now.month
        current_day = now.day

        # 1. 청산 로직 (외인 수급 역전 및 5월 말 캘린더 청산)
        for code in portfolio_codes:
            current_price = current_prices.get(code, 0)
            if current_price <= 0: continue
            
            p_item = self.state['portfolio'][code]
            stock = candidate_map.get(code, {})
            
            # (A) 5월 말 달력 기반 강제 청산 (Sell in May)
            if current_month == 5 and current_day >= 25:
                self.sell(code, current_price, reason="[MFHS2] 5월말 계절성 캘린더 청산 (Sell in May)")
                sold_today.add(code)
                continue
                
            # (B) 외인 수급 역전(-EMA 근사치) 파악
            f_change = stock.get('foreign_change', 0)
            if isinstance(f_change, str):
                try:
                    f_change = float(f_change.replace('%', '').replace('+', '').strip())
                except:
                    f_change = 0.0
            
            if f_change <= -0.5: # 외인 지분 0.5% 이상 대량 이탈 시
                self.sell(code, current_price, reason="[MFHS2] 외인 대량 이탈 감지 (수급 역전)")
                sold_today.add(code)
                continue

            # (C) 트레일링 스탑
            if self.check_trailing_stop(code, current_price, activation_pct=5.0, callback_pct=3.0):
                self.sell(code, current_price, reason="[MFHS2] 트레일링 스탑 익절")
                sold_today.add(code)
                continue

            # (D) 하드 손절
            avg_price = p_item.get('avg_price', 0)
            if avg_price > 0:
                profit_rate = (current_price - avg_price) / avg_price * 100
                if profit_rate <= -7.0:
                    self.sell(code, current_price, reason="[MFHS2] 하드 손절 (-7%)")
                    sold_today.add(code)

        # 2. 진입 로직 (MFHS2 통합 스코어링 기반 진입)
        if not self.state.get('market_index_healthy', True): return self.calculate_stats(current_prices)
        
        target_amount = self.initial_cash / 10

        for stock in candidates:
            code = stock['code']
            if code in self.state['portfolio'] or code in sold_today: continue
            
            price = float(stock.get('price', 0))
            amount = float(stock.get('amount', 0))
            if amount < 1_000_000_000 or price <= 0: continue # 거래대금 10억 미만 패스

            # MFHS2 통합 스코어 계산 (BaseSimulator 메서드 호출)
            score = self.calculate_mfhs2_score(stock, current_month)

            # 진입 결정: 40점 이상이면 매수
            if score >= 40:
                qty = int(target_amount / price)
                if qty > 0:
                    self.buy(code, stock['name'], price, qty, 
                             reason=f"[MFHS2] 다중 필터 수급 동승 (Score: {score}/100)")

        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
