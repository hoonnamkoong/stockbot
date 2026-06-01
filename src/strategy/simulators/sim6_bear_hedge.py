from .base_simulator import BaseSimulator


class BearHedgeSimulator(BaseSimulator):
    """
    [Sim 6] 하락장 줍줍형 (Bear-Hedge)
    - 극단적 현금 보유 원칙. 우량주가 급락 후 데드캣 반등을 시작할 때만 소량 진입.
    - 빠른 익절(+2.5%) / 타이트 손절(-2%). 트레일링 없음(도망이 원칙).
    """
    MAX_INVEST_RATIO = 0.20  # 총 자본 20% 이하만 투자
    MAX_HOLDINGS = 2

    def __init__(self, initial_cash=3000000):
        super().__init__("Bear", initial_cash)

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        candidate_map = {s['code']: s for s in candidates}
        portfolio_codes = list(self.state['portfolio'].keys())
        sold_today = set()

        self.update_peak_prices(current_prices)

        # 1. 청산 (빠른 익절 +2.5% / 타이트 손절 -2%)
        for code in portfolio_codes:
            p_item = self.state['portfolio'][code]
            current_price = current_prices.get(code, 0)
            if current_price <= 0: continue
            avg_price = p_item.get('avg_price', 0)
            if avg_price <= 0: continue
            profit_rate = (current_price - avg_price) / avg_price * 100

            if profit_rate >= 2.5:
                self.sell(code, current_price, reason=f"[하락줍줍] 데드캣 빠른 익절 (+{profit_rate:.1f}%)")
                sold_today.add(code)
                continue
            if profit_rate <= -2.0:
                self.sell(code, current_price, reason=f"[하락줍줍] 타이트 손절 ({profit_rate:.1f}%)")
                sold_today.add(code)
                continue

        # 2. 진입 (선별적: 기간 -7% 이상 급락 후 +7% 이내 반등 시작 + 외인 매도 완화 + 우량주)
        if not self.state.get('market_index_healthy', True):
            return self.calculate_stats(current_prices)

        max_position = self.initial_cash * 0.10
        for stock in candidates:
            if len(self.state['portfolio']) >= self.MAX_HOLDINGS: break
            invest_ratio = self.state.get('invested', 0) / self.initial_cash if self.initial_cash > 0 else 1
            if invest_ratio >= self.MAX_INVEST_RATIO: break

            code = stock['code']
            if code in self.state['portfolio'] or code in sold_today: continue

            price = float(stock.get('price', 0))
            amount = float(stock.get('amount', 0))
            if price <= 0 or amount < 5_000_000_000: continue  # 50억 우량주만

            sparkline = stock.get('sparkline_price', [])
            period_change = self.calc_period_change(sparkline)
            daily_change = self.parse_change_rate(stock)
            foreign_change = float(stock.get('foreign_change', 0) or 0)
            adx = self.calculate_adx(sparkline) if sparkline else 0.0

            # 재무 퀄리티 필터: ROE 음수(적자) 종목, 부채비율 200% 초과 제외
            roe = float(stock.get('roe', 0) or 0)
            debt_ratio = float(stock.get('debt_ratio', 0) or 0)
            is_quality = (roe >= 0) and (debt_ratio == 0 or debt_ratio <= 200)

            if (period_change <= -7.0 and 0 < daily_change <= 7.0
                    and foreign_change >= 0 and adx >= 15.0 and is_quality):
                invest_amount = min(max_position, self.state['cash'] * 0.5)
                qty = int(invest_amount / price)
                if qty > 0:
                    self.buy(code, stock['name'], price, qty,
                             reason=f"[하락줍줍] 데드캣 반등 (기간 {period_change:.1f}%, ROE {roe:.1f}%, 부채 {debt_ratio:.0f}%)")

        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
