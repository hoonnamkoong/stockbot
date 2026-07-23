from datetime import date

from .base_simulator import BaseSimulator, get_kst_now


class ReportFollowerSimulator(BaseSimulator):
    """
    [Sim 7] 리포트 팔로워 — 딥다이브 "강력 매수" 종목 자동 매수.
    Stage 3: run()으로 포트폴리오 청산 조건 체크.
    Stage 3.6: buy_from_report()로 신규 매수 신호 처리.
    """
    MAX_HOLDINGS = 6
    WEIGHT_MIN   = 0.10
    WEIGHT_MAX   = 0.15  # 0.15 × 6 = 최대 90% 투입
    GATE         = 45.0

    def __init__(self, initial_cash=3_000_000):
        super().__init__("reportfollower", initial_cash)

    def _calc_weight(self, bull_score: float) -> float:
        """bull_score(45~100)를 10~20% 비중으로 선형 변환."""
        w = self.WEIGHT_MIN + (self.WEIGHT_MAX - self.WEIGHT_MIN) * (bull_score - self.GATE) / (100.0 - self.GATE)
        return max(self.WEIGHT_MIN, min(self.WEIGHT_MAX, w))

    def _days_held(self, pos: dict) -> int:
        try:
            entry = date.fromisoformat(pos.get('entry_date', '2000-01-01'))
            return (date.today() - entry).days
        except Exception:
            return 0

    def run(self, candidates, current_prices=None):
        """포트폴리오 청산 조건 체크만 수행. 신규 매수는 buy_from_report()에서."""
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)

        for code in list(self.state['portfolio'].keys()):
            pos = self.state['portfolio'].get(code)
            if not pos:
                continue
            cur = current_prices.get(code, 0)
            if cur <= 0:
                continue
            avg = pos.get('avg_price', 0)
            if avg <= 0:
                continue

            profit_rate = (cur - avg) / avg * 100

            # 하드 스탑: -8%
            if profit_rate <= -8.0:
                self.sell(code, cur, reason="[리포트팔로워] 하드 스탑 -8%")
                continue

            # 트레일링 스탑: 고점 대비 -5% (수익 +5% 달성 후 활성화)
            if self.check_trailing_stop(code, cur, activation_pct=5.0, callback_pct=5.0):
                self.sell(code, cur, reason="[리포트팔로워] 트레일링 스탑 -5%")
                continue

            # 타임 스탑: 7일 경과 + ±2% 이내 부동
            if self._days_held(pos) >= 7 and abs(profit_rate) <= 2.0:
                self.sell(code, cur, reason="[리포트팔로워] 타임 스탑 7일 부동")
                continue

        self.save_state(current_prices)

    def buy_from_report(self, strong_picks: list, bull_score: float = 50.0):
        """
        딥다이브 "강력 매수" 픽을 매수.
        strong_picks: rank_and_recommendation에 '강력 매수'가 포함된 final_picks 서브셋.
        bull_score: 리베로 bull_score (비중 결정용).
        """
        weight = self._calc_weight(bull_score)
        holdings_count = len(self.state['portfolio'])
        # 잔여현금 기준으로 사이징하면 매수할수록 분모가 줄어 뒤쪽 픽이 기하급수로 작아진다
        # (weight 12% 기준 5번째 픽 = 첫 픽의 60%). NAV 기준으로 고정해 픽 간 비중을 균등화.
        nav = self.calc_nav()

        for pick in strong_picks:
            if holdings_count >= self.MAX_HOLDINGS:
                print(f"[Sim7] MAX_HOLDINGS({self.MAX_HOLDINGS}) 초과 — 스킵: {pick.get('name')}")
                break

            code = pick.get('code')
            name = pick.get('name', code)
            price = pick.get('current_price', pick.get('price', 0))

            if not code or price <= 0:
                continue
            if code in self.state['portfolio']:
                print(f"[Sim7] 이미 보유 중 — 스킵: {name}({code})")
                continue

            qty = int(nav * weight / price)
            if qty <= 0:
                print(f"[Sim7] 현금 부족 — 스킵: {name}({code})")
                continue

            ok = self.buy(code, name, price, qty,
                          reason=f"[리포트팔로워] 강력매수 bull_score={bull_score:.1f} weight={weight:.0%}")
            if ok:
                holdings_count += 1
                print(f"[Sim7] 매수 완료: {name}({code}) {qty}주 @{price:,}원 (비중 {weight:.0%})")
