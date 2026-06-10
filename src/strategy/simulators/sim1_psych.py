from .base_simulator import BaseSimulator

class PsychDivergenceSimulator(BaseSimulator):
    """
    [Sim 1] 심리 괴리형 (Psych-Divergence)
    - 뉴스/게시글 빈도(Buzz)와 가격 변동 간의 괴리 포착
    - 원리: 대중의 관심은 폭증했으나 가격은 아직 정체일 때 매집
    """
    def __init__(self, initial_cash=3000000):
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
            stock = candidate_map.get(code)
            current_price = current_prices.get(code, 0)
            if current_price <= 0: continue
            avg_price = p_item.get('avg_price', 0)
            if avg_price <= 0: continue
            profit_rate = (current_price - avg_price) / avg_price * 100
            
            # [V2] 트레일링 스탑 체크 (5% 수익 후 3% 하락 시)
            if self.check_trailing_stop(code, current_price, activation_pct=5.0, callback_pct=3.0):
                self.sell(code, current_price, reason=f"[심리/공격] 트레일링 스탑 익절 (고점 대비 하락)")
                sold_today.add(code)
                continue

            # [V60.0] ATR 기반 동적 익절/손절 (기존 고정 15% / -7% 폐기)
            sparkline = stock.get('sparkline_price', []) if stock else []
            # sparkline 부족 시 진입가의 1.5%를 fallback ATR로 사용 (1원 fallback은 즉시 손절 유발)
            atr = self.calculate_atr(sparkline) if len(sparkline) >= 3 else avg_price * 0.015

            # 동적 목표가 (TP) = 진입가 + 3 * ATR
            # 동적 손절가 (SL) = 진입가 - 1.5 * ATR  (R:R = 1:2 유지, 노이즈 완충)
            tp_price = avg_price + (atr * 3.0)
            sl_price = avg_price - (atr * 1.5)

            if current_price >= tp_price:
                self.sell(code, current_price, reason=f"[심리/공격] 동적 목표가 달성 (ATR 기반 익절)")
                sold_today.add(code)
            elif current_price <= sl_price:
                self.sell(code, current_price, reason=f"[심리/공격] 동적 손절가 이탈 (ATR 기반 손절)")
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
            
            # [V60.0] ADX 킬스위치 (ADX < 20 이면 진입 차단)
            sparkline = stock.get('sparkline_price', [])
            if len(sparkline) < 3: continue  # ATR/ADX 계산 불가 → 진입 스킵
            adx_approx = self.calculate_adx(sparkline)

            # [공격적 진입] 관심 폭발 + 가격 정체 + 체결 강도 확인 (Consensus)
            # 수급의 힘(체결강도 120% 이상)이 확인된 종목만 진입하여 허수 신호 제거
            is_valid_buzz = ((buzz_ratio >= 2.2 and buzz_count >= 30) or buzz_count >= 500)
            is_price_stable = (-5.0 <= change_rate <= 7.0) # 기존 -3.0 ~ 3.0에서 완화 (급등주도 수용)
            is_strong_demand = self.validate_tick_power(stock, threshold=120.0)
            is_trending = adx_approx >= 15.0 # 킬스위치 완화

            if is_valid_buzz and is_price_stable and is_strong_demand and is_trending:
                if price <= 0: continue
                qty = int(target_amount / price)
                if qty > 0:
                    self.buy(code, stock['name'], price, qty, 
                             reason=f"[심리/공격] Consensus 진입 (Buzz {buzz_count}개, ADX {adx_approx:.1f})")

        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
