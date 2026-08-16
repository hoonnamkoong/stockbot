from .base_simulator import BaseSimulator, get_kst_now
from datetime import datetime

# 사이징은 전 매매심 공통 규격이다(NAV×15% × 최대 6종목 = 90% 투입).
# 2026-08-03 이전의 심2는 상한 없이 NAV/10씩 담아 10종목까지 갔고, 현금이 36,234원
# (NAV의 1.2%)까지 마르자 신호가 와도 매수가 조용히 실패했다.
MAX_HOLDINGS = 5
POSITION_WEIGHT = 0.19

class SectorSpilloverSimulator(BaseSimulator):
    """
    [Sim 2] MFHS2 (다중 필터 하이브리드 수급 동승 전략)
    - 과거 섹터 전이형에서 변경됨.
    - 기관/외국인 수급과 감정 발산(Divergence) 지표를 융합하여 선도 진입.
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("Spillover", initial_cash)

    def get_universe(self):
        """코스피 **외국인** 순매수 상위 30개 종목 (FHPTJ04400000, etc_cls='1').

        2026-08-17까지 `etc_cls='0'`(외국인+기관 합산)을 썼다. 확정 일별 순매수
        30거래일(7/3~8/14, 11,403 종목-일)로 재니 **기관이 역신호**였다 —
        익일 시가→종가(수수료 후):

            외국인 단독 상위   +0.20% (승률 53%)
            기관 단독 상위     −0.82% (승률 40%)
            합산 상위(구 방식)  −0.01% (승률 48%)   ← 기관이 외국인 신호를 상쇄

            외인 매수 & 기관 매도  +0.08%
            외인 매도 & 기관 매수  −0.84%   ← 최악

        합산 순위는 두 신호를 평균 내 서로를 죽인다. 외국인만 본다.
        ⚠ 표본이 30거래일뿐이고 8월(반등장)이 끌어올린 값이다 — 이력이 쌓이면 재측정할 것.
        """
        try:
            from src.trade.kis_data_provider import KISDataProvider
            return KISDataProvider().get_foreign_institution_rank(market='0001', etc_cls='1', limit=30)
        except Exception:
            return None

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        candidate_map = {s['code']: s for s in candidates}
        portfolio_codes = list(self.state['portfolio'].keys())
        sold_today = set()

        # 고점 갱신
        self.update_peak_prices(current_prices)
        
        now = get_kst_now()   # 5월 말 캘린더 청산이 날짜에 걸려 있다 — 로컬 시간대면 경계가 하루 밀린다
        current_month = now.month
        current_day = now.day

        # 1. 청산 로직 (외인 수급 역전 및 5월 말 캘린더 청산)
        for code in portfolio_codes:
            current_price = current_prices.get(code, 0)
            if current_price <= 0: continue
            
            p_item = self.state['portfolio'][code]
            stock = candidate_map.get(code, {})
            
            # (A) 5월 말 달력 기반 강제 청산 (Sell in May)
            if current_month == 5 and current_day >= 25:
                self.sell(code, current_price, reason="[MFHS2] 5월말 계절성 캘린더 청산 (Sell in May)")
                self.add_cooldown(code, 3)
                sold_today.add(code)
                continue

            # (B) 외인 수급 역전(-EMA 근사치) 파악
            f_change = stock.get('foreign_change', 0)
            if isinstance(f_change, str):
                try:
                    f_change = float(f_change.replace('%', '').replace('+', '').strip())
                except:
                    f_change = 0.0

            if f_change <= -0.5: # 외인 지분 0.5% 이상 대량 이탈 시
                self.sell(code, current_price, reason="[MFHS2] 외인 대량 이탈 감지 (수급 역전)")
                self.add_cooldown(code, 3)
                sold_today.add(code)
                continue

            # (C) 트레일링 스탑
            if self.check_trailing_stop(code, current_price, activation_pct=5.0, callback_pct=3.0):
                self.sell(code, current_price, reason="[MFHS2] 트레일링 스탑 익절")
                self.add_cooldown(code, 2)
                sold_today.add(code)
                continue

            # (D) 하드 손절
            avg_price = p_item.get('avg_price', 0)
            if avg_price > 0:
                profit_rate = (current_price - avg_price) / avg_price * 100
                if profit_rate <= -7.0:
                    self.sell(code, current_price, reason="[MFHS2] 하드 손절 (-7%)")
                    self.add_cooldown(code, 3)
                    sold_today.add(code)

        # 2. 진입 로직 (MFHS2 통합 스코어링 기반 진입)
        target_amount = self.calc_nav(current_prices) * POSITION_WEIGHT
        held = len(self.state['portfolio']) - len(sold_today)

        for stock in candidates:
            if held >= MAX_HOLDINGS: break
            code = stock['code']
            if code in self.state['portfolio'] or code in sold_today: continue

            if self.is_in_cooldown(code): continue

            price = float(stock.get('price', 0))
            amount = float(stock.get('amount', 0))
            if amount < 1_000_000_000 or price <= 0: continue # 거래대금 10억 미만 패스

            # MFHS2 통합 스코어 계산 (KIS 데이터 우선, 폴백은 base 메서드)
            score = self._mfhs2_score_kis(stock, current_month)

            # 진입 결정: 60점 이상이면 매수 (이전 40점 → 수급 신호 강도 상향)
            if score >= 60:
                qty = int(target_amount / price)
                if qty > 0 and self.buy(code, stock['name'], price, qty,
                                        reason=f"[MFHS2] 다중 필터 수급 동승 (Score: {score}/100)"):
                    held += 1

        self.save_state(current_prices)
        return self.calculate_stats(current_prices)

    def _mfhs2_score_kis(self, stock_data: dict, current_month: int) -> int:
        """
        KIS 데이터 우선 MFHS2 스코어 산출.
        KIS 외인/기관 추정 순매수가 있으면 그것을 사용, 없으면 base 메서드 폴백.
        A(수급 40점) + B(발산 40점) + C(계절성 20점)
        """
        score = 0

        # [조건 A] 수급 (40점) — KIS 추정 데이터 우선
        frgn_kis = stock_data.get('frgn_fake_ntby_qty', 0)
        orgn_kis = stock_data.get('orgn_fake_ntby_qty', 0)
        if frgn_kis != 0 or orgn_kis != 0:
            # KIS 데이터 있음: **외인 순매수만** 본다(40점).
            # 2026-08-17까지 외인 20점 + 기관 20점이었다. 확정 수급 30거래일 실측에서
            # 기관 순매수 상위가 −0.82%(승률 40%)로 **역신호**였다 — 기관이 사는 것에
            # 점수를 주면 지는 쪽에 가중치를 얹는 셈이다. 배점(40)은 아래 폴백 경로
            # (foreign_change>0 → 40점)와 이미 같은 구조라 그쪽에 맞춘다.
            if frgn_kis > 0:
                score += 40
        else:
            # KIS 데이터 없음: 네이버 foreign_change 폴백
            f_change = stock_data.get('foreign_change', 0)
            if isinstance(f_change, str):
                try:
                    f_change = float(f_change.replace('%', '').replace('+', '').strip())
                except ValueError:
                    f_change = 0.0
            if f_change > 0:
                score += 40

        # [조건 B] 수급-가격 발산 (40점) — 스마트머니가 사고 있는데 가격이 아직 덜 올랐다
        frgn = stock_data.get('frgn_fake_ntby_qty', 0)
        orgn = stock_data.get('orgn_fake_ntby_qty', 0)
        daily_chg = self.parse_change_rate(stock_data)
        if frgn > 0 and orgn > 0 and daily_chg < 3.0:
            score += 40

        # [조건 C] 계절성 (20점)
        if 1 <= current_month <= 4:
            score += 20

        return score
