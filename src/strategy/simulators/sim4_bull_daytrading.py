from .base_simulator import BaseSimulator, get_kst_date
from datetime import datetime

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


MAX_HOLDINGS = 5
POSITION_WEIGHT = 0.19  # 종목당 NAV 대비 비중 (0.19 × 5 = 최대 95% 투입)
# ADX 상한(2026-08-05, 심4+4-1 합산 26건 실거래 재집계로 확정):
# [0,40)→승률88.9%/+11.22%, [40,60)→100%/+13.46%, [60,80)→50%/-2.63%, [80,100]→28.6%/-6.25%.
# 60을 기점으로 승률·평균ROI가 뒤집힌다 — 추세가 이미 다 나온(과열) 종목을 진입시켜
# 반전에 물리는 패턴으로 해석. 구간당 4~9건이라 정밀한 임계값까진 못 정해 구간 경계인
# 60을 그대로 쓴다.
ADX_MAX = 60.0


def _fn(funnel, code, reason, **vals):
    """왜 안 샀는지 한 줄 남긴다(심3·심5·심9와 같은 방식).

    2026-08-14: 체결강도 게이트를 고쳐 유니버스 30종목 중 25~27개가 통과하는데도
    실전 계좌는 하루 종일 `sim4_bull_daytrading: 주문 없음`이었다. 어제 고친 건
    필요조건이었지 충분조건이 아니었고, 뒤 게이트 중 무엇이 막는지는 로그에
    아무것도 남지 않았다.

    이 심은 **실전 계좌가 실제로 돌리는 심**이라 여기서 못 사면 그날 매매가
    통째로 없다. 추측으로 임계값을 만지지 말고 먼저 센다.
    """
    if funnel is None:
        return
    funnel.append({'code': code, 'reason': reason, **vals})


def decide_bull_daytrade(view, candidates, current_prices, funnel=None):
    """[Sim4-1] 단타 결정. 순수 함수 — 매매·상태 없음. Order 리스트 반환."""
    orders = []
    portfolio = view['portfolio']
    today = get_kst_date()
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
    target_amount = view['nav'] * POSITION_WEIGHT
    held = len(portfolio) - len(sold)
    # 런당 한 번만 판정한다(종목마다 재계산하면 같은 답을 후보 수만큼 다시 낸다).
    tick_outage = BaseSimulator.tick_power_outage(candidates)
    for stock in candidates:
        if held >= MAX_HOLDINGS:
            break
        code = stock['code']
        if code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            _fn(funnel, code, 'held_or_cooldown'); continue
        price = float(stock.get('price', 0))
        amount = float(stock.get('amount', 0))
        if price <= 0:
            _fn(funnel, code, 'no_price'); continue
        if amount < 3_000_000_000:
            _fn(funnel, code, 'amount', amount=amount); continue
        sparkline = stock.get('sparkline_price', [])
        if not sparkline:
            _fn(funnel, code, 'no_sparkline'); continue
        adx = _adx(sparkline)
        if adx < 20.0:
            _fn(funnel, code, 'adx_low', adx=adx); continue
        if adx >= ADX_MAX:
            _fn(funnel, code, 'adx_high', adx=adx); continue
        period_change = _period_change(sparkline)
        daily_change = _parse_change_rate(stock)
        has_inst = (stock.get('orgn_fake_ntby_qty', 0) > 0 or stock.get('frgn_fake_ntby_qty', 0) > 0)
        # 예전엔 아래 다섯을 한 `if`로 묶어 두어, 통과 못 하면 **무엇 때문인지
        # 알 수 없었다.** 2026-08-14: 체결강도 게이트를 고쳐 25~27/30이 통과하는데도
        # 하루 종일 `주문 없음`이었는데, 어느 조건에서 죽는지 로그에 아무것도
        # 남지 않았다. 조건을 쪼개서 센다.
        if not (5.0 <= period_change <= 40.0):
            _fn(funnel, code, 'period', period=period_change, adx=adx); continue
        if daily_change <= 0:
            _fn(funnel, code, 'daily_down', daily=daily_change, adx=adx); continue
        if not _validate_tick(stock, 120.0, outage=tick_outage):
            _fn(funnel, code, 'tick', tick=stock.get('tick_power', 0), adx=adx); continue
        if not has_inst:
            _fn(funnel, code, 'no_inst', adx=adx, period=period_change); continue
        qty = int(target_amount / price)
        if qty <= 0:
            _fn(funnel, code, 'qty_zero', price=price, target=target_amount)
        else:
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
        funnel = []
        orders = decide_bull_daytrade(self._view(current_prices), candidates,
                                      current_prices, funnel=funnel)
        self._log_funnel(candidates, funnel, orders)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)

    @staticmethod
    def _log_funnel(candidates, funnel, orders) -> None:
        """게이트별 탈락 분포. 이 심은 실전 계좌가 실제로 돌리는 심이라,
        여기서 못 사면 그날 매매가 통째로 없다.

        2026-08-14: 체결강도 게이트를 고쳐 30종목 중 25~27개가 통과하는데도
        하루 종일 `주문 없음`이었다. 뒤 게이트 다섯이 한 `if`로 묶여 있어
        무엇이 막는지 알 수 없었다.

        진단이 심을 죽이면 안 되니 통째로 삼킨다.
        """
        try:
            from collections import Counter
            if not funnel and not orders:
                return
            c = Counter(f['reason'] for f in funnel)
            parts = ', '.join(f'{k} {v}' for k, v in c.most_common())
            print(f"[Sim4-1 깔때기] 후보 {len(candidates)} → 매수 {len(orders)} | 탈락: {parts}")
            # ADX까지 통과한(=셋업이 살아 있는) 종목이 어디서 죽는지 본다.
            deep = [f for f in funnel
                    if f['reason'] in ('period', 'daily_down', 'tick', 'no_inst', 'qty_zero')]
            for f in deep[:5]:
                print(f"   {f['code']} 탈락={f['reason']} "
                      f"ADX={f.get('adx', 0):.1f} 기간={f.get('period', 0):.1f}% "
                      f"당일={f.get('daily', 0):.1f}% 체결강도={f.get('tick', 0)}")
        except Exception as e:
            print(f'[Sim4-1 깔때기] 기록 실패(무시): {e}')
