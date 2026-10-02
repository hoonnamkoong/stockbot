import json
import os

from .base_simulator import BaseSimulator, get_kst_now, DEFAULT_INITIAL_CASH, log_funnel

_cooldown_active = BaseSimulator.cooldown_active

MAX_HOLDINGS = 5
POSITION_WEIGHT = 0.19       # 종목당 NAV 대비 비중 (전 심 통일)
MIN_AMOUNT = 1_000_000_000   # 거래대금 최소 문턱(매수 시점 실시간 값으로 확인)

STOP_PCT = -7.5              # 미너비니의 시그니처 손절폭(7~8%)의 중간값
MA_EXIT_WINDOW = 50          # 50일선 이탈 시 청산(추세 종료 신호)
# 50일선 이탈은 마감 직전 창에서만 판정한다(손절은 언제나). Sim14 EXIT_WINDOW와
# 같은 창·같은 비교(15:15 포함, 15:20 미포함) — 15:20부터 동시호가라 그 뒤
# 현재가는 종가가 아니다. 창을 놓친 보유분은 EOD가 exit_next_open으로 표시해
# 다음날 첫 사이클에 판다. 배포 재생 하네스로 장기 알파 연 -6.7→+2.0%(8/8 경로)
# (docs/superpowers/specs/2026-10-02-sim11-ma50-close-exit.md).
MA_EXIT_TIME_WINDOW = ('15:15', '15:20')

MIN_ABOVE_52W_LOW_PCT = 30.0   # 52주 저가 대비 최소 상승폭
MAX_BELOW_52W_HIGH_PCT = 25.0  # 52주 고가 대비 최대 하락폭
MA200_TREND_LOOKBACK = 20      # 200일선 상승 추세 판정에 쓰는 과거 시점(약 1개월 전)

MIN_EPS_GROWTH_YOY = 20.0     # SEPA 실적 가속 필터 — EPS 전년동기대비
MIN_REVENUE_GROWTH_YOY = 15.0  # SEPA 실적 가속 필터 — 매출 전년동기대비

CONTRACTION_WINDOW = 10       # VCP 압축 판정 구간(최근 vs 그 이전)
PIVOT_WINDOW = 20             # 돌파 기준 최근 고점 탐색 구간
# 최근 구간 변동폭이 이전 구간의 85% 미만이면 압축으로 본다.
# 2026-09-29 0.7→0.85: 운영 감시목록이 2~3종목으로 말라 리셋(09-21) 후 거래 0건.
# 야후 3년 백테스트(기술조건만, 2023-07~2026-09)에서 거래당 +1.68%→+2.46%,
# 일별 클러스터 t 1.27→2.42 (docs/superpowers/specs/2026-09-29-sim11-profit-analysis.md).
# [2026-10-02 정정] 위 수치는 연구 하네스(배당 수정 가격·ma50 종가 판정 근사) 값이다.
# 배포 코드 직접 재생으로는 0.7 t 0.88 → 0.85 t 1.55(n 1136→1380, 건당 +1.40→+2.06%).
# 방향은 맞지만 유의하지 않다 — 감시목록 고갈을 푸는 운영 변경으로만 유지한다
# (docs/superpowers/specs/2026-10-02-sim11-replay-validation.md).
CONTRACTION_RATIO = 0.85

# EOD 배치(scripts/run_eod_sims.py)가 쓰고, get_universe()가 읽는다. 하루에
# 한 번만 갱신되는 파일이라 다른 심의 state_file과 달리 db-data 배포 목록에
# 별도로 넣어야 한다(eod_data.yml).
WATCHLIST_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'data', 'sim11_watchlist.json')



def _fn(funnel, code, reason, **vals):
    """왜 안 샀는지 한 줄 남긴다(심5·심6·심12와 같은 방식).

    심11은 **감시목록이 유일한 입구**다(EOD 배치가 만든다). 그래서 0건일 때
    가능한 원인이 셋이나 되는데 밖에서 구분이 안 됐다 — 감시목록이 비었는가,
    목록은 있는데 pivot을 못 넘었는가, 이미 보유 중인가. 2026-08-31에 실제로
    이 질문을 받고 상태 파일과 감시목록을 손으로 대조해서야 답했다
    (엔트리가 GS 하나였고 그건 이미 보유 중이었다).
    """
    if funnel is None:
        return
    funnel.append({'code': code, 'reason': reason, **vals})

def _sma(closes: list[float], window: int) -> float | None:
    """단순이동평균. 표본이 모자라면 None(지어내지 않는다)."""
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _trend_template_ok(price: float, closes: list[float],
                       w52_hgpr: float, w52_lwpr: float) -> bool:
    """추세 템플릿 통과 여부만. 사유가 필요하면 _trend_template_reject를 쓴다."""
    return _trend_template_reject(price, closes, w52_hgpr, w52_lwpr) is None


def _trend_template_reject(price: float, closes: list[float],
                           w52_hgpr: float, w52_lwpr: float) -> str | None:
    """미너비니 추세 템플릿(간소화 6항목 — 상대강도 순위는 횡단면 데이터가
    필요해 V1에서 뺐다. docstring 참고).

    1. 종가 > MA150 > MA200 (정배열)
    2. MA50 > MA150 및 MA50 > MA200
    3. 종가 > MA50
    4. MA200이 약 한 달 전보다 높다(상승 추세)
    5. 52주 저가 대비 30%+ 상승
    6. 52주 고가 대비 25% 이내
    """
    ma50 = _sma(closes, 50)
    ma150 = _sma(closes, 150)
    ma200 = _sma(closes, 200)
    if ma50 is None or ma150 is None or ma200 is None:
        return 'short_history'
    if len(closes) < 200 + MA200_TREND_LOOKBACK:
        return 'short_history'
    ma200_prior = _sma(closes[:-MA200_TREND_LOOKBACK], 200)
    if ma200_prior is None:
        return 'short_history'

    if not (price > ma150 > ma200):
        return 'not_stacked'
    if not (ma50 > ma150 and ma50 > ma200):
        return 'not_stacked'
    if not (price > ma50):
        return 'below_ma50'
    if not (ma200 > ma200_prior):
        return 'ma200_flat'
    if w52_lwpr <= 0 or w52_hgpr <= 0:
        return 'no_52w'
    if price < w52_lwpr * (1 + MIN_ABOVE_52W_LOW_PCT / 100):
        return 'near_52w_low'
    if price < w52_hgpr * (1 - MAX_BELOW_52W_HIGH_PCT / 100):
        return 'far_below_52w_high'
    return None


def _vcp_contracting(closes: list[float]) -> bool:
    """변동성 수축(VCP) 판정만 한다 — 돌파(가격 비교)는 여기서 안 본다.

    2026-08-20 재설계: 예전엔 "오늘 종가가 pivot을 넘었나"까지 이 함수가
    판정했는데, 그건 EOD 배치(장 마감 후)가 **이미 끝난 오늘 종가**로
    매수 여부를 정하는 꼴이었다 — 실제로 그 가격에 살 수 있는 시점이
    지나 있다(backtest-lookahead-trap과 같은 함정, program-trading-parity
    위반). 돌파 판정은 이제 decide_minervini가 **장중 실시간가**로 한다.
    이 함수는 압축 여부만 판정해 감시 목록(watchlist) 등재 자격을 정한다.

    closes는 오늘까지 포함한 종가열이어야 한다(watchlist는 내일 쓸 것이므로
    오늘이 이미 '과거'다).
    """
    need = CONTRACTION_WINDOW * 2
    if len(closes) < need:
        return False
    recent = closes[-CONTRACTION_WINDOW:]
    prior = closes[-CONTRACTION_WINDOW * 2:-CONTRACTION_WINDOW]
    if recent[-1] <= 0 or prior[-1] <= 0:
        return False
    recent_range = (max(recent) - min(recent)) / recent[-1]
    prior_range = (max(prior) - min(prior)) / prior[-1]
    if prior_range <= 0:
        return False
    return recent_range < prior_range * CONTRACTION_RATIO


def build_watchlist_entry(stock: dict, funnel=None) -> dict | None:
    """감시 목록 항목 하나를 만든다. 자격 미달이면 None.

    stock은 scripts.run_eod_sims.candidates_from_kis_live가 주는 형태다:
    price(오늘 종가), daily_closes(오늘 미포함 과거 종가), w52_hgpr, w52_lwpr,
    eps_growth_yoy(없으면 결손), revenue_growth_yoy.

    반환하는 pivot_price·ma50은 **내일부터** 쓸 기준이다 — 오늘을 '이미 지난
    거래일'로 넣어 계산한다(closes_through_today = daily_closes + [price]).
    """
    code = stock.get('code', '')
    price = float(stock.get('price', 0) or 0)
    daily_closes = stock.get('daily_closes') or []
    if price <= 0:
        _fn(funnel, code, 'no_price')
        return None

    w52_hgpr = float(stock.get('w52_hgpr', 0) or 0)
    w52_lwpr = float(stock.get('w52_lwpr', 0) or 0)
    rejected = _trend_template_reject(price, daily_closes, w52_hgpr, w52_lwpr)
    if rejected:
        _fn(funnel, code, rejected)
        return None

    # 결손(KIS가 값을 안 줌)과 미달(값은 있는데 기준에 못 미침)을 가른다.
    # 고치는 곳이 다르다 — 전자는 수집, 후자는 임계값이다.
    eps_g = stock.get('eps_growth_yoy')
    rev_g = stock.get('revenue_growth_yoy')
    if eps_g is None:
        _fn(funnel, code, 'no_eps')
        return None
    if eps_g < MIN_EPS_GROWTH_YOY:
        _fn(funnel, code, 'eps_low', eps=round(float(eps_g), 1))
        return None
    if rev_g is None:
        _fn(funnel, code, 'no_revenue')
        return None
    if rev_g < MIN_REVENUE_GROWTH_YOY:
        _fn(funnel, code, 'revenue_low', rev=round(float(rev_g), 1))
        return None

    closes_through_today = daily_closes + [price]
    if not _vcp_contracting(closes_through_today):
        _fn(funnel, code, 'no_vcp')
        return None
    ma50 = _sma(closes_through_today, MA_EXIT_WINDOW)
    if ma50 is None:
        _fn(funnel, code, 'no_ma50')
        return None

    return {
        'name': stock.get('name', stock.get('code', '')),
        'pivot_price': max(closes_through_today[-PIVOT_WINDOW:]),
        'ma50': ma50,
    }


def save_watchlist(entries: dict[str, dict], date_str: str) -> None:
    os.makedirs(os.path.dirname(WATCHLIST_PATH), exist_ok=True)
    with open(WATCHLIST_PATH, 'w', encoding='utf-8') as f:
        json.dump({'date': date_str, 'entries': entries}, f, ensure_ascii=False)


def load_watchlist(date_str: str) -> dict[str, dict]:
    """오늘 날짜와 일치할 때만 돌려준다(fail-closed).

    낡은 감시 목록을 오늘 걸로 오인하면 며칠 전 pivot_price로 잘못된 시점에
    사게 된다 — status.json 신선도 검사 없이 조용히 옛 값을 쓰던 Sim8의
    함정과 같은 유형이다.
    """
    try:
        with open(WATCHLIST_PATH, encoding='utf-8-sig') as f:
            data = json.load(f)
    except Exception:
        return {}
    if not isinstance(data, dict) or data.get('date') != date_str:
        return {}
    entries = data.get('entries')
    return entries if isinstance(entries, dict) else {}


def _in_ma_exit_window(now):
    hhmm = now.strftime('%H:%M')
    return MA_EXIT_TIME_WINDOW[0] <= hhmm < MA_EXIT_TIME_WINDOW[1]


def tally_ma50_window(state, now):
    """마감 창 사이클 수를 state['ma50_window']에 날짜별로 센다.

    날이 바뀐 첫 사이클에 전일 값을 한 줄로 돌려준다(아니면 None). 0회면
    창을 놓친 날이다 — "창을 놓쳤다"와 "판정했는데 안 걸렸다"는 거래 기록만
    보면 같은 모양이라 따로 세야 한다. 루프는 런마다 새 프로세스라 메모리가
    아니라 심 상태 파일(배포됨)에 둔다. 루프가 하루 통째로 안 돈 날은 줄이 없다.
    """
    today = now.strftime('%Y-%m-%d')
    tally = state.get('ma50_window')
    line = None
    if not isinstance(tally, dict) or tally.get('date') != today:
        if isinstance(tally, dict) and tally.get('date'):
            n = int(tally.get('cycles', 0) or 0)
            line = (f"[미너비니] {tally['date']} 마감 창 50일선 판정 사이클 {n}회"
                    + (" — 창 놓침(그 날 보유분은 EOD 표시로 익일 청산)" if n == 0 else ""))
        tally = {'date': today, 'cycles': 0}
    if _in_ma_exit_window(now):
        tally['cycles'] += 1
    state['ma50_window'] = tally
    return line


def decide_minervini(view, candidates, current_prices, now, funnel=None, notes=None):
    """[Sim11] 미너비니 SEPA/VCP 결정. 순수 함수. Order 리스트 반환.

    now: KST datetime. 손절은 언제나, 50일선 이탈은 마감 창(MA_EXIT_TIME_WINDOW)
      에서만 본다(진입일 보유분 포함). 감시목록 항목에 exit_next_open이 있으면
      (EOD가 전일 종가 < ma50으로 표시) 시간과 무관하게 첫 사이클에 판다.
    notes: 마감 창에서 ma50이 없어 판정을 못 한 보유 종목 메모.

    candidates는 get_universe()가 준 감시 목록(code, name, pivot_price, ma50)에
    _enrich_universe가 실시간 price·amount를 채운 것이다 — 무거운 계산
    (추세 템플릿·실적 가속·VCP 압축)은 이미 EOD 배치에서 끝났고, 여기서는
    **실시간가가 pivot을 넘는지**만 본다(program-trading-parity: 실제로
    체결 가능한 가격으로만 판단).
    """
    orders = []
    portfolio = view['portfolio']
    sold = set()
    cand_by_code = {s['code']: s for s in candidates if s.get('code')}
    closing = _in_ma_exit_window(now)

    # 1. 청산 — 하드손절(언제나) / 전일 종가 이탈 표시(첫 사이클) / 50일선 이탈(마감 창)
    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        avg = p.get('avg_price', 0)
        if cur <= 0 or avg <= 0:
            continue
        pr = (cur - avg) / avg * 100

        if pr <= STOP_PCT:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[미너비니] 손절 ({pr:+.1f}%)",
                           'cooldown': 3, 'mark_partial': False})
            sold.add(code); continue

        c = cand_by_code.get(code) or {}
        # 폴백: 전일 마감 창을 놓쳤거나 15:15 현재가가 종가와 갈려 못 판 보유분.
        # 사유 문자열을 창 판정과 구분해 둔다 — 판정 경로별 성과를 나눠 봐야 한다.
        if c.get('exit_next_open'):
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[미너비니] {MA_EXIT_WINDOW}일선 이탈(전일 종가 판정, 익일 청산) ({pr:+.1f}%)",
                           'cooldown': 3, 'mark_partial': False})
            sold.add(code); continue

        if not closing:
            continue
        ma50 = c.get('ma50')
        if ma50 is None:
            # 지어낸 값으로 팔지 않는다 — 손절만 유효하다는 사실을 남긴다.
            if notes is not None:
                notes.append(f'{code} ma50 없음 — 50일선 판정 불가(손절만 유효)')
            continue
        if cur < ma50:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[미너비니] {MA_EXIT_WINDOW}일선 이탈(마감 판정) ({ma50:,.0f} 하회, {pr:+.1f}%)",
                           'cooldown': 3, 'mark_partial': False})
            sold.add(code); continue

    # 2. 진입 — 감시 목록 종목의 실시간가가 pivot_price를 넘는 순간 산다.
    target_amount = view['nav'] * POSITION_WEIGHT
    held = len([c for c in portfolio if c not in sold])
    for stock in candidates:
        code = stock.get('code')
        if held >= MAX_HOLDINGS:
            _fn(funnel, code, 'max_holdings', held=held)
            break
        if not code:
            _fn(funnel, '_', 'no_code')
            continue
        if code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            _fn(funnel, code, 'held_or_cooldown')
            continue

        raw_price, raw_amount = stock.get('price'), stock.get('amount')
        # 필드 부재와 값 미달은 다른 고장이다 — 전자는 데이터 경로, 후자는 전략.
        if raw_price is None:
            _fn(funnel, code, 'no_price_field')
            continue
        if raw_amount is None:
            _fn(funnel, code, 'no_amount_field')
            continue
        price = float(raw_price or 0)
        amount = float(raw_amount or 0)
        pivot = stock.get('pivot_price')
        # 셋을 한 `if`로 묶으면 "안 샀다"만 남는다. 특히 `no_pivot`은 전략 미달이
        # 아니라 **감시목록 결손**이라 성격이 다르다 — 이게 후보 전량이면 EOD
        # 배치가 목록을 못 만든 것이고, 심을 고칠 게 아니라 배치를 봐야 한다.
        if price <= 0:
            _fn(funnel, code, 'no_price')
            continue
        if pivot is None:
            _fn(funnel, code, 'no_pivot')
            continue
        if amount < MIN_AMOUNT:
            _fn(funnel, code, 'amount', amount=amount)
            continue
        if price <= pivot:
            _fn(funnel, code, 'below_pivot', price=price, pivot=pivot)
            continue

        qty = int(target_amount / price)
        if qty <= 0:
            _fn(funnel, code, 'qty_zero', price=price, target=target_amount)
            continue
        orders.append({'action': 'BUY', 'code': code, 'name': stock.get('name', code),
                       'price': price, 'quantity': qty, 'cooldown': None,
                       'reason': f"[미너비니] 실시간 pivot 돌파 ({pivot:,.0f} 상회)"})
        held += 1
    return orders


class MinerviniTrendSimulator(BaseSimulator):
    """
    [Sim 11] 미너비니 추세형 (SEPA / VCP — Trend Template)
    - 레퍼런스: Mark Minervini. US Investing Championship 1997 +155%, 2021 +334.8%(대회 감사·검증).
      다만 그 수익률은 레버리지·집중·재량판단이 섞인 개인 성과다 — 이 심은
      문서화된 규칙(트렌드 템플릿+실적 가속+VCP)만 기계적으로 따르므로 같은
      수익률을 재현한다는 보장은 없다.

    - **2026-08-20 재설계: EOD 판단 + EOD 체결 → EOD 판단 + 장중 체결.**
      처음 버전은 마감 후 배치가 그날 종가로 사고팔았다 — 이미 지난
      가격으로 "샀다"고 기록하는 룩어헤드였고(backtest-lookahead-trap),
      실전으로 승격해도 그 가격에 주문을 낼 방법이 없었다
      (program-trading-parity-mandate 위반). 이제 무거운 계산(추세
      템플릿·실적 가속·VCP 압축, 종목당 KIS 3콜)만 EOD 배치가 하루 1회
      돌려 **감시 목록**(WATCHLIST_PATH)에 남기고, 실제 매수/매도는 이
      심이 **장중 1분 루프**(다른 버즈 불필요 심들과 같은 경로)에서
      실시간가로 한다.
    - 진입: 감시 목록에 있고(전날 밤 이미 추세 템플릿+실적 가속+VCP 압축
      통과), 실시간가가 그때 계산한 pivot_price(20일 고점)를 넘으면 산다.
    - 청산: 하드손절 -7.5%(실시간가, 언제나) / 50일선 이탈(추세 종료) —
      2026-10-02부터 장중 즉시가 아니라 마감 창(15:15~15:20) 사이클의 현재가로
      판정하고, 창을 놓친 보유분은 EOD 표시(exit_next_open)로 다음날 첫
      사이클에 판다. 고정 익절 없음 — 승자는 끝까지 탄다.
    - get_universe()는 감시 목록만 돌려주고 **price를 채우지 않는다** —
      _enrich_universe(trade_engine.py)가 실시간 KIS 시세로 채운다(Sim6와
      같은 공유 보강 경로를 그대로 탄다). 오늘 날짜 감시 목록이 없으면
      빈 유니버스(폴백 없음 — 낡은 pivot으로 사지 않는다).
    - 상대강도(RS) 순위는 V1에서 뺐다 — 횡단면 전체 유니버스의 기간수익률
      랭킹이 필요한데 지금 유니버스(top100 비ETF)가 그 모집단으로 적절한지
      미검증이라 다음 버전 과제로 남긴다.
    - 감시 목록 생성: `scripts/run_eod_sims.py`가 하루 1회(장 마감 후) 돈다.
      필요 데이터(200일+ 일봉, 분기 EPS/매출성장률)는 2026-08-20에 KIS 실측
      확인: `KISDataProvider.get_daily_history`/`get_earnings_growth`.
    """

    def __init__(self, initial_cash=DEFAULT_INITIAL_CASH):
        super().__init__("Minervini", initial_cash)

    def get_universe(self):
        today = get_kst_now().strftime('%Y%m%d')
        entries = load_watchlist(today)
        return [
            {'code': code, 'name': e.get('name', code),
             'pivot_price': e.get('pivot_price'), 'ma50': e.get('ma50'),
             # 필드 추가 전 감시목록 파일에는 없다 — 없으면 표시 없음(False).
             'exit_next_open': e.get('exit_next_open') is True}
            for code, e in entries.items()
        ]

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        now = get_kst_now()
        tally_line = tally_ma50_window(self.state, now)
        if tally_line:
            # 하루 한 줄. log_funnel의 details는 후보가 비면 안 찍혀서 직접 찍는다.
            print(tally_line)
        funnel, notes = [], []
        orders = decide_minervini(self._view(current_prices), candidates,
                                  current_prices, now, funnel=funnel, notes=notes)
        log_funnel('미너비니', candidates, funnel, orders, details=notes)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
