from datetime import datetime

from ..regime_state import BEAR, STRONG_BEAR, REGIME6_LABEL_KO, read_regime6_confirmed
from .base_simulator import BaseSimulator, get_kst_now, DEFAULT_INITIAL_CASH, log_funnel

# base 순수 헬퍼(Task 3 @staticmethod) 재사용
_parse_change_rate = BaseSimulator.parse_change_rate
_cooldown_active = BaseSimulator.cooldown_active

# 정본: docs/superpowers/specs/2026-09-29-sim5-regime-optimization.md §7(상수)·§8(의사코드)·§9(게이트).
MAX_HOLDINGS = 5
POSITION_WEIGHT = 0.19  # 종목당 NAV 대비 비중 (0.19 × 5 = 최대 95% 투입)

# 레인지 채널 + 과매도 진입
MIN_HISTORY = 20          # 채널·RSI2 최소 일수. 10일 채널은 성과가 더 나빴다(설계서 B1)
MIN_WIDTH_PCT = 8.0       # 채널 폭 하한(%): 미달=수수료 대비 무의미 셋업 → 스킵
LOW_ZONE = 0.03           # 채널 저점 +3% 이내에서만 진입
DAILY_CRASH_PCT = -2.0    # 당일 등락이 이 값 이하면 떨어지는 칼 → 스킵
MIN_AMOUNT = 1_000_000_000
ENTRY_RSI2_MAX = 15.0     # 진입은 RSI2 < 15 (저점 근접만으로는 '하락 추세 진행 중'을 못 가른다)

# 청산 (채널 상단 트레일링은 2026-09-29 폐지 — 설계서 §4)
EXIT_RSI2_MIN = 70.0      # RSI2 > 70 과열 청산
STOP_PCT = -5.0           # 하드 손절. −3%는 모든 격자 칸에서 가장 나빴다(§4.3·§9.4)
TIMEOUT_DAYS = 10         # 타임 스탑(달력일)

# 신규 진입을 허용하는 리베로 6단계 국면. 청산은 국면과 무관.
# ⚠ 6단계 'BEAR'는 '하락' 하나다(3단계 BEAR와 철자만 같다) — 매우하락은 따로 적는다.
# 2026-10-02 {약한횡보, 하락, 매우하락} → {하락, 매우하락}(사용자 확정). 배포 코드 재생 +
# 상장폐지 267종목 보정 장기 검증에서 약한횡보만 허용 시 β조정 알파 −6.7%p(t≈−3)로 모든
# 패널에서 손해였다. 장기 MDD −72% → −44% (docs/superpowers/specs/2026-10-02-sim5-gate-review.md).
ALLOWED_REGIMES6 = frozenset({BEAR, STRONG_BEAR})


def entry_allowed(regime6) -> bool:
    """신규 진입 게이트. None(판정 불가)·모르는 값은 막는다(fail-closed)."""
    return regime6 in ALLOWED_REGIMES6


def rsi2(closes):
    """Wilder RSI, 기간 2(α=1/2 지수평활). closes는 과거→최신, 마지막이 현재가.

    연구 하네스(r3_lib.rsi2 = pandas ewm(alpha=0.5, adjust=False))와 같은 값이다.
    하락분 평균이 0이면 100(연구 구현은 50으로 채웠다 — 과매도 판정엔 영향 없음, §7).
    값이 2개 미만이면 None(계산 불가)이다.
    """
    if not closes or len(closes) < 2:
        return None
    up = dn = None
    for k in range(1, len(closes)):
        d = closes[k] - closes[k - 1]
        u, v = max(d, 0), max(-d, 0)
        up = u if up is None else 0.5 * up + 0.5 * u
        dn = v if dn is None else 0.5 * dn + 0.5 * v
    if dn == 0:
        return 100.0
    return 100 - 100 / (1 + up / dn)


def _fn(funnel, code, reason, **vals):
    """왜 안 샀는지 한 줄 남긴다(심6·심12·심13과 같은 방식).

    2026-08-31에 "심5가 어제 왜 0건이었나"에 답하지 못했다. 있던 계측은
    `near_low_pcts` 하나뿐이라 **채널폭을 통과한 뒤**의 이야기만 알 수 있었고,
    그 앞에서 걸린 후보(보유·쿨다운·유동성·채널 없음)는 흔적이 없었다.
    그래서 "조건 미달"과 "후보가 애초에 안 왔다"가 구분되지 않았다.
    """
    if funnel is None:
        return
    funnel.append({'code': code, 'reason': reason, **vals})


def _hist(range_history):
    """range_history(직전 20일 종가, 과거→최신)에서 양수만. 부족하면 None."""
    hist = [h for h in (range_history or []) if h and h > 0]
    return hist if len(hist) >= MIN_HISTORY else None


def _channel(range_history):
    """range_history(20일 종가) → (low, high, width_pct). 이력 부족 시 None."""
    hist = _hist(range_history)
    if not hist:
        return None
    low, high = min(hist), max(hist)
    return low, high, (high - low) / low * 100


def _sort_key(stock):
    """채널 저점 대비 현재가 비율(price/low) 오름차순, 동률은 코드순(설계서 §1·§8).

    채널이나 가격이 없는 후보는 맨 뒤로 보낸다 — 버리지 않고 루프에서 이유를 남긴다.
    """
    code = str(stock.get('code') or '')
    ch = _channel(stock.get('range_history'))
    try:
        price = float(stock.get('price') or 0)
    except (TypeError, ValueError):
        price = 0
    if not ch or price <= 0:
        return (float('inf'), code)
    return (price / ch[0], code)


def decide_sideways(view, candidates, current_prices, funnel=None, *, allow_entry):
    """[Sim5] 레인지 저점 + RSI2 과매도 진입 / 손절·RSI2 과열·타임스탑 청산. 순수 함수.

    allow_entry: 신규 진입 허용 여부(국면 게이트). **필수 인자다** — 기본값을 두면
      호출자가 게이트를 잊었을 때 조용히 '진입 허용'이 된다. 심5 run()은
      entry_allowed(read_regime6_confirmed())를 넘긴다 — 심10도 SIDEWAYS 위임 때 같은 값을
      넘긴다(10-01: 3단계 라우팅만으로는 강한횡보 진입을 못 막는다).
      청산은 이 값과 무관하게 항상 돈다.
    """
    orders = []
    portfolio = view['portfolio']
    today = get_kst_now().date()
    sold = set()
    cand_by_code = {s.get('code'): s for s in candidates}
    exit_no_hist = []

    # 1. 청산: 국면과 무관하게 항상. 손절 → RSI2 과열 → 타임스탑. 고정 익절·트레일링 없음.
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
                           'reason': f"[레인지] 하드 손절 ({pr:.1f}%)", 'cooldown': 3, 'mark_partial': False})
            sold.add(code); continue

        # 후보 밖(이력 없음)이면 RSI2는 판정 불가 — '과열 아님'과 섞지 않고 건너뛴다.
        hist = _hist((cand_by_code.get(code) or {}).get('range_history'))
        if hist is None:
            exit_no_hist.append(code)
        else:
            r = rsi2(hist + [cur])
            if r is not None and r > EXIT_RSI2_MIN:
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': f"[레인지] RSI2 과열 청산 (RSI2 {r:.0f}, {pr:+.1f}%)",
                               'cooldown': 2, 'mark_partial': False})
                sold.add(code); continue

        entry_str = p.get('entry_date')
        if entry_str:
            try:
                if (today - datetime.strptime(entry_str, '%Y-%m-%d').date()).days >= TIMEOUT_DAYS:
                    orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                                   'reason': f"[레인지] 타임 스탑 ({TIMEOUT_DAYS}일 경과, {pr:+.1f}%)",
                                   'cooldown': 1, 'mark_partial': False})
                    sold.add(code); continue
            except ValueError:
                pass
    if exit_no_hist:
        # 깔때기(funnel)는 '후보가 왜 탈락했나'의 장부라 보유 종목을 넣으면 회계가
        # 깨진다(미설명 음수). 판정 불가는 여기서 따로 한 줄 남긴다.
        print(f"[레인지] RSI2 청산 판정 불가(이력 없음) {len(exit_no_hist)}종목: "
              f"{', '.join(exit_no_hist)} — 손절·타임스탑만 적용")

    # 2. 진입 게이트(국면). 막혀도 위 청산은 이미 끝났다.
    if not allow_entry:
        for stock in candidates:
            _fn(funnel, stock.get('code'), 'regime_gate')
        return orders

    # 3. 진입: 넓은 채널 + 저점 근접 + 당일 급락 아님 + RSI2 과매도
    target_amount = view['nav'] * POSITION_WEIGHT
    held = len(portfolio) - len(sold)
    near_low_pcts = []  # 채널폭 통과 후보의 '저점 대비 %' — 진단용(아래 참고)
    for stock in sorted(candidates, key=_sort_key):
        code = stock['code']
        if held >= MAX_HOLDINGS:
            _fn(funnel, code, 'max_holdings', held=held)
            break
        if code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            _fn(funnel, code, 'held_or_cooldown')
            continue
        raw_price, raw_amount = stock.get('price'), stock.get('amount')
        # **필드 부재와 값 미달을 가른다.** `stock.get('amount', 0)`으로 읽으면
        # 키가 없는 것이 "거래대금 0원"이 되어 `탈락: amount 99`로 찍힌다 —
        # "유동성 부족 99종목"으로 읽히지만 진실은 "그 필드가 오지 않았다"다.
        # 심5가 배포 이래 0건이던 사고가 정확히 이 형태였다(2026-08-17 확인).
        if raw_price is None:
            _fn(funnel, code, 'no_price_field')
            continue
        if raw_amount is None:
            _fn(funnel, code, 'no_amount_field')
            continue
        price = float(raw_price or 0)
        amount = float(raw_amount or 0)
        if price <= 0:
            _fn(funnel, code, 'no_price')
            continue
        if amount < MIN_AMOUNT:
            _fn(funnel, code, 'amount', amount=amount)
            continue
        hist = _hist(stock.get('range_history'))
        if not hist:
            # range_history가 없거나 짧다 = 채널을 못 만든다. 전략 미달이 아니라
            # **입력 결손**이라 따로 센다 — 이게 후보 전량이면 배선 문제다.
            _fn(funnel, code, 'no_channel')
            continue
        low, high, width_pct = _channel(hist)
        # 조건을 한 `if`로 묶으면 "안 샀다"만 남고 어느 게이트가 막았는지
        # 사라진다. 심4-1이 같은 형태로 하루 종일 침묵했던 적이 있다.
        if width_pct < MIN_WIDTH_PCT:
            _fn(funnel, code, 'narrow_channel', width=width_pct)
            continue
        near_low_pcts.append((code, (price / low - 1) * 100))
        if price > low * (1 + LOW_ZONE):
            _fn(funnel, code, 'not_near_low', above_low_pct=(price / low - 1) * 100)
            continue
        daily_change = _parse_change_rate(stock)
        if daily_change <= DAILY_CRASH_PCT:
            _fn(funnel, code, 'daily_crash', change=daily_change)
            continue
        r = rsi2(hist + [price])
        if r is None or r >= ENTRY_RSI2_MAX:
            _fn(funnel, code, 'rsi2_not_oversold', rsi2=r)
            continue
        qty = int(target_amount / price)
        if qty <= 0:
            _fn(funnel, code, 'qty_zero', price=price, target=target_amount)
            continue
        orders.append({'action': 'BUY', 'code': code, 'name': stock['name'], 'price': price,
                       'quantity': qty, 'cooldown': None,
                       'reason': f"[레인지] 저점+과매도 (채널폭 {width_pct:.1f}%, RSI2 {r:.0f})"})
        held += 1

    # 진단(2026-08-05): 진입 신호가 며칠째 안 나오는 게 '저점 근처인데 다른 조건에
    # 걸리는지' 아니면 '애초에 저점 근처 후보가 없는지' 로그가 없어 구분이 안 됐다.
    # 버즈(인기·상승 종목) 후보와 저점진입 조건이 구조적으로 안 맞을 가능성(Sim9-1과
    # 같은 패턴)을 확인하기 위한 최소 계측 — 매수가 없을 때만 한 줄 남긴다.
    #
    # 2026-09-01: 이 계측은 **채널폭을 통과한 뒤**만 본다. 그 앞에서 걸린 후보는
    # 흔적이 없어서 "심5가 어제 왜 0건이었나"에 답하지 못했다. 이제 깔때기가
    # 전 구간을 세고, 아래 줄은 그중 '가장 아까웠던 후보'를 덧붙이는 역할만 한다.
    if not any(o['action'] == 'BUY' for o in orders) and near_low_pcts:
        code, pct = min(near_low_pcts, key=lambda x: x[1])
        print(f"[레인지] 진입 없음 — 채널폭 통과 {len(near_low_pcts)}개 중 "
              f"저점에 가장 가까운 {code} 저점 대비 {pct:+.1f}% "
              f"(기준 +{LOW_ZONE * 100:.0f}% 이내)")
    return orders


class SidewaysSwingSimulator(BaseSimulator):
    """
    [Sim 5] 레인지 저점 + 과매도 확인형 (평균회귀)
    ※ 클래스/상태파일명은 레거시('Sideways')를 유지하되 전략은 재정의됨.
       구 '추세 눌림목(+4% 고정익절)'은 목표가가 종목 실제 변동폭과 무관해 "이겨봐야 수수료"
       셋업까지 잡아 수수료에 알파가 잠식됨(2026-07 실측). 레인지 폭에 비례한 스윙으로 전환.
    - 2026-09-29 재설계(docs/superpowers/specs/2026-09-29-sim5-regime-optimization.md):
      저점 근접만으로 사면 '박스 바닥'과 '하락 추세 진행 중'을 못 가려 −3% 손절에 절반이
      걸렸다. RSI2 과매도 확인을 더하고, 청산을 RSI2 과열로 바꾸고, 손절·보유기간을 넓혔다.
    - 진입: range_history(직전 20일 종가) 채널 폭>=8% + 채널 저점 +3% 이내 + 당일 등락 > −2%
            + RSI2(이력+현재가) < 15 + 거래대금 >= 10억. 후보는 price/low 오름차순으로 채운다.
    - 청산: 하드손절 −5% / RSI2 > 70 / 10달력일 타임스탑. 고정 익절·트레일링 없음.
    - 국면 게이트는 run()에 있다: 리베로 6단계(전일 확정)가 하락·매우하락일 때만 신규 진입(10-02 G2).
      강한횡보·상승·매우상승·판정 불가(None)면 진입만 막고 **청산은 계속한다**
      (심6와 다르다 — 심6의 비 BEAR 경로는 국면 청산이라 None에서 멈춰야 하지만,
      심5의 청산은 국면을 보지 않는 손절·타임스탑이라 멈추면 손실이 방치된다).
    - 데이터: range_history는 5일 sparkline_price와 별개 필드(파리티 위해 양 환경 동일 채움).
      ⚠ 장중 range_history 첫 행이 당일 미완성 봉일 수 있다(날짜가 없어 여기서 못 거른다).
    """
    def __init__(self, initial_cash=DEFAULT_INITIAL_CASH):
        super().__init__("Sideways", initial_cash)

    def get_universe(self):
        """KOSPI 시총 상위 100 — **중립** 유니버스.

        2026-08-14 실측으로 확정: 버즈 후보를 받는 동안 이 심은 매수가 0건이었다.

            [레인지] 진입 없음 — 채널폭 통과 19개 중
            저점에 가장 가까운 000660 저점 대비 +24.4% (기준 +3% 이내)

        채널폭은 18~19개가 통과하는데 저점에 가장 가까운 종목조차 +24%다.
        버즈 후보(인기·급등 종목)는 정의상 채널 저점 근처에 있을 수 없다 —
        "박스권 저점 매수"에 "지금 뜨는 종목" 풀을 물린 셈이었다.

        상승률/하락률 상위도 답이 아니다. 이 심은 "박스권 바닥에 **조용히**
        앉아 있는 종목"을 원하는데, 그건 오늘 오른 쪽에도 내린 쪽에도 없다.
        (하락률 상위는 `daily_change > -2.0` 게이트와도 정면 충돌한다.)

        조회 실패는 None이다 — 빈 리스트로 돌려주면 '후보가 없다'가 되어
        그날 이 심이 조용히 아무것도 안 한다. None이면 호출부가 파이프라인
        후보를 그대로 쓴다.

        채널(`range_history` 20일)은 `_enrich_universe`가 채운다 — 그 보강이
        없던 동안에는 자체 유니버스를 달면 오히려 진입이 **구조적으로
        불가능**해졌다(같은 날 고쳤다).
        """
        try:
            from src.data.market_cap_universe import fetch_top100
            return fetch_top100(limit=100)
        except Exception:
            return None

    def _read_regime6(self):
        """리베로가 전일까지 확정한 6단계 국면. 판정 불가면 None(→ 신규 진입 금지).

        장중 regime6가 아니라 전일 확정값이다 — 연구 하네스의 t−1 라벨 게이트와 같고,
        심10·Sim14와 같은 헬퍼(read_regime6_confirmed)를 쓴다.

        페이퍼(trade_engine._run_simulators)와 실전(program_trader)이 같은 run()을
        부르므로 같은 파일(self.data_dir의 국면 상태)을 같은 방식으로 읽는다.
        """
        return read_regime6_confirmed(self.data_dir)

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        regime6 = self._read_regime6()
        funnel = []
        orders = decide_sideways(self._view(current_prices), candidates, current_prices,
                                 funnel=funnel, allow_entry=entry_allowed(regime6))
        log_funnel('레인지', candidates, funnel, orders,
                   regime=REGIME6_LABEL_KO.get(regime6, '판정불가'))
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
