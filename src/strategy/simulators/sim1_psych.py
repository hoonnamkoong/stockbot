from .base_simulator import BaseSimulator

class PsychDivergenceSimulator(BaseSimulator):
    """
    [Sim 1] 심리 괴리형 (Psych-Divergence)
    - 뉴스/게시글 빈도(Buzz)와 가격 변동 간의 괴리 포착
    - 원리: 대중의 관심은 폭증했으나 가격은 아직 정체일 때 매집
    """
    def __init__(self, initial_cash=5000000):
        super().__init__("Psych", initial_cash)

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        candidate_map = {s['code']: s for s in candidates}
        portfolio_codes = list(self.state['portfolio'].keys())
        sold_today = set()

        # 고점 갱신 (트레일링 스탑용)
        self.update_peak_prices(current_prices)

        # 1. 청산 로직 (공격적 홀딩 + 트레일링 스탑)
        for code in portfolio_codes:
            p_item = self.state['portfolio'][code]
            current_price = current_prices.get(code, 0)
            avg_price = p_item.get('avg_price', 0)
            if avg_price <= 0: continue
            profit_rate = (current_price - avg_price) / avg_price * 100
            
            # [V2] 트레일링 스탑 체크 (5% 수익 후 3% 하락 시)
            if self.check_trailing_stop(code, current_price, activation_pct=5.0, callback_pct=3.0):
                self.sell(code, current_price, reason=f"[심리/공격] 트레일링 스탑 익절 (고점 대비 하락)")
                sold_today.add(code)
                continue

            # 기본 익절/손절
            if profit_rate >= 15.0:
                self.sell(code, current_price, reason=f"[심리/공격] 목표 폭발 수익 달성 (+{profit_rate:.1f}%)")
                sold_today.add(code)
            elif profit_rate <= -7.0:
                self.sell(code, current_price, reason=f"[심리/공격] 손절 (-7%)")
                sold_today.add(code)

        # 2. 진입 로직 (시장 지수 + 유동성 + 심리 괴리)
        if not self.state.get('market_index_healthy', True): return self.calculate_stats(current_prices)

        target_amount = self.initial_cash / 10
        for stock in candidates:
            code = stock['code']
            if code in self.state['portfolio'] or code in sold_today: continue
            
            # [V50.2] 유동성 필터: 거래대금 10억 미만 제외 (amount 필드 사용)
            price = float(stock.get('price', 0))
            amount = float(stock.get('amount', 0))
            if amount < 1_000_000_000: continue

            avg_buzz = stock.get('avg_posts', 1)
            if avg_buzz <= 0: avg_buzz = 1
            buzz_count = stock.get('recent_posts_count', 0)
            buzz_ratio = buzz_count / avg_buzz
            
            change_rate = stock.get('change_rate', stock.get('daily_change_rate', 0))
            if isinstance(change_rate, str):
                change_rate = float(change_rate.replace('%', '').replace('+', ''))
            
            # [공격적 진입] 관심 폭발 + 가격 정체
            if (buzz_ratio >= 2.2 or buzz_count >= 750) and change_rate < 3.0:
                if price <= 0: continue
                qty = int(target_amount / price)
                if qty > 0:
                    self.buy(code, stock['name'], price, qty, 
                             reason=f"[심리/공격] V2 진입 (Buzz {buzz_count}개, {buzz_ratio:.1f}배)")

        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
