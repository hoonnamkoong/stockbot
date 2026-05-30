from .base_simulator import BaseSimulator

class SmartRiskSimulator(BaseSimulator):
    """
    [Sim 3] 스마트 리스크형 (Smart-Risk)
    - 추세 확인된 종목만 진입, 엄격한 손절로 방어
    """
    def __init__(self, initial_cash=3000000):
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
            
            # [V60.0 Consensus] ATR 기반 가변 이탈가 적용
            sparkline = stock.get('sparkline_price', []) if stock else []
            atr = self.calculate_atr(sparkline)
            has_ma = len(sparkline) >= 3
            ma_val = sum(sparkline[-5:]) / len(sparkline[-5:]) if has_ma else p_item['avg_price']

            # 기본 익절/손절/이탈
            # ATR이 클수록(변동성이 클수록) 이탈 허용 범위를 넓힘
            exit_threshold = ma_val - (atr * 0.5) if atr > 0 else ma_val * 0.98

            if profit_rate >= 10.0:
                self.sell(code, current_price, reason=f"[리스크/공합] 목표 수익 달성 (+{profit_rate:.1f}%)")
                sold_today.add(code)
            elif profit_rate <= -5.0:
                self.sell(code, current_price, reason=f"[리스크/공합] 손절 (-5%)")
                sold_today.add(code)
            elif current_price < exit_threshold:
                self.sell(code, current_price, reason=f"[리스크/공합] Consensus 추세 이탈 (ATR 하회)")
                sold_today.add(code)

        # 2. 진입 로직 (시장 지수 + 유동성 + 추세/횡보 레짐 스위칭)
        if not self.state.get('market_index_healthy', True): return self.calculate_stats(current_prices)

        # [V60.0] 일일 매매 횟수 상한(5회) 체크
        from datetime import datetime
        today_str = datetime.now().strftime('%Y-%m-%d')
        if self.state.get('last_buy_date') != today_str:
            self.state['last_buy_date'] = today_str
            self.state['daily_buys_count'] = 0

        target_amount = self.initial_cash / 10
        for stock in candidates:
            if self.state.get('daily_buys_count', 0) >= 5:
                break # 최대 5종목 진입 완료
                
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
            
            # [V60.0 Consensus] ADX 기반 레짐 스위칭
            sparkline = stock.get('sparkline_price', [])
            adx_approx = self.calculate_adx(sparkline) if sparkline else 0.0
            
            is_strong = self.validate_tick_power(stock, 110.0)
            
            buy_reason = ""
            
            if adx_approx >= 15.0:
                # 추세장 (Trend): 기존 돌파 매매
                is_trending = (period_change > 3.0 or stock.get('consecutive_days', 0) >= 2)
                if is_trending and is_strong and daily_change > 0:
                    buy_reason = f"[리스크/추세] 돌파 진입 (ADX {adx_approx:.1f}, 체결강도 {stock.get('tick_power')}%)"
            else:
                # 횡보장 (Range): RSI 과매도 회귀 매매 (낙폭과대 반등)
                if len(sparkline) >= 3:
                    ma_val = sum(sparkline[-3:]) / 3
                    # 3일 평균가보다 낮게 떨어져있으면서 오늘 체결강도가 강하게(반등) 들어오는 놈
                    if price < ma_val * 0.98 and is_strong and daily_change > 0:
                        buy_reason = f"[리스크/횡보] 낙폭 반등 진입 (ADX {adx_approx:.1f}, MA이격)"

            if buy_reason:
                if price <= 0: continue
                qty = int(target_amount / price)
                if qty > 0:
                    if self.buy(code, stock['name'], price, qty, reason=buy_reason):
                        self.state['daily_buys_count'] += 1

        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
