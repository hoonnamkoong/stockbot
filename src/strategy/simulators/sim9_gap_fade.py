from datetime import datetime

from .base_simulator import BaseSimulator, get_kst_now

_cooldown_active = BaseSimulator.cooldown_active

MAX_HOLDINGS = 6
POSITION_WEIGHT = 0.15  # 종목당 NAV 대비 비중 (0.15 × 6 = 최대 90% 투입, 전 심 통일)

# 갭소진 파라미터 (2026-06-01~07-27 41거래일 실측으로 확정)
GAP_MIN = 3.0            # 갭(시가/전일종가) 하한 %
INTRA_MAX = -3.0         # 장중(현재가/시가) 되밀림 상한 %
ENTRY_AFTER_MIN = 14 * 60 + 30  # 14:30 이후에만 진입 (되밀림 확정 전 진입 금지)
ENTRY_BEFORE_MIN = 15 * 60 + 20  # 15:20 동시호가 시작 = 체결 가능 한계
STOP_PCT = -3.0          # 익일 손절
# 고정 익절 없음: 동일 표본(n=136) 검증에서 +3% 익절이 평균 +2.83%→-1.35%로 알파를
# 파괴했다. 승자를 3%에서 자르는 동안 패자는 종가까지 흐른다. 손절만 남기면 +5.14%.
MIN_AMOUNT = 1_000_000_000


def _minutes(now):
    return now.hour * 60 + now.minute


def _held_days(entry_str, today):
    """진입일로부터 경과한 달력 일수. 파싱 불가면 None."""
    if not entry_str:
        return None
    try:
        return (today - datetime.strptime(entry_str, '%Y-%m-%d').date()).days
    except ValueError:
        return None


def decide_gap_fade(view, candidates, current_prices, now=None):
    """[Sim9] 갭소진 반등 결정. 순수 함수. Order 리스트 반환.

    now를 주입받는 이유: 진입/청산이 모두 시각 게이트에 걸려 있어 테스트가
    시계에 의존하면 안 된다.
    """
    now = now or get_kst_now()
    mins = _minutes(now)
    today = now.date()
    orders = []
    portfolio = view['portfolio']
    sold = set()

    # 1. 청산 — 진입 당일은 손대지 않는다. 오버나이트 보유가 전략의 본체다.
    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        if cur <= 0:
            continue
        avg = p.get('avg_price', 0)
        if avg <= 0:
            continue
        days = _held_days(p.get('entry_date'), today)
        if days == 0:
            continue
        pr = (cur - avg) / avg * 100

        # entry_date를 못 읽으면(상태 손상) 1일 타임스탑을 보장할 수 없다.
        # 역추세 1일 전략에서 눌러앉은 포지션이 가장 위험하므로 즉시 청산한다.
        if days is None:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[갭소진] 진입일 불명 → 즉시 청산 ({pr:+.1f}%)",
                           'cooldown': None, 'mark_partial': False})
            sold.add(code); continue

        if pr <= STOP_PCT:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[갭소진] 손절 ({pr:+.1f}%)",
                           'cooldown': 2, 'mark_partial': False})
            sold.add(code); continue

        # 타임스탑 1일: 익일 장 막바지 청산. +5일까지 끌면 수익이 무너진다(실측 -0.39%).
        # 2일 이상 남아 있으면(휴장·데이터 누락으로 청산 창을 놓친 경우) 시각 불문 청산.
        if days >= 2 or ENTRY_AFTER_MIN <= mins < ENTRY_BEFORE_MIN:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[갭소진] 타임스탑 청산 ({days}일, {pr:+.1f}%)",
                           'cooldown': None, 'mark_partial': False})
            sold.add(code); continue

    # 2. 진입 — 갭 상승 후 장중 되밀림. 되밀림이 확정된 장 막바지에만 산다.
    # 시장 지수 게이트를 걸지 않는다: 하루짜리 역추세이고, 실측도 지수 조건 없이 나왔다.
    # 상한 15:20: 동시호가가 시작되면 이 가격으로 체결할 수 없다. 15:33 런에서 사는
    # 백테스트는 체결 불가능한 거래를 세는 것이라 상한이 없으면 결과가 거짓이 된다.
    if not (ENTRY_AFTER_MIN <= mins < ENTRY_BEFORE_MIN):
        return orders

    target_amount = view['nav'] * POSITION_WEIGHT
    held = len(portfolio) - len(sold)
    for stock in candidates:
        if held >= MAX_HOLDINGS:
            break
        code = stock.get('code')
        if not code or code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            continue
        price = float(stock.get('price', 0))
        open_px = float(stock.get('open_price', 0))
        prev_cl = float(stock.get('prev_close', 0))
        amount = float(stock.get('amount', 0))
        if price <= 0 or open_px <= 0 or prev_cl <= 0 or amount < MIN_AMOUNT:
            continue

        gap = (open_px / prev_cl - 1) * 100
        intra = (price / open_px - 1) * 100
        if gap >= GAP_MIN and intra <= INTRA_MAX:
            qty = int(target_amount / price)
            if qty > 0:
                orders.append({'action': 'BUY', 'code': code, 'name': stock.get('name', code),
                               'price': price, 'quantity': qty, 'cooldown': None,
                               'reason': f"[갭소진] 되밀림 매수 (갭 {gap:+.1f}%, 장중 {intra:+.1f}%)"})
                held += 1
    return orders


class GapFadeSimulator(BaseSimulator):
    """
    [Sim 9] 갭소진 반등 (Gap-Fade Rebound)
    - 가설: 급등주는 갭으로 오르고 장중에 되밀린다. 되밀림이 과도할수록 다음날 되돌아온다.
      레퍼런스: Lou, Polk & Skouras (2019, JFE) "A Tug of War: Overnight vs Intraday".
    - 진입: 14:30~15:20 & 거래대금>=10억 & 갭>=+3% & 장중<=-3%.
            시각 게이트가 핵심 — 되밀림 확정 전에 사면 더 밀린다.
    - 청산: -3% 손절 / 익일 14:30~15:20 무조건 청산(타임스탑 1일). 고정 익절 없음.
            +5일까지 끌면 수익이 무너지므로 1일을 넘기지 않는다.
    - 데이터: open_price(KIS stck_oprc) + prev_close. 추가 네트워크 콜 0.
    - ⚠ 실전 미승격(tradeable: false). 2026-07-28 백테스트에서 배포 게이트 미통과.
      설계 근거였던 +2.98%는 '종가로 신호를 정의하고 종가에 산다'는 룩어헤드였고,
      체결 가능한 15:18 스냅샷으로 판단하면 알파가 기저 수준으로 내려앉는다.
      실제 시가(09:02 근사가 아닌)가 쌓인 뒤 재검증하기 위한 페이퍼 관찰용이다.
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("GapFade", initial_cash)

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        orders = decide_gap_fade(self._view(current_prices), candidates, current_prices)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
