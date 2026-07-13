from datetime import datetime

from .base_simulator import BaseSimulator, get_kst_now

# base 순수 헬퍼(Task 3 @staticmethod) 재사용
_adx = BaseSimulator.calculate_adx
_period_change = BaseSimulator.calc_period_change
_parse_change_rate = BaseSimulator.parse_change_rate
_validate_tick = BaseSimulator.validate_tick_power
_cooldown_active = BaseSimulator.cooldown_active

MAX_HOLDINGS = 4


def decide_sideways(view, candidates, current_prices):
    """[Sim5] 추세 눌림목 결정. 순수 함수. Order 리스트 반환."""
    orders = []
    portfolio = view['portfolio']
    today = get_kst_now().date()
    sold = set()
    # 1. 청산
    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        if cur <= 0:
            continue
        avg = p.get('avg_price', 0)
        if avg <= 0:
            continue
        pr = (cur - avg) / avg * 100
        stock = next((s for s in candidates if s.get('code') == code), None)
        sparkline = stock.get('sparkline_price', []) if stock else []
        if pr >= 4.0:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[눌림목] 목표 익절 (+{pr:.1f}%)", 'cooldown': 2, 'mark_partial': False})
            sold.add(code); continue
        if sparkline:
            recent_high = max(sparkline[-5:]) if len(sparkline) >= 5 else max(sparkline)
            if cur >= recent_high * 0.99:
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': "[눌림목] 반등 회복 익절 (고점 근접)", 'cooldown': 2, 'mark_partial': False})
                sold.add(code); continue
        entry_str = p.get('entry_date')
        if entry_str:
            try:
                if (today - datetime.strptime(entry_str, '%Y-%m-%d').date()).days >= 7:
                    orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                                   'reason': "[눌림목] 타임 스탑 (7일 경과)", 'cooldown': 1, 'mark_partial': False})
                    sold.add(code); continue
            except ValueError:
                pass
        if pr <= -3.0:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[눌림목] 하드 손절 ({pr:.1f}%)", 'cooldown': 3, 'mark_partial': False})
            sold.add(code); continue
    # 2. 진입
    if not view['market_index_healthy']:
        return orders
    target_amount = view['initial_cash'] / 10
    held = len(portfolio) - len(sold)
    for stock in candidates:
        if held >= MAX_HOLDINGS:
            break
        code = stock['code']
        if code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            continue
        price = float(stock.get('price', 0))
        amount = float(stock.get('amount', 0))
        if price <= 0 or amount < 1_000_000_000:
            continue
        sparkline = stock.get('sparkline_price', [])
        if len(sparkline) < 3:
            continue
        adx = _adx(sparkline)
        period_change = _period_change(sparkline)
        daily_change = _parse_change_rate(stock)
        hist = sparkline[:-1] if len(sparkline) > 1 else sparkline
        recent_high = max(hist[-4:]) if len(hist) >= 4 else (max(hist) if hist else price)
        pullback_pct = (recent_high - price) / recent_high * 100 if recent_high > 0 else 0
        if (adx >= 20.0 and period_change > 0 and 1.0 <= pullback_pct <= 10.0
                and daily_change > -2.0 and _validate_tick(stock, 100.0)):
            qty = int(target_amount / price)
            if qty > 0:
                orders.append({'action': 'BUY', 'code': code, 'name': stock['name'], 'price': price,
                               'quantity': qty, 'cooldown': None,
                               'reason': f"[눌림목] 추세 눌림 저가매수 (ADX {adx:.1f}, 눌림 {pullback_pct:.1f}%)"})
                held += 1
    return orders


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
    def __init__(self, initial_cash=3000000):
        super().__init__("Sideways", initial_cash)

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        orders = decide_sideways(self._view(), candidates, current_prices)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
