from . import kr_calendar
from .base_simulator import BaseSimulator, DEFAULT_INITIAL_CASH, get_kst_now, log_funnel

# [Sim6] GTAA-KR5 상시 방어형 자산배분 (2026-10-01 재목적화, 관찰 심).
# 근거: docs/superpowers/specs/2026-10-01-bear-strategy-external-research.md §6.3(다-1).
# 1997~ 연 9.5%·샤프 0.64·MDD −17%(코스피 0.35·−64%), 2026 여름 −40% 급락 때 −11.8%.
# 기대치는 "하락장에서 번다"가 아니라 "덜 잃는다"다 — 상승장에선 코스피에 크게 진다.
# 구 인버스 추세추종(114800)은 R6 연구에서 현금보다 나은 후보가 없어 폐기됐다
# (docs/superpowers/specs/2026-10-01-sim6-bear-redesign.md).
ASSETS = [
    {'code': '069500', 'name': 'KODEX 200'},
    {'code': '360750', 'name': 'TIGER 미국S&P500'},
    {'code': '148070', 'name': 'KIWOOM 국고채10년'},
    {'code': '411060', 'name': 'ACE KRX금현물'},
    {'code': '305080', 'name': 'TIGER 미국채10년선물'},
]
# 현금성 ETF. 459580(주당 약 107만원)은 300만원 NAV에서 정수 절사 오차가 커서 안 쓴다.
# 488770(약 10.6만원)보다 단가가 낮아(약 5.8만원) 절사 잔여가 작은 357870을 쓴다.
CASH_ETF = {'code': '357870', 'name': 'TIGER CD금리투자KIS'}

ASSET_WEIGHT = 0.20      # 자산당 목표 비중(NAV 기준)
SMA_MONTHS = 10          # 10개월 이동평균 = 직전 완결 월말 종가 10개
# 목표 대비 차이가 NAV의 5%p 미만이면 건드리지 않는다(미세 리밸런스 방지).
# 연구 문서에 밴드 값이 명시되지 않아 정한 값이다. 신호가 바뀐 자산(목표 0)은 밴드와
# 무관하게 전량 매도한다.
REBALANCE_BAND = 0.05
HISTORY_DAYS = 260       # 10개 완결 월 + 이번 달 일부 ≈ 230거래일 이상
SESSION_START_MIN = 9 * 60
SESSION_END_MIN = 15 * 60 + 30

_UNIVERSE_CODES = {a['code'] for a in ASSETS} | {CASH_ETF['code']}


def _fn(funnel, code, reason, **vals):
    """왜 주문이 없었는지 한 줄 남긴다(다른 심과 같은 방식)."""
    if funnel is None:
        return
    funnel.append({'code': code, 'reason': reason, **vals})


def _prev_month(month):
    y, mo = int(month[:4]), int(month[4:])
    return f'{y - 1}12' if mo == 1 else f'{y}{mo - 1:02d}'


def trend_signal(history, month):
    """직전 완결 월말 종가 vs 10개월 이동평균 → ('above'|'below'|None, info).

    month(YYYYMM)의 봉은 쓰지 않는다 — 진행 중인 달이라 룩어헤드다. 판정 불가는
    None과 사유다(지어낸 값으로 판정하지 않는다):
      no_history    이력이 비었다(조회 실패)
      stale_history 직전 달 봉이 없다(낡은 캐시·결손) — 더 옛 월말로 판정하지 않는다
      short_history 완결 월이 10개 미만
      gap_history   최근 10개 월 사이가 비었다
      bad_close     월말 종가가 0 이하
    '아래면 현금'이므로 종가 == 평균은 'above'다.
    """
    month_end = {}
    for row in sorted(history or [], key=lambda r: r.get('date', '')):
        ym = str(row.get('date', ''))[:6]
        if len(ym) == 6 and ym < month:
            month_end[ym] = row.get('close', 0)
    if not month_end:
        return None, {'reason': 'no_history'}
    months = sorted(month_end)
    if months[-1] != _prev_month(month):
        return None, {'reason': 'stale_history', 'last_month': months[-1]}
    if len(months) < SMA_MONTHS:
        return None, {'reason': 'short_history', 'months': len(months)}
    window = months[-SMA_MONTHS:]
    for older, newer in zip(window, window[1:]):
        if _prev_month(newer) != older:
            return None, {'reason': 'gap_history', 'missing_before': newer}
    closes = [float(month_end[ym]) for ym in window]
    if min(closes) <= 0:
        return None, {'reason': 'bad_close'}
    close, sma = closes[-1], sum(closes) / len(closes)
    return ('below' if close < sma else 'above'), {'close': close, 'sma': round(sma, 2)}


def decide_gtaa(view, current_prices, signals, prev_signals, funnel=None, only=None):
    """[Sim6] GTAA-KR5 리밸런스 주문. 순수 함수. 매도 먼저, 매수 나중.

    signals: {자산코드: 'above'|'below'} — 판정 불가 자산은 키가 없다.
    prev_signals: 지난 리밸런스의 신호. 판정 불가 자산은 '비중 변경 없음'이라
      그 자산 주문을 내지 않고, 지난달 '아래'였으면 그 몫의 현금성 ETF도 유지한다.
    현재가가 없는(0·결손) 종목은 주문하지 않는다.
    only: 주어지면 이 자산들과 현금성 ETF만 주문한다 — 같은 달 재시도에서 이미
      처리한 자산을 다시 거래하지 않기 위해서다(현금성 ETF 목표는 전체 신호로 잰다).
    """
    portfolio = view['portfolio']
    nav = view['nav']
    weight_value = nav * ASSET_WEIGHT

    targets = {}
    cash_slots = 0
    for a in ASSETS:
        code = a['code']
        sig = signals.get(code)
        if sig is None:
            _fn(funnel, code, 'signal_unknown_keep')
            if prev_signals.get(code) == 'below':
                cash_slots += 1
            continue
        targets[code] = weight_value if sig == 'above' else 0.0
        if sig == 'below':
            cash_slots += 1
    targets[CASH_ETF['code']] = weight_value * cash_slots

    names = {a['code']: a['name'] for a in ASSETS + [CASH_ETF]}
    sells, buys = [], []
    for code, target in targets.items():
        if only is not None and code != CASH_ETF['code'] and code not in only:
            continue
        held = portfolio.get(code, {}).get('quantity', 0)
        px = current_prices.get(code, 0) or 0
        if px <= 0:
            if held or target > 0:
                _fn(funnel, code, 'no_price')
            continue
        if target <= 0:
            if held > 0:
                sells.append({'action': 'SELL', 'code': code, 'price': px, 'quantity': None,
                              'reason': '[GTAA] 10개월선 아래 — 현금성으로 전환',
                              'cooldown': None, 'mark_partial': False})
            else:
                _fn(funnel, code, 'below_sma')
            continue
        diff = target - held * px
        if abs(diff) < nav * REBALANCE_BAND:
            _fn(funnel, code, 'within_band', diff=round(diff))
            continue
        if diff < 0:
            qty = int(-diff / px)
            if qty > 0:
                sells.append({'action': 'SELL', 'code': code, 'price': px, 'quantity': qty,
                              'reason': '[GTAA] 비중 초과분 축소', 'cooldown': None,
                              'mark_partial': False})
            continue
        buys.append((code, diff, px))

    sell_net = 1 - BaseSimulator.SELL_FEE_RATE - BaseSimulator.SELL_TAX_RATE
    available = view['cash']
    for o in sells:
        qty = portfolio[o['code']]['quantity'] if o['quantity'] is None else o['quantity']
        available += qty * o['price'] * sell_net

    orders = list(sells)
    buy_cost = 1 + BaseSimulator.BUY_FEE_RATE
    for code, diff, px in buys:      # 자산 순서대로, 현금성 ETF가 마지막(잔여를 흡수)
        qty = int(min(diff, available / buy_cost) / px)
        if qty <= 0:
            _fn(funnel, code, 'qty_zero', price=px, cash=round(available))
            continue
        available -= qty * px * buy_cost
        orders.append({'action': 'BUY', 'code': code, 'name': names[code], 'price': px,
                       'quantity': qty, 'cooldown': None,
                       'reason': '[GTAA] 목표 비중 20% 맞춤' if code != CASH_ETF['code']
                       else f'[GTAA] 현금성 대기 ({cash_slots}개 자산 몫)'})
    return orders


def legacy_exits(view, current_prices, funnel=None):
    """유니버스 밖 보유(구 인버스 심의 114800 등)는 전량 청산. 가격 없으면 보류."""
    orders = []
    for code in list(view['portfolio'].keys()):
        if code in _UNIVERSE_CODES:
            continue
        px = current_prices.get(code, 0) or 0
        if px <= 0:
            _fn(funnel, code, 'legacy_no_price')
            continue
        orders.append({'action': 'SELL', 'code': code, 'price': px, 'quantity': None,
                       'reason': '[GTAA] 유니버스 밖 레거시 청산', 'cooldown': None,
                       'mark_partial': False})
    return orders


class BearHedgeSimulator(BaseSimulator):
    """
    [Sim 6] 방어형 자산배분 GTAA-KR5 (관찰 심, tradeable=false)
    ※ 클래스·모듈·상태파일명(sim_bear_*)은 레거시 이름을 유지한다 — 바꾸면 매니페스트
       id·ui_key·배포 목록·대시보드가 끊긴다. 전략은 2026-10-01에 재정의됐다.
    - 유니버스: 069500·360750·148070·411060·305080 + 현금성 357870 (고정 리터럴, price 없음
      → _enrich_universe가 KIS 실시간가로 채운다).
    - 국면(리베로)과 무관하게 상시 운용한다.
    - 월 1회: 그 달 첫 거래일 정규장(09:00~15:30) 첫 사이클에 리밸런스. 같은 달 중복 없음
      (state['gtaa_rebalanced_month']). 신호는 직전 완결 월말 종가로만(룩어헤드 금지).
    - 일봉 이력은 KIS get_daily_history(1일 디스크 캐시)를 리밸런스가 필요할 때만 조회.
      5자산 전부 판정 불가면 그 달을 소모하지 않고 다음 사이클에 다시 시도한다.
    - 일부만 판정 불가면 판정된 자산으로 리밸런스하고 나머지를 state['gtaa_pending']에
      남긴다. 같은 달 다음 사이클은 그 자산만 다시 조회·처리한다(이미 처리한 자산은
      다시 거래하지 않는다). 결손 자산 몫은 그동안 현금으로 남는다. 새 달 리밸런스가
      pending을 덮어쓴다.
    """
    def __init__(self, initial_cash=DEFAULT_INITIAL_CASH):
        super().__init__("Bear", initial_cash)

    def get_universe(self):
        return [dict(e) for e in ASSETS + [CASH_ETF]]

    @staticmethod
    def _fetch_history(code):
        """KIS 일봉. 실패는 빈 리스트(판정 불가) — 지어낸 이력으로 판정하지 않는다."""
        try:
            from src.trade.kis_data_provider import KISDataProvider
            return KISDataProvider().get_daily_history(code, days=HISTORY_DAYS)
        except Exception:
            return []

    @staticmethod
    def _is_trading_day(yyyymmdd):
        from src import market_calendar
        return kr_calendar.is_open(market_calendar.load_calendar(), yyyymmdd)

    def _rebalance_gate(self, now):
        """(month, pending, 사유). pending이 None이면 전체 리밸런스, 리스트면 그 자산만 재시도."""
        month = now.strftime('%Y%m')
        pending = None
        if self.state.get('gtaa_rebalanced_month') == month:
            pending = list(self.state.get('gtaa_pending') or [])
            if not pending:
                return None, None, 'already_rebalanced'
        mins = now.hour * 60 + now.minute
        if not (SESSION_START_MIN <= mins < SESSION_END_MIN):
            return None, None, 'outside_session'
        if not self._is_trading_day(now.strftime('%Y%m%d')):
            return None, None, 'not_trading_day'
        return month, pending, None

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        funnel = []
        orders = legacy_exits(self._view(current_prices), current_prices, funnel)
        self._apply(orders, current_prices)

        now = get_kst_now()
        month, pending, why = self._rebalance_gate(now)
        if month is None:
            _fn(funnel, '_gate', why)
        else:
            # 재시도면 미처리 자산만 KIS를 부른다(사이클당 자산당 1회).
            targets = [a['code'] for a in ASSETS if pending is None or a['code'] in pending]
            signals, infos = {}, {}
            for code in targets:
                sig, info = trend_signal(self._fetch_history(code), month)
                infos[code] = dict(info, signal=sig)
                if sig is None:
                    _fn(funnel, code, f"signal_{info['reason']}")
                else:
                    signals[code] = sig
            actionable = [c for c in signals if (current_prices.get(c, 0) or 0) > 0]
            if not actionable:
                # 전부 판정 불가(또는 판정된 자산의 가격이 전부 결손) — 이번 달을
                # 소모하지 않는다(재시도면 pending 그대로). 다음 사이클이 다시 시도한다.
                _fn(funnel, '_gate', 'rebalance_deferred' if pending is None else 'retry_deferred')
            else:
                prev = self.state.get('gtaa_signals', {})
                if pending is None:
                    full, only = signals, None
                else:
                    # 이번 달 이미 판정된 자산 신호 + 이번에 새로 판정된 신호.
                    # 현금성 ETF 목표가 전체 '아래' 개수로 맞게 잡히게 한다.
                    full = {c: prev[c] for c in (a['code'] for a in ASSETS)
                            if c not in pending and c in prev}
                    full.update(signals)
                    only = set(signals)
                rebalance = decide_gtaa(self._view(current_prices), current_prices,
                                        full, prev, funnel, only=only)
                self._apply(rebalance, current_prices)
                orders += rebalance
                self.state['gtaa_signals'] = {a['code']: signals.get(a['code'], prev.get(a['code']))
                                              for a in ASSETS}
                self.state['gtaa_pending'] = [c for c in targets if c not in signals]
                self.state['gtaa_rebalanced_month'] = month
                if pending is None:
                    self.state['gtaa_last_rebalance'] = {
                        'date': now.strftime('%Y-%m-%d %H:%M'), 'assets': infos}
                else:
                    last = self.state.setdefault('gtaa_last_rebalance', {'assets': {}})
                    last.setdefault('assets', {}).update(infos)
                    last['retry_date'] = now.strftime('%Y-%m-%d %H:%M')

        buys = sum(1 for o in orders if o['action'] == 'BUY')
        log_funnel('Sim6', candidates, funnel, orders, seen=buys + len(funnel), diag_id='sim6')
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
