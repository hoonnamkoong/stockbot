from . import kr_calendar
from .base_simulator import BaseSimulator, DEFAULT_INITIAL_CASH, get_kst_now, log_funnel
from .sim6_bear_hedge import (
    HISTORY_DAYS, SESSION_END_MIN, SESSION_START_MIN, _fn, month_end_closes)

# [Sim15] 코스피200 대 나스닥100 가속 듀얼모멘텀(ADM) 1배 — 관찰 심(2026-10-03).
# 정본 사양: docs/superpowers/specs/2026-10-02-max-return-etf.md §9 추천 1, 한계는 §10.
#
# 연구 수치(월말 판정·t+1 종가 체결·총수익 가격 기준 백테스트, 실거래 기록 아님):
#   2021-01~2026-09 연 37.9%(세후 35.3%)·MDD −40.8%, 2005~2020 연 15.6%·MDD −26%.
# 그대로 기대하면 안 되는 이유(같은 문서):
#   - 판정일을 5~15거래일 옮기면 2021~26 연 28~36%, 2005~20 연 9.6~15.1%로 내려간다.
#     위 수치는 '월말 판정'이라는 한 경로의 값이다.
#   - 2021~26 수익의 대부분이 2025-01~2026-06 코스피 급등에서 나왔다.
#   - 다중검정 보정 뒤 유의성은 경계선이다(DSR 0.97 / 시험 수 156 기준 0.83).
#   - 레버리지 없는 후보만으로 한 walk-forward는 코스피 보유와 같았다. 코스피 대
#     나스닥이라는 쌍 자체가 2026년 시점의 사후 선택이다.
#   - 2026 여름 급락(06-22~07-30)에 −40.8%였다. 월 1회 판정은 월중 급락을 못 피한다.
# 연구와 이 심이 다른 점: 연구는 분배 조정 가격·t+1 종가 체결, 이 심은 KIS 수정주가
# (분배 미조정)·그 달 첫 거래일 장중 첫 사이클 체결이다.
JUDGE_ASSETS = [
    {'code': '069500', 'name': 'KODEX 200'},
    {'code': '133690', 'name': 'TIGER 미국나스닥100'},
]
SAFE_ASSET = {'code': '148070', 'name': 'KIWOOM 국고채10년'}   # 구 KOSEF 국고채10년

# 점수 = 1개월 + 3개월 + 6개월 수익률 합. 6개월 수익에 6개월 전 월말이 필요하므로
# 직전 완결 월말 종가 7개를 쓴다(HISTORY_DAYS 260거래일 ≈ 12개월이라 충분하다).
LOOKBACK_MONTHS = (1, 3, 6)
SCORE_MONTHS = max(LOOKBACK_MONTHS) + 1


def adm_score(history, month):
    """직전 완결 월말 종가로 (1+3+6개월 수익률 합|None, info).

    month(YYYYMM)의 봉은 쓰지 않는다(룩어헤드). 판정 불가는 None과 사유다 —
    사유는 sim6_bear_hedge.month_end_closes와 같다.
    """
    closes, why = month_end_closes(history, month, SCORE_MONTHS)
    if closes is None:
        return None, why
    last = closes[-1]
    returns = {f'r{k}': last / closes[-1 - k] - 1 for k in LOOKBACK_MONTHS}
    return sum(returns.values()), {'close': last, **{k: round(v, 4) for k, v in returns.items()}}


def pick_winner(scores):
    """점수가 큰 판정 자산의 코드. 그 점수가 0 이하면 None(안전자산).

    동점은 JUDGE_ASSETS 나열 순서(069500 먼저)다 — 문서에 동점 규칙이 없어
    결정적으로만 정했다.
    """
    best = max((a['code'] for a in JUDGE_ASSETS), key=lambda c: scores[c])
    return best if scores[best] > 0 else None


def decide_adm(view, current_prices, target, universe, funnel=None, tag='ADM'):
    """target 한 종목 100% 보유로 맞추는 주문. 순수 함수. 매도 먼저, 매수 나중.

    universe: 이 심이 보유할 수 있는 ETF [{'code','name'}].
    - target을 이미 들고 있으면 주문 없음(남은 현금으로 더 사지 않는다).
    - 팔 종목이나 살 종목의 현재가가 하나라도 없으면 주문을 전혀 내지 않는다 —
      전량 교체는 한 묶음이고, 한쪽만 체결하면 그 달 내내 현금이거나 두 종목이다.
    - 수량은 정수 주수 절사, 남는 돈은 현금이다.
    """
    portfolio = view['portfolio']
    codes = [a['code'] for a in universe]
    names = {a['code']: a['name'] for a in universe}
    to_sell = [c for c in codes if c != target and portfolio.get(c, {}).get('quantity', 0) > 0]
    need_price = to_sell + ([] if target in portfolio else [target])
    missing = [c for c in need_price if (current_prices.get(c, 0) or 0) <= 0]
    if missing:
        for code in missing:
            _fn(funnel, code, 'no_price')
        return []

    orders = [{'action': 'SELL', 'code': c, 'price': current_prices[c], 'quantity': None,
               'reason': f'[{tag}] 월 판정 교체 — {names[target]}로', 'cooldown': None,
               'mark_partial': False} for c in to_sell]
    # sell()과 같은 세율 — ETF는 거래세 면제. 갈리면 계획한 매수가 현금 부족으로 빠진다.
    available = view['cash'] + sum(
        portfolio[c]['quantity'] * current_prices[c]
        * (1 - BaseSimulator.SELL_FEE_RATE - BaseSimulator.sell_tax_rate(c)) for c in to_sell)

    for code in codes:
        if code != target:
            _fn(funnel, code, 'not_target')
            continue
        if code in portfolio:
            _fn(funnel, code, 'hold_same')
            continue
        px = current_prices[code]
        qty = int(available / (px * (1 + BaseSimulator.BUY_FEE_RATE)))
        if qty <= 0:
            _fn(funnel, code, 'qty_zero', price=px, cash=round(available))
            continue
        orders.append({'action': 'BUY', 'code': code, 'name': names[code], 'price': px,
                       'quantity': qty, 'cooldown': None,
                       'reason': f'[{tag}] 월 판정 100% 보유'})
    return orders


def stray_exits(view, current_prices, universe_codes, funnel=None, tag='ADM'):
    """유니버스 밖 보유는 전량 청산. 가격 없으면 보류(0원에 팔지 않는다)."""
    orders = []
    for code in list(view['portfolio'].keys()):
        if code in universe_codes:
            continue
        px = current_prices.get(code, 0) or 0
        if px <= 0:
            _fn(funnel, code, 'stray_no_price')
            continue
        orders.append({'action': 'SELL', 'code': code, 'price': px, 'quantity': None,
                       'reason': f'[{tag}] 유니버스 밖 보유 청산', 'cooldown': None,
                       'mark_partial': False})
    return orders


class AdmBase(BaseSimulator):
    """심15·심16 공통 — 월 1회 판정·전량 교체. 하위 클래스가 HOLD_FOR만 바꾼다.

    - 판정은 항상 JUDGE_ASSETS(1배 ETF)의 KIS 일봉으로 한다. 일봉은 리밸런스가
      필요한 사이클에만 조회한다(get_daily_history 1일 디스크 캐시, 심6과 같은
      키라 069500은 공유된다).
    - 월 1회: 그 달 첫 거래일 정규장(09:00~15:30) 첫 사이클. 같은 달 중복 없음
      (state['adm_rebalanced_month']).
    - 두 판정 자산 중 하나라도 판정 불가면 그 달 판정을 보류한다 — 보유 유지,
      주문 없음, 달을 소모하지 않고 다음 사이클에 다시 조회한다(부분 판정으로
      갈아타지 않는다).
    - 판정은 됐는데 목표 종목을 못 들었으면(현재가 결손 등) 역시 달을 소모하지
      않는다.
    """
    LABEL = 'Sim15'
    TAG = 'ADM'
    HOLD_FOR = {a['code']: a for a in JUDGE_ASSETS}   # 판정 승자 → 실제 보유 ETF

    def get_universe(self):
        """보유 대상 ETF만(고정 리터럴, price 없음 → _enrich_universe가 KIS 실시간가로 채운다)."""
        return [dict(e) for e in list(self.HOLD_FOR.values()) + [SAFE_ASSET]]

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
        """(month, 사유). month가 None이면 이번 사이클은 판정하지 않는다."""
        month = now.strftime('%Y%m')
        if self.state.get('adm_rebalanced_month') == month:
            return None, 'already_rebalanced'
        mins = now.hour * 60 + now.minute
        if not (SESSION_START_MIN <= mins < SESSION_END_MIN):
            return None, 'outside_session'
        if not self._is_trading_day(now.strftime('%Y%m%d')):
            return None, 'not_trading_day'
        return month, None

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        universe = self.get_universe()
        funnel = []
        orders = stray_exits(self._view(current_prices), current_prices,
                             {e['code'] for e in universe}, funnel, self.TAG)
        self._apply(orders, current_prices)

        now = get_kst_now()
        month, why = self._rebalance_gate(now)
        if month is None:
            _fn(funnel, '_gate', why)
        else:
            scores, infos = {}, {}
            for asset in JUDGE_ASSETS:
                code = asset['code']
                score, info = adm_score(self._fetch_history(code), month)
                infos[code] = dict(info, score=score)
                if score is None:
                    _fn(funnel, code, f"score_{info['reason']}")
                else:
                    scores[code] = score
            if len(scores) < len(JUDGE_ASSETS):
                _fn(funnel, '_gate', 'judge_deferred')
            else:
                winner = pick_winner(scores)
                target = (self.HOLD_FOR[winner] if winner else SAFE_ASSET)['code']
                switch = decide_adm(self._view(current_prices), current_prices, target,
                                    universe, funnel, self.TAG)
                self._apply(switch, current_prices)
                orders += switch
                if target in self.state['portfolio']:
                    self.state['adm_rebalanced_month'] = month
                    self.state['adm_last_decision'] = {
                        'date': now.strftime('%Y-%m-%d %H:%M'), 'scores': infos,
                        'winner': winner, 'target': target}
                else:
                    _fn(funnel, '_gate', 'switch_deferred')

        buys = sum(1 for o in orders if o['action'] == 'BUY')
        # diag_id(심별 진단 CSV)는 쓰지 않는다 — trade_loop.DIAG_LOG_SIM_IDS와 scraper.yml
        # 배포 제외 목록에 하드코딩이 늘어난다(Sim14와 같은 이유). 깔때기는 log_funnel이
        # 전 심 공용 결정 스냅샷(decision_log)에 남긴다.
        log_funnel(self.LABEL, candidates, funnel, orders, seen=buys + len(funnel))
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)


class DualMomentumSimulator(AdmBase):
    """[Sim 15] ADM 코스피/나스닥 1배 (관찰 심, tradeable=false)

    승자가 069500이면 069500을, 133690이면 133690을, 둘 다 점수 0 이하면 148070을
    NAV 전액(정수 주수)으로 든다.
    """
    def __init__(self, initial_cash=DEFAULT_INITIAL_CASH):
        super().__init__("Adm", initial_cash)
