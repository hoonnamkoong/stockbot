from .base_simulator import BaseSimulator
from datetime import date, datetime

# base의 순수 헬퍼(Task 3에서 @staticmethod로 전환됨)를 재사용 — 중복 정의 없음.
# decide 본문은 이 로컬 이름들을 그대로 쓴다.
_adx = BaseSimulator.calculate_adx
_period_change = BaseSimulator.calc_period_change
_parse_change_rate = BaseSimulator.parse_change_rate
_validate_tick = BaseSimulator.validate_tick_power
_cooldown_active = BaseSimulator.cooldown_active


def _holding_days(p_item, today):   # sim4-1 고유(base에 없음)
    s = p_item.get('entry_date', '')
    try:
        return (today - datetime.strptime(s, '%Y-%m-%d').date()).days if s else 0
    except Exception:
        return 0


def _partial_days(p_item, today):   # sim4-1 고유(base에 없음)
    s = p_item.get('partial_sold_date', '')
    try:
        return (today - datetime.strptime(s, '%Y-%m-%d').date()).days if s else 0
    except Exception:
        return 0


MAX_HOLDINGS = 6
POSITION_WEIGHT = 0.15  # 종목당 NAV 대비 비중 (0.15 × 6 = 최대 90% 투입)


def decide_bull_daytrade(view, candidates, current_prices):
    """[Sim4-1] 단타 결정. 순수 함수 — 매매·상태 없음. Order 리스트 반환."""
    orders = []
    portfolio = view['portfolio']
    today = date.today()
    # 1. 청산
    sold = set()
    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        if cur <= 0:
            continue
        avg = p.get('avg_price', 0)
        if avg <= 0:
            continue
        pr = (cur - avg) / avg * 100
        if not p.get('partial_sold', False):
            if _holding_days(p, today) >= 2:
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': "[단타] 2일 경과 모멘텀 소멸 강제청산", 'cooldown': 1, 'mark_partial': False})
                sold.add(code); continue
            if pr <= -3.0:
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': f"[단타] 손절 ({pr:.1f}%)", 'cooldown': 2, 'mark_partial': False})
                sold.add(code); continue
            if pr >= 5.0:
                half = p['quantity'] // 2
                if half > 0:
                    orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': half,
                                   'reason': f"[단타] 1차 분할 익절 +5% ({pr:.1f}%)", 'cooldown': None, 'mark_partial': True})
        else:
            if _partial_days(p, today) >= 5:
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': "[단타] 5일 경과 2차 강제청산", 'cooldown': 1, 'mark_partial': False})
                sold.add(code); continue
            if pr <= 0.0:
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': f"[단타] 매입가 복귀 손절 ({pr:.1f}%)", 'cooldown': 2, 'mark_partial': False})
                sold.add(code); continue
            if pr >= 10.0:
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': f"[단타] 2차 전량 익절 +10% ({pr:.1f}%)", 'cooldown': 2, 'mark_partial': False})
                sold.add(code); continue
    # 2. 진입
    if not view['market_index_healthy']:
        return orders
    target_amount = view['nav'] * POSITION_WEIGHT
    held = len(portfolio) - len(sold)
    for stock in candidates:
        if held >= MAX_HOLDINGS:
            break
        code = stock['code']
        if code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            continue
        price = float(stock.get('price', 0))
        amount = float(stock.get('amount', 0))
        if price <= 0 or amount < 3_000_000_000:
            continue
        sparkline = stock.get('sparkline_price', [])
        adx = _adx(sparkline) if sparkline else 0.0
        if adx < 20.0:
            continue
        period_change = _period_change(sparkline)
        daily_change = _parse_change_rate(stock)
        has_inst = (stock.get('orgn_fake_ntby_qty', 0) > 0 or stock.get('frgn_fake_ntby_qty', 0) > 0)
        if (5.0 <= period_change <= 40.0 and daily_change > 0 and adx >= 20.0
                and _validate_tick(stock, 120.0) and has_inst):
            qty = int(target_amount / price)
            if qty > 0:
                orders.append({'action': 'BUY', 'code': code, 'name': stock['name'], 'price': price,
                               'quantity': qty, 'cooldown': None,
                               'reason': f"[단타] 탑승 (기간 {period_change:.1f}%, ADX {adx:.1f}, 기관{stock.get('orgn_fake_ntby_qty',0):+,}/외인{stock.get('frgn_fake_ntby_qty',0):+,})"})
                held += 1
    return orders


class BullMomentumDayTradingSimulator(BaseSimulator):
    """
    [Sim 4-1] 상승 모멘텀 단타형 (Bull-Momentum Day Trading)
    - 진입: Sim4와 동일 (상승률 상위 유니버스, ADX+수급+모멘텀 필터)
    - 청산: 분할 익절 (+5% 절반 / +10% 전량) + 타이트 손절/강제청산
    - 불타기 없음. 빠른 회전율 목표.
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("BullDayTrade", initial_cash)

    def get_universe(self):
        """코스피 당일 상승률 상위 30개 종목 (Sim4와 동일)."""
        try:
            from src.trade.kis_data_provider import KISDataProvider
            return KISDataProvider().get_fluctuation_rank(market='0001', sort='0', limit=30)
        except Exception:
            return None

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        orders = decide_bull_daytrade(self._view(current_prices), candidates, current_prices)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
