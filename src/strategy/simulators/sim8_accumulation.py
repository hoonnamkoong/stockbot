from .base_simulator import BaseSimulator

_cooldown_active = BaseSimulator.cooldown_active

MAX_HOLDINGS = 6
POSITION_WEIGHT = 0.15   # 종목당 NAV 대비 최종 비중 (전 심 통일). 2단으로 나눠 채운다.

# 앵커링 좌표
NEAR_FLOOR = 0.85        # 52주 고점의 85% 미만이면 앵커 구간 밖
NEAR_ACCUM_MAX = 0.98    # 매집 단계 상한
NEAR_BREAK = 1.00        # 돌파 단계 하한 (신고가)

INFO_ACCUM_MIN = 1.5     # 매집 단계 정보축 임계
CONSENSUS_BOOST = 1.3    # 외인·기관 동시 순매수 가중 (Kyle: 정보거래자 합의)
MIN_SAMPLE = 10          # 횡단면 z 최소 표본. 미달이면 신호를 만들지 않는다.
MIN_AMOUNT = 1_000_000_000

TRAIL_ARM_PCT = 5.0      # 고점이 +5% 도달 후
TRAIL_CALLBACK_PCT = 3.0 # 고점 대비 -3% 하락 시 청산
STOP_PCT = -5.0


def _zmap(pairs):
    """[(code, value)] → {code: z}. 표본 부족·분산 0이면 빈 dict.

    비어 있으면 진입 조건이 성립하지 않는다(fail-closed). 표본이 얇을 때
    z를 억지로 만들면 후보 3개 중 1등이 '이상 신호'로 둔갑한다.
    """
    vals = [v for _, v in pairs]
    n = len(vals)
    if n < MIN_SAMPLE:
        return {}
    mu = sum(vals) / n
    sd = (sum((v - mu) ** 2 for v in vals) / n) ** 0.5
    if sd <= 0:
        return {}
    return {c: (v - mu) / sd for c, v in pairs}


def _features(candidates):
    """후보 횡단면 → (info, crowd, zamt).

    순매수를 거래대금으로 정규화하는 것이 핵심이다. 절대 수량으로 z를 내면
    대형주가 항상 이긴다(Sim1의 buzz>=500이 대형주 상수가 된 것과 같은 함정).
    """
    rows = []
    for s in candidates:
        code = s.get('code')
        price = float(s.get('price', 0) or 0)
        amount = float(s.get('amount', 0) or 0)
        if not code or price <= 0:
            continue
        denom = max(amount, 1.0)
        rows.append((
            code,
            float(s.get('frgn_fake_ntby_qty', 0) or 0) * price / denom,
            float(s.get('orgn_fake_ntby_qty', 0) or 0) * price / denom,
            float(s.get('foreign_change', 0) or 0),
            float(s.get('unique_posters', 0) or 0),
            amount,
        ))

    zf = _zmap([(r[0], r[1]) for r in rows])
    zo = _zmap([(r[0], r[2]) for r in rows])
    zc = _zmap([(r[0], r[3]) for r in rows])
    crowd = _zmap([(r[0], r[4]) for r in rows])
    zamt = _zmap([(r[0], r[5]) for r in rows])

    info = {}
    for code, frgn_r, orgn_r, _, _, _ in rows:
        if code not in zf or code not in zo or code not in zc:
            continue
        v = zf[code] + zo[code] + zc[code]
        if frgn_r > 0 and orgn_r > 0:
            v *= CONSENSUS_BOOST
        info[code] = v
    return info, crowd, zamt


def _nearness(stock):
    """현재가 / 52주 고점. 52주 데이터가 없으면 None."""
    hi = float(stock.get('w52_hgpr', 0) or 0)
    lo = float(stock.get('w52_lwpr', 0) or 0)
    price = float(stock.get('price', 0) or 0)
    if hi <= 0 or lo <= 0 or price <= 0:
        return None
    return price / hi


def decide_accumulation(view, candidates, current_prices):
    """[Sim8] 선행매집 결정. 순수 함수. Order 리스트 반환."""
    orders = []
    portfolio = view['portfolio']
    sold = set()
    cand_by_code = {s.get('code'): s for s in candidates if s.get('code')}
    info, crowd, zamt = _features(candidates)

    # 1. 청산 — 정보축이 꺼지면 나온다. 이 전략의 근거는 정보거래자의 존재 자체다.
    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        avg = p.get('avg_price', 0)
        if cur <= 0 or avg <= 0:
            continue
        pr = (cur - avg) / avg * 100

        if pr <= STOP_PCT:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[선행매집] 손절 ({pr:+.1f}%)", 'cooldown': 3,
                           'mark_partial': False})
            sold.add(code); continue

        peak = p.get('peak_price', avg)
        if peak >= avg * (1 + TRAIL_ARM_PCT / 100) and cur <= peak * (1 - TRAIL_CALLBACK_PCT / 100):
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[선행매집] 트레일링 청산 (고점대비 -{TRAIL_CALLBACK_PCT:.0f}%, {pr:+.1f}%)",
                           'cooldown': 1, 'mark_partial': False})
            sold.add(code); continue

        stock = cand_by_code.get(code)
        if not stock:
            continue  # 오늘 후보에 없으면 정보축·앵커를 계산할 수 없다. 판단 보류.

        iv = info.get(code)
        if iv is not None and iv < 0:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[선행매집] 정보축 반전 (info {iv:+.2f}, {pr:+.1f}%)",
                           'cooldown': 1, 'mark_partial': False})
            sold.add(code); continue

        near = _nearness(stock)
        if near is not None and near < NEAR_FLOOR:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[선행매집] 앵커 이탈 (52주고점 {near*100:.0f}%, {pr:+.1f}%)",
                           'cooldown': 1, 'mark_partial': False})
            sold.add(code); continue

    # 2. 진입 — 2단 피라미딩. 매집 단계 절반, 돌파 단계 나머지 절반.
    full = view['nav'] * POSITION_WEIGHT
    half = full / 2
    held = len([c for c in portfolio if c not in sold])
    for stock in candidates:
        code = stock['code']
        if code in sold or _cooldown_active(view['cooldown_codes'], code):
            continue
        price = float(stock.get('price', 0) or 0)
        amount = float(stock.get('amount', 0) or 0)
        near = _nearness(stock)
        iv = info.get(code)
        if price <= 0 or amount < MIN_AMOUNT or near is None or iv is None:
            continue
        if near < NEAR_FLOOR:
            continue

        cv = crowd.get(code)
        av = zamt.get(code)
        is_accum = (NEAR_FLOOR <= near < NEAR_ACCUM_MAX and iv > INFO_ACCUM_MIN
                    and cv is not None and cv < 0)
        is_break = (near >= NEAR_BREAK and iv > 0 and av is not None and av > 0)
        if not (is_accum or is_break):
            continue

        if code in portfolio:
            # 이미 매집 단계에 들어간 종목의 돌파 매수(피라미딩).
            # 목표 비중까지 남은 만큼만 채운다 — 별도 상태 없이 2단을 강제한다.
            if not is_break:
                continue
            cost = portfolio[code].get('quantity', 0) * portfolio[code].get('avg_price', 0)
            room = full - cost
            if room < half * 0.5:
                continue
            qty = int(room / price)
            label = "돌파 추가매수"
        else:
            if held >= MAX_HOLDINGS:
                continue
            qty = int(half / price)
            label = "매집 진입" if is_accum else "돌파 진입"
            held += 1

        if qty > 0:
            orders.append({'action': 'BUY', 'code': code, 'name': stock.get('name', code),
                           'price': price, 'quantity': qty, 'cooldown': None,
                           'reason': f"[선행매집] {label} (52주 {near*100:.0f}%, info {iv:+.2f})"})
    return orders


class AccumulationSimulator(BaseSimulator):
    """
    [Sim 8] 선행매집 (Smart-Money Divergence × 52주 앵커링)
    - 이론: George & Hwang(2004) 52주 고점 앵커링 때문에 좋은 정보가 가격에 늦게 반영되고,
            Kyle(1985) 그 지연 구간에서 정보거래자는 이미 사고 있다.
            심8은 그 '정보 반영 지연 구간'을 잡는다.
    - Sim1과 정확히 반대 시점이다. Sim1은 심리가 터질 때 사고, 심8은 아직 안 터졌을 때 산다.
    - 진입: (매집) 52주고점 85~98% + 정보축>1.5 + 군중축<0 → 목표 비중의 절반
            (돌파) 52주 신고가 + 정보축>0 + 거래대금z>0 → 나머지 절반
    - 청산: 정보축 부호 반전 / 앵커 이탈(<85%) / 트레일링(+5% 후 -3%) / -5% 손절
    - 데이터: w52_hgpr·w52_lwpr·frgn/orgn_fake_ntby_qty·foreign_change·unique_posters.
              전부 이미 수집 중인 필드다. 추가 네트워크 콜 0.
    - ⚠ 백테스트 없음(tradeable: false). 월별 엑셀에 52주·수급추정 컬럼이 없어
      과거 검증이 불가능하다. 페이퍼로 돌려 데이터를 쌓는 것이 현재 유일한 검증 경로다.
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("Accumulation", initial_cash)

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        orders = decide_accumulation(self._view(current_prices), candidates, current_prices)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
