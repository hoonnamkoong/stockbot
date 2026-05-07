from .base_simulator import BaseSimulator

class SmartRiskSimulator(BaseSimulator):
    """
    [Sim 3] 스마트 리스크형 (Smart-Risk)
    - 추세 확인된 종목만 진입, 엄격한 손절로 방어
    """
    def __init__(self, initial_cash=5000000):
        super().__init__("Risk", initial_cash)

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        candidate_map = {s['code']: s for s in candidates}
        portfolio_codes = list(self.state['portfolio'].keys())
        sold_today = set()

        # 고점 갱신
        self.update_peak_prices(current_prices)

        # 1. 청산 로직 (트레일링 스탑 + 지표 이탈)
        for code in portfolio_codes:
            p_item = self.state['portfolio'][code]
            stock = candidate_map.get(code)
            current_price = current_prices.get(code, 0)
            if current_price <= 0: continue
            
            # [V2] 트레일링 스탑 (5% 수익 후 3% 하락 시)
            if self.check_trailing_stop(code, current_price, activation_pct=5.0, callback_pct=3.0):
                self.sell(code, current_price, reason="[리스크/V2] 트레일링 스탑 익절")
                sold_today.add(code)
                continue

            profit_rate = (current_price - p_item['avg_price']) / p_item['avg_price'] * 100
            
            # 5일 이평선 계산 (sparkline 활용)
            sparkline = stock.get('sparkline_price', []) if stock else []
            ma_val = sum(sparkline[-5:]) / len(sparkline[-5:]) if len(sparkline) >= 3 else p_item['avg_price']

            # 기본 익절/손절/이탈
            if profit_rate >= 10.0:
                self.sell(code, current_price, reason=f"[리스크/V2] 목표 수익 달성 (+{profit_rate:.1f}%)")
                sold_today.add(code)
            elif profit_rate <= -5.0:
                self.sell(code, current_price, reason=f"[리스크/V2] 손절 (-5%)")
                sold_today.add(code)
            elif current_price < ma_val * 0.98:
                self.sell(code, current_price, reason=f"[리스크/V2] 추세 이탈 감지 (MA 하회)")
                sold_today.add(code)

        # 2. 진입 로직 (시장 지수 + 유동성 + 추세)
        if not self.state.get('market_index_healthy', True): return self.calculate_stats(current_prices)

        target_amount = self.initial_cash / 10
        for stock in candidates:
            code = stock['code']
            if code in self.state['portfolio'] or code in sold_today: continue
            
            # [V50.2] 유동성 필터 (10억 이상, amount 필드 사용)
            price = float(stock.get('price', 0))
            amount = float(stock.get('amount', 0))
            if amount < 1_000_000_000: continue

            period_change = stock.get('period_change_rate', 0)
            daily_change = stock.get('change_rate', stock.get('daily_change_rate', 0))
            if isinstance(daily_change, str):
                daily_change = float(daily_change.replace('%', '').replace('+', ''))
            
            # [V50.2] 5일 누적 수익 3% 이상 또는 2일 이상 연속 포착 & 당일 양봉 시에만 진입
            if (period_change > 3.0 or stock.get('consecutive_days', 0) >= 2) and daily_change > 0:
                if price <= 0: continue
                qty = int(target_amount / price)
                if qty > 0:
                    self.buy(code, stock['name'], price, qty, 
                             reason=f"[리스크/V2] 추세 추종 (5일 누적 {period_change:.1f}%)")

        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
