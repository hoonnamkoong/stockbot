from .base_simulator import BaseSimulator
from datetime import date, datetime


class BullMomentumDayTradingSimulator(BaseSimulator):
    """
    [Sim 4-1] 상승 모멘텀 단타형 (Bull-Momentum Day Trading)
    - 진입: Sim4와 동일 (상승률 상위 유니버스, ADX+수급+모멘텀 필터)
    - 청산: 분할 익절 (+5% 절반 / +10% 전량) + 타이트 손절/강제청산
    - 불타기 없음. 빠른 회전율 목표.
    """
    MAX_HOLDINGS = 4

    def __init__(self, initial_cash=3000000):
        super().__init__("BullDayTrade", initial_cash)

    def get_universe(self):
        """코스피 당일 상승률 상위 30개 종목 (Sim4와 동일)."""
        try:
            from src.trade.kis_data_provider import KISDataProvider
            return KISDataProvider().get_fluctuation_rank(market='0001', sort='0', limit=30)
        except Exception:
            return None

    def _holding_days(self, p_item: dict) -> int:
        entry_str = p_item.get('entry_date', '')
        if not entry_str:
            return 0
        try:
            entry = datetime.strptime(entry_str, '%Y-%m-%d').date()
            return (date.today() - entry).days
        except Exception:
            return 0

    def _partial_days(self, p_item: dict) -> int:
        sold_str = p_item.get('partial_sold_date', '')
        if not sold_str:
            return 0
        try:
            sold = datetime.strptime(sold_str, '%Y-%m-%d').date()
            return (date.today() - sold).days
        except Exception:
            return 0

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        portfolio_codes = list(self.state['portfolio'].keys())
        sold_today = set()

        self.update_peak_prices(current_prices)

        today_str = date.today().isoformat()

        # 1. 청산
        for code in portfolio_codes:
            p_item = self.state['portfolio'].get(code)
            if not p_item:
                continue
            current_price = current_prices.get(code, 0)
            if current_price <= 0:
                continue
            avg_price = p_item.get('avg_price', 0)
            if avg_price <= 0:
                continue
            profit_rate = (current_price - avg_price) / avg_price * 100
            partial_sold = p_item.get('partial_sold', False)

            if not partial_sold:
                # --- 1차 익절 전 ---
                if self._holding_days(p_item) >= 2:
                    self.sell(code, current_price, reason="[단타] 2일 경과 모멘텀 소멸 강제청산")
                    sold_today.add(code)
                    continue
                if profit_rate <= -3.0:
                    self.sell(code, current_price, reason=f"[단타] 손절 ({profit_rate:.1f}%)")
                    self.add_cooldown(code, 2)
                    sold_today.add(code)
                    continue
                if profit_rate >= 5.0:
                    half_qty = p_item['quantity'] // 2
                    if half_qty > 0:
                        self.sell(code, current_price, quantity=half_qty,
                                  reason=f"[단타] 1차 분할 익절 +5% ({profit_rate:.1f}%)")
                        if code in self.state['portfolio']:
                            self.state['portfolio'][code]['partial_sold'] = True
                            self.state['portfolio'][code]['partial_sold_date'] = today_str
                            self.save_state(current_prices)
            else:
                # --- 1차 익절 후 ---
                if self._partial_days(p_item) >= 5:
                    self.sell(code, current_price, reason="[단타] 5일 경과 2차 강제청산")
                    sold_today.add(code)
                    continue
                if profit_rate <= 0.0:
                    self.sell(code, current_price, reason=f"[단타] 매입가 복귀 손절 ({profit_rate:.1f}%)")
                    sold_today.add(code)
                    continue
                if profit_rate >= 10.0:
                    self.sell(code, current_price, reason=f"[단타] 2차 전량 익절 +10% ({profit_rate:.1f}%)")
                    sold_today.add(code)
                    continue

        # 2. 진입 (Sim4와 동일 조건)
        if not self.state.get('market_index_healthy', True):
            return self.calculate_stats(current_prices)

        target_amount = self.initial_cash / 10
        for stock in candidates:
            if len(self.state['portfolio']) >= self.MAX_HOLDINGS:
                break
            code = stock['code']
            if code in self.state['portfolio'] or code in sold_today:
                continue
            if self.is_in_cooldown(code):
                continue

            price = float(stock.get('price', 0))
            amount = float(stock.get('amount', 0))
            if price <= 0 or amount < 3_000_000_000:
                continue

            sparkline = stock.get('sparkline_price', [])
            adx = self.calculate_adx(sparkline) if sparkline else 0.0
            if adx < 20.0:
                continue

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
                             reason=f"[단타] 탑승 (기간 {period_change:.1f}%, ADX {adx:.1f}, 기관{orgn:+,}/외인{frgn:+,})")

        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
