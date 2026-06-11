from .base_simulator import BaseSimulator


class SmartRiskSimulator(BaseSimulator):
    """
    [Sim 3] 가치 페어 전략 (Value Pair)
    - 업종 평균 대비 PER/PBR 20% 이하 저평가 + ADX 20 이상 추세 전환 종목 진입
    - Sim4(모멘텀)와 음의 상관 목표: 모멘텀 장에서 기회 적음, 조정/가치 장에서 기회 증가
    - 청산: +8% 익절 / -5% 손절 / 7일 타임스탑
    """
    MAX_HOLDINGS = 3

    def __init__(self, initial_cash=3000000):
        super().__init__("Risk", initial_cash)

    def get_universe(self):
        """코스피 재무비율 수익성 상위 30개 종목 (FHPST01750000)."""
        try:
            from src.trade.kis_data_provider import KISDataProvider
            return KISDataProvider().get_finance_ratio_rank(market='0001', limit=30)
        except Exception:
            return None

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        candidate_map = {s['code']: s for s in candidates}
        portfolio_codes = list(self.state['portfolio'].keys())
        sold_today = set()

        self.update_peak_prices(current_prices)

        # 1. 청산
        for code in portfolio_codes:
            p_item = self.state['portfolio'][code]
            current_price = current_prices.get(code, 0)
            if current_price <= 0: continue

            avg_price = p_item.get('avg_price', 0)
            if avg_price <= 0: continue
            profit_rate = (current_price - avg_price) / avg_price * 100

            # 목표 익절 +8%
            if profit_rate >= 8.0:
                self.sell(code, current_price, reason=f"[가치페어] 목표 익절 ({profit_rate:.1f}%)")
                self.add_cooldown(code, 2)
                sold_today.add(code)
                continue

            # 손절 -5%
            if profit_rate <= -5.0:
                self.sell(code, current_price, reason=f"[가치페어] 손절 ({profit_rate:.1f}%)")
                self.add_cooldown(code, 3)
                sold_today.add(code)
                continue

            # 타임스탑: 7일 (≈5 영업일)
            from datetime import date
            entry_date_str = p_item.get('entry_date', '')
            if entry_date_str:
                try:
                    entry_date = date.fromisoformat(entry_date_str)
                    if (date.today() - entry_date).days >= 7:
                        self.sell(code, current_price,
                                  reason=f"[가치페어] 타임스탑 ({(date.today() - entry_date).days}일 보유)")
                        self.add_cooldown(code, 1)
                        sold_today.add(code)
                        continue
                except Exception:
                    pass

        # 2. 진입
        if not self.state.get('market_index_healthy', True):
            return self.calculate_stats(current_prices)
        if len(self.state['portfolio']) >= self.MAX_HOLDINGS:
            return self.calculate_stats(current_prices)

        from src.data.sector_cache import SectorCache
        sector_cache = SectorCache()
        target_amount = self.initial_cash / 10

        for stock in candidates:
            if len(self.state['portfolio']) >= self.MAX_HOLDINGS: break
            code = stock['code']
            if code in self.state['portfolio'] or code in sold_today: continue
            if self.is_in_cooldown(code): continue

            price = float(stock.get('price', 0))
            amount = float(stock.get('amount', 0))
            if price <= 0 or amount < 5_000_000_000: continue  # 50억 유동성

            # PER/PBR 데이터 없으면 진입 제외 (안전 우선)
            stock_per = float(stock.get('per', 0))
            stock_pbr = float(stock.get('pbr', 0))
            if stock_per <= 0 and stock_pbr <= 0: continue

            # 업종 평균 조회
            sector_name = stock.get('sector_name', '')
            sector_avg = sector_cache.get_sector_avg(sector_name) if sector_name else None
            if not sector_avg: continue

            # 업종 평균 대비 20% 이하 저평가 여부
            avg_per = sector_avg['avg_per']
            avg_pbr = sector_avg['avg_pbr']
            per_cheap = (0 < stock_per <= avg_per * 0.8)
            pbr_cheap = (0 < stock_pbr <= avg_pbr * 0.8)
            if not (per_cheap or pbr_cheap): continue

            # ADX >= 20 (추세 전환 확인)
            sparkline = stock.get('sparkline_price', [])
            adx = self.calculate_adx(sparkline) if sparkline else 0.0
            if adx < 20.0: continue

            # 오늘 종가 > 5일 전 종가 (가격 반등 확인)
            if len(sparkline) >= 6 and sparkline[-1] <= sparkline[-6]: continue

            qty = int(target_amount / price)
            if qty > 0:
                reason = (
                    f"[가치페어] 업종 저평가 진입 "
                    f"(PER {stock_per:.1f}x / 섹터 {avg_per:.1f}x, "
                    f"PBR {stock_pbr:.2f}x / 섹터 {avg_pbr:.2f}x, "
                    f"ADX {adx:.1f}, 섹터: {sector_name})"
                )
                self.buy(code, stock['name'], price, qty, reason=reason)

        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
