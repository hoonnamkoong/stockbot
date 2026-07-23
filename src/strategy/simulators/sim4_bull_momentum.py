from .base_simulator import BaseSimulator


class BullMomentumSimulator(BaseSimulator):
    """
    [Sim 4] 상승장 주도주 탑승형 (Bull-Momentum)
    - 고유동성 + 강한 기간 모멘텀 종목에 진입해 불타기로 비중 확대.
    - 고정 익절 없음: 트레일링 스탑으로만 청산하여 상승을 끝까지 라이딩.
    """
    MAX_HOLDINGS = 6
    POSITION_WEIGHT = 0.15  # 종목당 NAV 대비 비중 (0.15 × 6 = 최대 90% 투입)

    def __init__(self, initial_cash=3000000):
        super().__init__("Bull", initial_cash)

    def get_universe(self):
        """코스피 당일 상승률 상위 30개 종목 (등락률 순위 FHPST01700000)."""
        try:
            from src.trade.kis_data_provider import KISDataProvider
            return KISDataProvider().get_fluctuation_rank(market='0001', sort='0', limit=30)
        except Exception:
            return None

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        candidate_map = {s['code']: s for s in candidates}
        portfolio_codes = list(self.state['portfolio'].keys())
        sold_today = set()

        self.update_peak_prices(current_prices)

        # 1. 청산 (트레일링 5/5 + ATR 3배 하드 손절, 고정 익절 없음)
        for code in portfolio_codes:
            p_item = self.state['portfolio'][code]
            stock = candidate_map.get(code)
            current_price = current_prices.get(code, 0)
            if current_price <= 0: continue
            avg_price = p_item.get('avg_price', 0)
            if avg_price <= 0: continue
            profit_rate = (current_price - avg_price) / avg_price * 100

            # 트레일링 스탑 (5% 활성화 후 고점 대비 5% 콜백) — 넓은 밴드로 잔파도 방어
            if self.check_trailing_stop(code, current_price, activation_pct=5.0, callback_pct=5.0):
                self.sell(code, current_price, reason="[상승모멘텀] 트레일링 스탑 익절 (라이딩 종료)")
                self.add_cooldown(code, 2)
                sold_today.add(code)
                continue

            # ATR 3배 하드 손절
            sparkline = stock.get('sparkline_price', []) if stock else []
            if sparkline and len(sparkline) >= 2:
                atr = self.calculate_atr(sparkline)
                atr_pct = (atr / avg_price) * 100 if avg_price > 0 else 3.0
            else:
                atr_pct = 3.0  # sparkline 부재 시 기본 3% (→ -9% 손절)
            if profit_rate <= -(3.0 * atr_pct):
                self.sell(code, current_price, reason=f"[상승모멘텀] ATR 3배 손절 ({profit_rate:.1f}%)")
                self.add_cooldown(code, 3)
                sold_today.add(code)
                continue

        # 2. 불타기 (Pyramiding) — 보유 종목 +5% & 미증액 시 1회만
        # is_scaled_out(base)는 부분매도 플래그와 충돌하므로 sim4 전용 'pyramided' 플래그 사용
        if self.state.get('market_index_healthy', True):
            for code in list(self.state['portfolio'].keys()):
                if code in sold_today: continue
                p_item = self.state['portfolio'][code]
                current_price = current_prices.get(code, 0)
                if current_price <= 0: continue
                avg_price = p_item.get('avg_price', 0)
                if avg_price <= 0: continue
                profit_rate = (current_price - avg_price) / avg_price * 100
                # 불타기 추가 조건: 기관 OR 외인 추정 순매수 양수여야 허수 신호 제거
                _s = candidate_map.get(code, {})
                orgn_support = _s.get('orgn_fake_ntby_qty', 0)
                frgn_support = _s.get('frgn_fake_ntby_qty', 0)
                has_inst_support = (orgn_support > 0 or frgn_support > 0)
                if profit_rate >= 5.0 and not p_item.get('pyramided', False) and has_inst_support:
                    add_qty = int(p_item['quantity'] * 0.5)
                    cost = add_qty * current_price
                    if add_qty > 0 and cost <= self.state['cash'] * 0.15:
                        if self.buy(code, p_item['name'], current_price, add_qty,
                                    reason=f"[상승모멘텀] 불타기 50% (기관{orgn_support:+,}/외인{frgn_support:+,})"):
                            self.state['portfolio'][code]['pyramided'] = True
                            self.save_state(current_prices)

        # 3. 진입 (고유동성 + 강한 기간 모멘텀 + 당일 상승 + ADX + 체결강도)
        if not self.state.get('market_index_healthy', True):
            return self.calculate_stats(current_prices)

        target_amount = self.calc_nav(current_prices) * self.POSITION_WEIGHT
        for stock in candidates:
            if len(self.state['portfolio']) >= self.MAX_HOLDINGS: break
            code = stock['code']
            if code in self.state['portfolio'] or code in sold_today: continue
            if self.is_in_cooldown(code): continue

            price = float(stock.get('price', 0))
            amount = float(stock.get('amount', 0))
            if price <= 0 or amount < 3_000_000_000: continue  # 30억 고유동성

            sparkline = stock.get('sparkline_price', [])
            adx = self.calculate_adx(sparkline) if sparkline else 0.0
            if adx < 15.0: continue  # 슬립 모드: 추세 약하면 신규 진입 없음

            period_change = self.calc_period_change(sparkline)
            daily_change = self.parse_change_rate(stock)

            orgn = stock.get('orgn_fake_ntby_qty', 0)
            frgn = stock.get('frgn_fake_ntby_qty', 0)
            has_inst = (orgn > 0 or frgn > 0)
            if (5.0 <= period_change <= 40.0 and daily_change > 0 and adx >= 20.0
                    and self.validate_tick_power(stock, threshold=120.0)
                    and has_inst):
                qty = int(target_amount / price)
                if qty > 0:
                    self.buy(code, stock['name'], price, qty,
                             reason=f"[상승모멘텀] 주도주 탑승 (기간 {period_change:.1f}%, ADX {adx:.1f}, 기관{orgn:+,}/외인{frgn:+,})")

        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
