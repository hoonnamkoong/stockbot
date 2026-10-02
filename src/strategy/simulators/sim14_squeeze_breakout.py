import csv
import datetime as dt
import os
import statistics

from .base_simulator import BaseSimulator, get_kst_now, DEFAULT_INITIAL_CASH, log_funnel
from .. import regime_state as rs
from src import market_calendar

_cooldown_active = BaseSimulator.cooldown_active

# ── 파라미터 — 설계서 docs/superpowers/specs/2026-09-29-new-sideways-sim-design.md
# §5.1(격자)·§7.1(의사코드)의 값을 그대로 옮겼다. 바꾸면 설계서의 백테스트
# (top100 강한횡보 n=168, 건당 +2.51%, 일별 클러스터 t=+2.67)가 이 코드를
# 더는 설명하지 않는다.
# [2026-10-02 정정] 위 n=168·t=2.67은 **슬롯 제약 없는 신호 목록** 기준이다. 실제 5슬롯
# Sim14는 같은 창에서 t 1.80·NAV +40%·MDD −11%다. 장기(2005~, 폐지 보정)로는 β조정
# 알파 +0.2%/년(t 0.10)이고, 신호 품질은 강한횡보(t 1.85)가 기타 국면(t 4.20)보다
# 낮다 — 게이트는 알파가 아니라 β·MDD를 줄이는 역할이다
# (docs/superpowers/specs/2026-10-02-sim14-replay-validation.md).
MAX_HOLDINGS = 5
POSITION_WEIGHT = 0.19          # 종목당 NAV 대비 비중 (전 심 통일)
MIN_AMT5 = 1_000_000_000        # 전일까지 5일 평균 거래대금 하한(설계서 §2 유니버스 필터)

BW_WINDOW = 20                  # 볼린저 밴드폭 = 4σ(20일 종가) / MA20
BW_LOOKBACK = 60                # 밴드폭의 자기 분포 구간
SQUEEZE_Q = 0.10                # 하위 10% (이웃 q0.15·q0.25도 t≥2.0 — §5.1)
BREAKOUT_WINDOW = 20            # 직전 20거래일 **고가**(종가 아님, t 2.67 vs 10일 1.10)
AMT_WINDOW = 5
MIN_BARS = 80                   # 20 + 60 (설계서 §7.1 "최소 80봉")
MA_EXIT_WINDOW = 10             # 청산: 현재가 < MA10(확정 9봉 + 현재가)

STOP_PCT = -5.0                 # 장중 즉시
MAX_HOLD_DAYS = 10              # 확정 거래일 기준
# 마감 직전 루프(설계서 §7.1 `15:15 <= now < 15:20`). 한국장은 15:20부터
# 동시호가라 그 뒤 현재가는 종가가 아니다 — 창을 넓히지 않는다.
EXIT_WINDOW = ('15:15', '15:20')

# 일봉 원천: EOD(eod_data.yml)가 db-data/data/에 올리는 top100 OHLCV(약 100거래일,
# 운영 리베로·심9-1과 같은 모집단). trading.yml이 db-data의 data/를 통째로 받으므로
# 60초 루프에서 KIS 추가 호출 없이 읽힌다.
OHLCV_FILENAME = 'ohlcv_top100.csv'
# 마지막 확정 봉 다음 날부터 어제까지 **거래일**이 이만큼 비면 EOD가 멈춘 것이다 —
# 옛 20일 고가·분위로 사지 않는다. 하루 결손(1)은 봐준다.
# [2026-10-02 정정] 예전엔 달력일 7(STALE_CSV_DAYS)이었다. 2025 추석(마지막 봉 10/02 →
# 10/10, 8일)에 걸려 정상 신호(241560 +10.3%)를 놓쳤고 보유분 MA10·만기 판정도
# 건너뛰었다(docs/superpowers/specs/2026-10-02-sim14-replay-validation.md §4.2).
# 휴장 판정은 KIS chk-holiday 달력(opnd_yn)만 믿는다.
STALE_TRADING_DAYS = 2
# 달력이 모르는 날이 끼면(판정 불가 ≠ 개장) 평일을 거래일로 근사하고 연휴 여유를 둔다.
# 평일 8개 ≈ 달력일 12. 역대 최장 공백(2017 추석, 평일 6개)을 넘는다.
STALE_FALLBACK_WEEKDAYS = 8
CALENDAR_FILENAME = 'market_calendar.json'


def _fn(funnel, code, reason, **vals):
    """왜 안 샀는지 한 줄 남긴다(심5·심11·심12와 같은 방식).

    필드 부재(no_features·no_price_field — 데이터 경로가 고장)와 값 미달
    (no_squeeze·amt5_low·no_breakout — 전략이 거름)을 다른 이름으로 남긴다.
    고치는 곳이 다르다. 심11은 amount를 안 채워 전량 탈락한 적이 있다(08-20).
    """
    if funnel is None:
        return
    funnel.append({'code': code, 'reason': reason, **vals})


# ── 확정 일봉 ────────────────────────────────────────────────────
def csv_staleness(last_iso, today, calendar):
    """(낡음 여부, 판정 경로, 결손 거래일 수).

    마지막 확정 봉 다음 날부터 **어제까지** 개장일을 센다(오늘 봉은 원래 없다).
    달력이 전부 아는 구간이면 'calendar' — STALE_TRADING_DAYS 이상이면 낡음.
    하루라도 모르면 'weekday_approx' — 모르는 날은 평일=개장으로 세고(더 엄격),
    문턱은 STALE_FALLBACK_WEEKDAYS로 넓힌다. 근사가 연휴를 결손으로 세기 때문이다.
    """
    day = dt.date.fromisoformat(last_iso) + dt.timedelta(days=1)
    missed, approx = 0, False
    while day < today:
        verdict = market_calendar.lookup(calendar, day.strftime('%Y%m%d'))
        if verdict is None:
            approx = True
            verdict = day.weekday() < 5
        missed += 1 if verdict else 0
        day += dt.timedelta(days=1)
    if approx:
        return missed >= STALE_FALLBACK_WEEKDAYS, 'weekday_approx', missed
    return missed >= STALE_TRADING_DAYS, 'calendar', missed


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x


def load_daily_bars(path, today):
    """long 형식 OHLCV CSV → {code: {'name','dates','high','close','amount'}} (오래된→최신).

    **today 이후 행(오늘 포함)은 버린다.** EOD가 16시 이후 오늘 행을 쓰고 나면
    그 행은 미완성 봉(장중)이거나 판단 시점에 알 수 없던 값이다 — 지표는 직전
    거래일까지의 확정 봉으로만 만든다. 현재가는 돌파 판정에만 쓴다.

    고가·종가가 없는 행은 뺀다(0으로 채우지 않는다). 거래대금은 없으면 None으로
    남겨 5일 평균을 '측정 불가'로 만든다. 읽지 못하면 None.
    """
    cutoff = today.strftime('%Y%m%d')
    out = {}
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                d = (row.get('date') or '').strip()
                code = (row.get('code') or '').strip()
                if len(d) != 8 or not code or d >= cutoff:
                    continue
                high, close = _num(row.get('high')), _num(row.get('close'))
                if not high or not close or high <= 0 or close <= 0:
                    continue
                amount = _num(row.get('amount'))
                b = out.setdefault(code, {'name': (row.get('name') or code).strip(),
                                          'rows': []})
                b['rows'].append((f'{d[:4]}-{d[4:6]}-{d[6:]}', high, close,
                                  amount if amount is not None and amount >= 0 else None))
    except Exception:
        return None
    daily = {}
    for code, b in out.items():
        rows = sorted(dict((r[0], r) for r in b['rows']).values())   # 날짜 중복 제거·정렬
        daily[code] = {'name': b['name'],
                       'dates': [r[0] for r in rows],
                       'high': [r[1] for r in rows],
                       'close': [r[2] for r in rows],
                       'amount': [r[3] for r in rows]}
    return daily


def _quantile(vals, q):
    """선형 보간 분위(numpy·pandas 기본값과 같다)."""
    s = sorted(vals)
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _bandwidths(closes):
    """최근 BW_LOOKBACK개 확정일 각각의 밴드폭 4σ/MA20 (표본표준편차)."""
    out = []
    n = len(closes)
    for k in range(n - BW_LOOKBACK, n):
        win = closes[k - BW_WINDOW + 1:k + 1]
        mean = sum(win) / BW_WINDOW
        out.append(4 * statistics.stdev(win) / mean)
    return out


def entry_inputs(bars):
    """확정 일봉 → (진입 지표 dict, None) 또는 (None, 사유).

    squeeze = 전일(t-1) 밴드폭이 자기 60일 분포 하위 10% 이하
    hi20    = 직전 20거래일 최고 **고가**(당일 제외)
    amt5    = 전일까지 5일 평균 거래대금
    """
    closes, highs, amounts = bars['close'], bars['high'], bars['amount']
    if len(closes) < MIN_BARS:
        return None, 'short_history'
    last_amts = amounts[-AMT_WINDOW:]
    if any(a is None for a in last_amts):
        return None, 'no_amt5'
    bws = _bandwidths(closes)
    q10 = _quantile(bws, SQUEEZE_Q)
    return {
        'hi20': max(highs[-BREAKOUT_WINDOW:]),
        'squeeze': bws[-1] <= q10,
        'bw': bws[-1],
        'bw_q10': q10,
        'amt5': sum(last_amts) / AMT_WINDOW,
    }, None


def exit_inputs(bars):
    """청산 재료: MA10용 확정 9봉 종가 + 보유 거래일 계산용 최근 확정일. 모자라면 {}."""
    if len(bars['close']) < MA_EXIT_WINDOW - 1:
        return {}
    return {'closes9': list(bars['close'][-(MA_EXIT_WINDOW - 1):]),
            'bar_dates': list(bars['dates'][-(MAX_HOLD_DAYS * 2):])}


def _entry_reject(feat):
    """지표 단계 탈락 사유(수축 없음·거래대금 미달). 통과면 None."""
    if feat.get('squeeze') is not True:
        return 'no_squeeze'
    if feat['amt5'] < MIN_AMT5:
        return 'amt5_low'
    return None


# ── 국면 게이트 ──────────────────────────────────────────────────
def entry_gate(regime6):
    """신규 진입 허용 여부. 강한횡보에서만 — 같은 규칙이 약한횡보에서는 설계 구간
    음(−), 기타 국면에서는 검증 구간 소멸이었다(설계서 §5.1). 모르면 막는다."""
    return regime6 == rs.STRONG_SIDEWAYS


# ── 결정(순수 함수) ──────────────────────────────────────────────
def _in_exit_window(now):
    hhmm = now.strftime('%H:%M')
    return EXIT_WINDOW[0] <= hhmm < EXIT_WINDOW[1]


def _held_trading_days(entry_date, bar_dates):
    """진입일부터 어제까지 확정 거래일 수. 진입 당일은 0, 10거래일째 마감에 10."""
    return sum(1 for d in bar_dates if d >= entry_date) if entry_date else 0


def decide_sim14(view, candidates, current_prices, entry_allowed, now, funnel=None, notes=None):
    """[Sim14] 수축 돌파형. 순수 함수. Order 리스트 반환.

    entry_allowed: 국면 게이트 결과(run()이 entry_gate(rs.read_regime6_confirmed())로 정한다).
      False여도 청산은 한다 — 청산은 국면과 무관하다(설계서 §7).
    now: KST datetime. 손절은 언제나, MA10·만기는 마감 직전 창에서만 본다.
    notes: 청산 재료가 없어 MA10·만기를 못 본 보유 종목 메모(깔때기와 별도 —
      깔때기는 '왜 안 샀나'의 회계라 섞으면 후보 수와 합이 안 맞는다).
    """
    orders = []
    portfolio = view['portfolio']
    sold = set()
    cand_by_code = {stock.get('code'): stock for stock in candidates if stock.get('code')}
    closing = _in_exit_window(now)

    # 1. 청산 — 국면과 무관하게 항상
    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        avg = p.get('avg_price', 0)
        if cur <= 0 or avg <= 0:
            continue
        pr = (cur - avg) / avg * 100
        if pr <= STOP_PCT:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[Sim14] 손절 ({pr:+.1f}%)",
                           'cooldown': 1, 'mark_partial': False})
            sold.add(code)
            continue
        if not closing:
            continue
        # 진입 당일은 MA10·만기를 안 본다 — R4 백테스트는 다음 날부터 청산을 봤다.
        # 당일 판정 때문에 5건이 당일 청산돼 건당 −0.24%p였다(재생 검증 §4.1).
        if p.get('entry_date') == now.strftime('%Y-%m-%d'):
            continue
        c = cand_by_code.get(code) or {}
        closes9, bar_dates = c.get('closes9'), c.get('bar_dates')
        if not closes9 or bar_dates is None:
            if notes is not None:
                notes.append(f'{code} 확정 일봉 없음 — MA10·만기 판정 불가(손절만 유효)')
            continue
        ma10 = (sum(closes9) + cur) / MA_EXIT_WINDOW
        if cur < ma10:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[Sim14] MA10 이탈 ({ma10:,.0f} 하회, {pr:+.1f}%)",
                           'cooldown': 1, 'mark_partial': False})
            sold.add(code)
            continue
        days = _held_trading_days(p.get('entry_date', ''), bar_dates)
        if days >= MAX_HOLD_DAYS:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[Sim14] {MAX_HOLD_DAYS}거래일 만기 ({pr:+.1f}%)",
                           'cooldown': 1, 'mark_partial': False})
            sold.add(code)

    # 2. 국면 게이트 — 강한횡보가 아니면 신규 진입 없음
    if not entry_allowed:
        _fn(funnel, '_gate', 'regime_blocked')
        return orders

    # 3. 진입 — 전일 수축 + 장중 현재가가 직전 20일 고가 돌파
    target = view['nav'] * POSITION_WEIGHT
    held = len([c for c in portfolio if c not in sold])
    for stock in candidates:
        code = stock.get('code')
        if held >= MAX_HOLDINGS:
            _fn(funnel, code, 'max_holdings', held=held)
            break
        if code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            _fn(funnel, code, 'held_or_cooldown')
            continue
        hi20 = stock.get('hi20')
        if hi20 is None or stock.get('amt5') is None:
            _fn(funnel, code, 'no_features')
            continue
        raw_price = stock.get('price')
        if raw_price is None:
            _fn(funnel, code, 'no_price_field')
            continue
        price = float(raw_price or 0)
        if price <= 0:
            _fn(funnel, code, 'no_price')
            continue
        why = _entry_reject({'squeeze': stock.get('squeeze'), 'amt5': stock.get('amt5')})
        if why:
            _fn(funnel, code, why, amt5=stock.get('amt5'))
            continue
        if price <= hi20:
            _fn(funnel, code, 'no_breakout', price=price, hi20=hi20)
            continue
        qty = int(target / price)
        if qty <= 0:
            _fn(funnel, code, 'qty_zero', price=price, target=target)
            continue
        # 신호가(hi20)와 가상 체결가(현재가)를 둘 다 남긴다 — 백테스트는
        # max(시가, hi20)+0.10%에 샀고 60초 루프는 그보다 늦다(설계서 §7.1).
        orders.append({'action': 'BUY', 'code': code, 'name': stock.get('name', code),
                       'price': price, 'quantity': qty, 'cooldown': None,
                       'reason': (f"[Sim14] 수축 돌파 (신호가 hi20 {hi20:,.0f} → "
                                  f"체결 {price:,.0f}, 5일 거래대금 {stock.get('amt5') / 1e8:,.0f}억)")})
        held += 1
    return orders


class SqueezeBreakoutSimulator(BaseSimulator):
    """
    [Sim 14] 수축 돌파형 (Bollinger squeeze → 20일 고가 돌파) — 강한횡보 전용, 관찰.
    - 설계서: docs/superpowers/specs/2026-09-29-new-sideways-sim-design.md (W5, q=0.10).
      발상: 시장은 방향 없이 크게 흔들리는데(강한횡보), 자기 변동성이 바닥까지 눌려
      있던 종목이 20일 고가를 뚫는 날은 종목 고유 재료의 시작일일 가능성이 높다
      (Crabel 수축→확장). 두꺼운 꼬리 전략이라 중앙값은 음(−)이다 — 초기 손실은 정상.
    - 유니버스: 운영 top100(`data/ohlcv_top100.csv`의 종목). 버즈 의존 없음.
    - 지표(1일 1회 재료, 확정 봉만): 밴드폭 60일 하위 10%, 직전 20일 고가, 5일 평균
      거래대금 >= 10억. get_universe()가 CSV에서 계산해 통과 종목(+보유 종목)만
      내놓는다 — top100 전체를 매분 보강하면 60초 루프 예산을 넘는다.
    - 진입: 전일 확정 6단계가 강한횡보일 때만, 실시간 현재가 > hi20.
      현재가는 _enrich_universe(trade_engine)가 KIS 실시간 시세로 채운다(심11과 같은 경로).
    - 청산(국면 무관): -5% 손절 즉시 / 15:15~15:20 루프에서 현재가 < MA10 또는 10거래일 만기.
      MA10·만기는 진입 다음 날부터 본다(R4 백테스트와 같다). 손절은 진입 당일에도 본다.
      청산한 종목은 그날 재진입 금지(쿨다운 1일 = 백테스트의 '다음 날부터 재진입').
    - 페이퍼 관찰 단계(tradeable: false).
    """

    def __init__(self, initial_cash=DEFAULT_INITIAL_CASH):
        super().__init__("Squeeze", initial_cash)
        self._pre_funnel = []
        self._csv_note = None

    def _regime6_prev(self):
        return rs.read_regime6_confirmed(self.data_dir)

    def get_universe(self):
        """지표 통과 종목 + 보유 종목(청산 재료). price는 채우지 않는다.

        국면 게이트가 닫혀 있으면 보유 종목만 낸다 — 살 수 없는 종목까지 매분
        보강(네이버·KIS 호출)할 이유가 없다.
        """
        self._pre_funnel = []
        self._csv_note = None
        today = get_kst_now().date()
        portfolio = self.state.get('portfolio', {})
        daily = load_daily_bars(os.path.join(self.data_dir, OHLCV_FILENAME), today)
        if daily:
            last = max(b['dates'][-1] for b in daily.values() if b['dates'])
            calendar = market_calendar.load_calendar(
                os.path.join(self.data_dir, CALENDAR_FILENAME))
            stale, mode, missed = csv_staleness(last, today, calendar)
            self._csv_note = f'일봉 마지막 {last}, 결손 거래일 {missed} (판정 {mode})'
            if stale:
                _fn(self._pre_funnel, '_csv', 'stale_daily_csv', last=last,
                    mode=mode, missed=missed)
                daily = None
        else:
            _fn(self._pre_funnel, '_csv', 'no_daily_csv')
        daily = daily or {}
        entry_open = entry_gate(self._regime6_prev())

        out = []
        for code in sorted(set(daily) | set(portfolio)):
            bars = daily.get(code)
            name = bars['name'] if bars else portfolio[code].get('name', code)
            entry = {'code': code, 'name': name}
            if bars:
                entry.update(exit_inputs(bars))
            if code in portfolio:
                out.append(entry)
                continue
            if not entry_open:
                continue
            feat, why = entry_inputs(bars)
            why = why or _entry_reject(feat)
            if why:
                _fn(self._pre_funnel, code, why)
                continue
            entry.update(hi20=feat['hi20'], squeeze=True, amt5=feat['amt5'])
            out.append(entry)
        return out

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        regime6 = self._regime6_prev()
        funnel, notes = [], []
        orders = decide_sim14(self._view(current_prices), candidates, current_prices,
                              entry_gate(regime6), get_kst_now(), funnel=funnel, notes=notes)
        pre = list(self._pre_funnel)
        if self._csv_note:
            notes.insert(0, self._csv_note)
        # diag_id(심별 진단 CSV)는 쓰지 않는다 — 그러면 trade_loop.DIAG_LOG_SIM_IDS와
        # scraper.yml 배포 제외 목록 두 곳에 하드코딩이 늘어난다. 깔때기는
        # log_funnel이 전 심 공용 결정 스냅샷(decision_log)에 이미 남긴다.
        log_funnel('Sim14', candidates, pre + funnel, orders,
                   seen=len(candidates) + len(pre), regime=regime6, details=notes)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
