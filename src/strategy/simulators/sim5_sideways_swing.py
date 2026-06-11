from datetime import datetime

from .base_simulator import BaseSimulator, get_kst_now


class SidewaysSwingSimulator(BaseSimulator):
    """
    [Sim 5] 추세 눌림목형 (Trend-Pullback)
    ※ 클래스/상태파일명은 레거시('Sideways')를 유지하되 전략은 재정의됨.
       기존 '횡보 박스권 과매도'는 버즈/모멘텀 유니버스(ADX 중앙값 70)와 구조적으로 맞지
       않아(백테스트 진입 0건) 폐기. 대신 '상승추세 속 눌림목 저가매수 + 빠른 익절'로 전환.
    - 진입: 추세 존재(ADX>=20) + 기간 우상향 + 단기 이평(MA5) 이하로 눌림 + 당일 반등.
    - 청산: 빠른 익절(+4%) / 눌림 회복(MA5 상회) / 7일 타임스탑 / -3% 손절.
    - Sim4(추격·라이딩)와 상호보완: 이쪽은 저가매수·빠른 익절.
    """
    MAX_HOLDINGS = 4

    def __init__(self, initial_cash=3000000):
        super().__init__("Sideways", initial_cash)

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        candidate_map = {s['code']: s for s in candidates}
        portfolio_codes = list(self.state['portfolio'].keys())
        sold_today = set()

        self.update_peak_prices(current_prices)
        today = get_kst_now().date()

        # 1. 청산
        for code in portfolio_codes:
            p_item = self.state['portfolio'][code]
            stock = candidate_map.get(code)
            current_price = current_prices.get(code, 0)
            if current_price <= 0: continue
            avg_price = p_item.get('avg_price', 0)
            if avg_price <= 0: continue
            profit_rate = (current_price - avg_price) / avg_price * 100

            sparkline = stock.get('sparkline_price', []) if stock else []

            # 익절: +4%
            if profit_rate >= 4.0:
                self.sell(code, current_price, reason=f"[눌림목] 목표 익절 (+{profit_rate:.1f}%)")
                self.add_cooldown(code, 2)  # 익절 후 2일 재진입 금지 (눌림 재형성 대기)
                sold_today.add(code)
                continue
            # 눌림 회복 익절: 최근 고점 근접 시 (진입가 대비 +2% 이상이면서 sparkline 신고가 돌파)
            if sparkline:
                recent_high = max(sparkline[-5:]) if len(sparkline) >= 5 else max(sparkline)
                if current_price >= recent_high * 0.99:
                    self.sell(code, current_price, reason="[눌림목] 반등 회복 익절 (고점 근접)")
                    self.add_cooldown(code, 2)
                    sold_today.add(code)
                    continue
            # 타임 스탑: 7일(≈5영업일) 경과 시 손익 무관 청산
            entry_str = p_item.get('entry_date')
            if entry_str:
                try:
                    entry_d = datetime.strptime(entry_str, '%Y-%m-%d').date()
                    if (today - entry_d).days >= 7:
                        self.sell(code, current_price, reason="[눌림목] 타임 스탑 (7일 경과)")
                        self.add_cooldown(code, 1)
                        sold_today.add(code)
                        continue
                except ValueError:
                    pass
            # 하드 손절: -3% (백테스트상 -2%보다 우수 — 노이즈 털림 방지)
            if profit_rate <= -3.0:
                self.sell(code, current_price, reason=f"[눌림목] 하드 손절 ({profit_rate:.1f}%)")
                self.add_cooldown(code, 3)  # 손절 후 3일 재진입 금지
                sold_today.add(code)
                continue

        # 2. 진입 (추세 존재 + 기간 우상향 + MA5 이하 눌림 + 당일 반등 + 유동성/체결강도)
        if not self.state.get('market_index_healthy', True):
            return self.calculate_stats(current_prices)

        target_amount = self.initial_cash / 10
        fail_log = []
        for stock in candidates:
            if len(self.state['portfolio']) >= self.MAX_HOLDINGS: break
            code = stock['code']
            name = stock.get('name', code)
            if code in self.state['portfolio'] or code in sold_today: continue
            if self.is_in_cooldown(code): continue

            price = float(stock.get('price', 0))
            amount = float(stock.get('amount', 0))
            if price <= 0:
                fail_log.append(f"{name}:price=0")
                continue
            if amount < 1_000_000_000:
                fail_log.append(f"{name}:amount={amount/1e8:.0f}억<10억")
                continue

            sparkline = stock.get('sparkline_price', [])
            if len(sparkline) < 3:
                fail_log.append(f"{name}:sparkline={len(sparkline)}<3")
                continue
            adx = self.calculate_adx(sparkline)
            period_change = self.calc_period_change(sparkline)
            daily_change = self.parse_change_rate(stock)
            tick_power = float(stock.get('tick_power', 0.0))

            # [Fix] 고점은 과거 종가 기준(sparkline[:-1])으로 계산
            # sparkline[-1]은 당일 or 전일 종가 ≈ price이므로 제외해야
            # "현재가 = 5일 고점" 오판(pullback=0%) 방지
            hist = sparkline[:-1] if len(sparkline) > 1 else sparkline
            recent_high = max(hist[-4:]) if len(hist) >= 4 else (max(hist) if hist else price)
            pullback_pct = (recent_high - price) / recent_high * 100 if recent_high > 0 else 0

            c_adx = adx >= 20.0
            c_period = period_change > 0
            # 하한 1.0%: 얕은 눌림(추세 건재)까지 진입 — 최대 병목이자 가장 효율적 레버(백테스트 +4건/월).
            c_pullback = 1.0 <= pullback_pct <= 10.0
            # 눌림목 저가매수는 당일에도 약세인 경우가 많아 '당일 양봉' 강제는 진입을 과도하게 제약.
            # -2%까지 허용해 진입 기회 확대 (백테스트상 월 진입 ~7→~14건).
            c_daily = daily_change > -2.0
            c_tick = self.validate_tick_power(stock, threshold=100.0)

            # [Debug] 조건별 탈락 사유 기록
            if not (c_adx and c_period and c_pullback and c_daily and c_tick):
                reasons = []
                if not c_adx: reasons.append(f"ADX={adx:.0f}<20")
                if not c_period: reasons.append(f"period={period_change:.1f}%")
                if not c_pullback: reasons.append(f"pullback={pullback_pct:.1f}%(1.0~10%벗어남)")
                if not c_daily: reasons.append(f"daily={daily_change:.1f}%")
                if not c_tick: reasons.append(f"tick={tick_power:.0f}(amount={amount/1e8:.0f}억)")
                fail_log.append(f"{name}:{','.join(reasons)}")
                continue

            qty = int(target_amount / price)
            if qty > 0:
                self.buy(code, stock['name'], price, qty,
                         reason=f"[눌림목] 추세 눌림 저가매수 (ADX {adx:.1f}, 눌림 {pullback_pct:.1f}%)")

        if fail_log:
            print(f"[Sim5 진입 탈락] {len(fail_log)}개: " + " | ".join(fail_log[:10]))

        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
