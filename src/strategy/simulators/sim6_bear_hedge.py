import os

from .base_simulator import BaseSimulator

# base 순수 헬퍼 재사용
_parse_change_rate = BaseSimulator.parse_change_rate
_cooldown_active = BaseSimulator.cooldown_active

# 인버스 ETF 고정 유니버스 (검증 2026-07-21: 유동성 7,887억, 주문 호환 OK).
# 2X(252670)는 변동성 감쇠 심각(52주 -93%)이라 제외. 1x만 사용.
INVERSE_UNIVERSE = [
    {'code': '114800', 'name': 'KODEX 인버스'},
]

# 파라미터: 하락장 데이터 백테스트로 재튜닝(2026-07-21). 인버스는 변동성 커서
# 타이트 청산은 휩쏘로 수익 유실(구 -5%/-7% → 6~7월 -11.5%). 쉬운 진입 + 느슨한 청산으로
# 하락장 캡처 +9%대(단순보유 +20%의 절반). ★ standalone 알파 없음 — Sim0 게이팅 전제.
MAX_HOLDINGS = 1
ENTRY_RATIO = 0.9        # 진입 시 가용현금의 90%(하락 확신 국면 전제)
TRAIL_CALLBACK_PCT = 10.0  # 고점 대비 -10% 하락 시 청산 (느슨 — 휩쏘 방지)
STOP_PCT = -12.0         # 하드 손절 (파국 방지용, 넓게)
REENTRY_COOLDOWN = 1     # 청산 후 1일 쿨다운(추세 지속 시 재진입)


def decide_sim6(view, candidates, current_prices):
    """[Sim6] 인버스 ETF 추세추종 결정. 순수 함수. Order 리스트 반환.

    Sim4(상승모멘텀)의 미러: 인버스 ETF 자체의 상승 추세(=시장 하락 추세)를 타고,
    트레일링으로 하락을 라이딩한다. 시장 국면은 직접 판단하지 않는다(인버스 가격 추세만 봄).
    """
    orders = []
    portfolio = view['portfolio']
    sold = set()
    cand_by_code = {s.get('code'): s for s in candidates}

    # 1. 청산: 하드손절 / 트레일링(고점 대비 콜백). 고정 익절 없음(추세 라이딩).
    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        if cur <= 0:
            continue
        avg = p.get('avg_price', 0)
        if avg <= 0:
            continue
        pr = (cur - avg) / avg * 100

        if pr <= STOP_PCT:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[인버스] 하드 손절 ({pr:.1f}%)", 'cooldown': REENTRY_COOLDOWN, 'mark_partial': False})
            sold.add(code); continue

        peak = p.get('peak_price', avg)
        if cur <= peak * (1 - TRAIL_CALLBACK_PCT / 100):
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[인버스] 트레일링 청산 (고점대비 -{TRAIL_CALLBACK_PCT:.0f}%, {pr:+.1f}%)",
                           'cooldown': REENTRY_COOLDOWN, 'mark_partial': False})
            sold.add(code); continue

    # 2. 진입: 인버스 ETF가 상승 추세(현재가>MA5 + 5일 상승률>=2% + 당일 상승)일 때만.
    held = len(portfolio) - len(sold)
    for stock in candidates:
        if held >= MAX_HOLDINGS:
            break
        code = stock['code']
        if code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            continue
        price = float(stock.get('price', 0))
        if price <= 0:
            continue
        sparkline = stock.get('sparkline_price', [])
        if len(sparkline) < 3:
            continue
        ma = sum(sparkline) / len(sparkline)
        daily_change = _parse_change_rate(stock)
        # 쉬운/빠른 진입: 인버스가 MA5 상회 + 당일 상승. (모멘텀 확인 대기 시 고점 못 잡음)
        if price > ma and daily_change > 0:
            invest = view['cash'] * ENTRY_RATIO
            qty = int(invest / price)
            if qty > 0:
                orders.append({'action': 'BUY', 'code': code, 'name': stock.get('name', code), 'price': price,
                               'quantity': qty, 'cooldown': None,
                               'reason': "[인버스] 하락 추세추종 매수 (MA5 상회 + 당일 상승)"})
                held += 1
    return orders


class BearHedgeSimulator(BaseSimulator):
    """
    [Sim 6] 하락장 인버스 ETF 추세추종형 (Bear-Inverse-Trend)
    ※ 클래스/상태파일명은 레거시('Bear')를 유지하되 전략은 재정의됨.
       구 '데드캣 반등 롱'은 하락장에 롱으로 반등에 베팅 = 코인플립(2026-06~07 승률 47.6%,
       수수료로 -0.42%/건). 현물 롱 시스템의 하락 수익 정공법 = 인버스 ETF 추세추종으로 전환.
    - 유니버스: KODEX 인버스(114800) 고정 (검증: 유동성·주문 호환 OK, 2X는 감쇠로 제외).
    - 진입: 인버스가 상승 추세(현재가>MA5 + 5일 상승률>=2% + 당일 상승) → 하락에 순방향 베팅.
    - 청산: 트레일링(고점 대비 -7%) / 하드손절 -5%. 청산 후 쿨다운 1일(추세 지속 시 재진입).
    - 국면 판단 없음(순수 알고리즘). Sim10이 BEAR 국면에 이 심을 켠다.
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("Bear", initial_cash)

    def get_universe(self):
        """인버스 ETF 고정 유니버스 (스크리너로는 못 잡음 — 하락장엔 ETF가 오름)."""
        return [dict(e) for e in INVERSE_UNIVERSE]

    def _read_regime(self):
        """Sim0(리베로)의 현재 국면 판단을 읽는다. 자체 판단이 아니라 Sim0 출력을 소비.

        인버스 ETF는 standalone 알파가 없다(국면 전환이 타이밍 신호를 휩쏨). 상승장에서
        인버스 매수 = 손실이므로, Sim0가 BEAR로 판단할 때만 매매한다. 실패 시 SIDEWAYS(보수).
        """
        import json
        try:
            with open(os.path.join(self.data_dir, "sim_libero_state.json"), "r", encoding="utf-8-sig") as f:
                regime = json.load(f).get("current_regime", "SIDEWAYS")
            return regime if regime in ("BULL", "SIDEWAYS", "BEAR") else "SIDEWAYS"
        except Exception:
            return "SIDEWAYS"

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        if self._read_regime() == "BEAR":
            orders = decide_sim6(self._view(), candidates, current_prices)
        else:
            # 비(非)하락장: 인버스 매수 금지 + 보유분 전량 청산(국면 이탈)
            orders = [{'action': 'SELL', 'code': code, 'price': current_prices.get(code, 0),
                       'quantity': None, 'reason': "[인버스] 국면 이탈 청산(비 BEAR)",
                       'cooldown': 1, 'mark_partial': False}
                      for code in list(self.state["portfolio"].keys())
                      if current_prices.get(code, 0) > 0]
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
