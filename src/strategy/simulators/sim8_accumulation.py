import os

from .base_simulator import BaseSimulator, DEFAULT_INITIAL_CASH, log_funnel

_cooldown_active = BaseSimulator.cooldown_active

MAX_HOLDINGS = 5
POSITION_WEIGHT = 0.19   # 종목당 NAV 대비 최종 비중 (전 심 통일). 2단으로 나눠 채운다.

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



def _fn(funnel, code, reason, **vals):
    """왜 안 샀는지 한 줄 남긴다(심5·심6·심12와 같은 방식).

    심8은 게이트가 많고(유동성·근접도·수급·군중·매집/돌파 판정) 조건이 한
    `if`에 뭉쳐 있어, 0건일 때 밖에서는 어느 단계에서 끊겼는지 알 수 없었다.
    피처 계산 루프에서 조용히 빠지는 종목도 있어 "후보가 애초에 안 왔다"와
    "왔는데 걸렸다"조차 구분되지 않았다.
    """
    if funnel is None:
        return
    funnel.append({'code': code, 'reason': reason, **vals})

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
    """후보 횡단면 → (info, zamt).

    순매수를 거래대금으로 정규화하는 것이 핵심이다. 절대 수량으로 z를 내면
    대형주가 항상 이긴다(Sim1의 buzz>=500이 대형주 상수가 된 것과 같은 함정).

    군중축은 여기서 만들지 않는다. 유니버스가 외인·기관 순매수 상위로 바뀌면
    후보에 unique_posters가 아예 없어 횡단면 z가 퇴화한다(전부 0 → 표준편차 0
    → 빈 dict). 관심의 기준선은 버즈 유니버스에서 따로 가져온다 → crowd_reference.
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
            amount,
        ))

    zf = _zmap([(r[0], r[1]) for r in rows])
    zo = _zmap([(r[0], r[2]) for r in rows])
    zc = _zmap([(r[0], r[3]) for r in rows])
    zamt = _zmap([(r[0], r[4]) for r in rows])

    info = {}
    for code, frgn_r, orgn_r, _, _ in rows:
        if code not in zf or code not in zo or code not in zc:
            continue
        v = zf[code] + zo[code] + zc[code]
        if frgn_r > 0 and orgn_r > 0:
            v *= CONSENSUS_BOOST
        info[code] = v
    return info, zamt


def _median(values):
    srt = sorted(values)
    return srt[len(srt) // 2] if srt else None


def _crowd_baseline(candidates, view):
    """관심 기준선 → ({code: 관심}, 중앙값). 중앙값이 None이면 판정 불가다.

    후보 자체가 unique_posters를 들고 있으면(버즈 유니버스) 그 분포를 쓴다 —
    외부 파일에 기대지 않는 편이 정확하고, 같은 런의 같은 횡단면이다.
    안 들고 있으면(외인·기관 순매수 상위 유니버스) run()이 뷰에 넣어준
    버즈 기준선을 쓴다.
    """
    vals = {}
    for s in candidates:
        code = s.get('code')
        try:
            v = float(s.get('unique_posters') or 0)
        except (TypeError, ValueError):
            continue
        if code and v > 0:
            vals[code] = v
    if vals:
        return vals, _median(vals.values())
    return view.get('buzz_attention') or {}, view.get('buzz_median')


def crowd_reference(data_dir):
    """버즈 유니버스의 관심 분포에서 기준선을 뽑는다 → ({code: 관심}, 중앙값).

    latest_stocks.json은 파이프라인 2단계(llm_analyzer)가 매 런 덮어쓰므로 심이
    도는 3단계 시점에는 당일 최신본이다.

    순위 유니버스 종목이 이 목록에 없다는 것은 지어낸 값이 아니라 측정이다 —
    그 종목에는 사람들이 글을 안 쓰고 있다. 그래서 '없음'을 관심 0으로 읽는다.

    읽지 못하면 (빈 dict, None)이다. 중앙값이 None이면 '군중 미도달'을 판정할
    수 없다는 뜻이고, 호출부는 매집을 하지 않는다(없는 근거로 사지 않는다).

    ⚠ **신선도를 반드시 검사한다.** 파일이 낡아도 값은 멀쩡히 들어 있어서
    fail-closed가 걸리지 않고 **옛 기준선으로 조용히 판정**한다. 2026-08-17에
    로컬에 5월자 파일(2종목)이 남아 있는 것을 확인했다 — 그대로면 '군중 미도달'이
    3개월 전 분포로 결정된다. 파일 mtime은 못 쓴다(CI 체크아웃이 갱신한다).
    같은 순간에 쓰이는 `status.json`의 `last_updated`를 본다.
    (심0의 breadth가 stale CSV로 18일 박제됐던 것과 같은 유형이다.)
    """
    import json
    from datetime import datetime, timedelta, timezone
    try:
        with open(os.path.join(data_dir, 'status.json'), encoding='utf-8-sig') as f:
            updated = str(json.load(f).get('last_updated', ''))[:10]
        today = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d')
        if updated != today:
            print(f'[Sim8] 버즈 기준선이 낡았다(status.json {updated or "없음"} ≠ {today}) — 매집 보류')
            return {}, None
    except Exception as e:
        print(f'[Sim8] 버즈 기준선 신선도 확인 실패: {e} — 매집 보류')
        return {}, None
    try:
        with open(os.path.join(data_dir, 'latest_stocks.json'), encoding='utf-8-sig') as f:
            rows = json.load(f)
    except Exception:
        return {}, None
    if not isinstance(rows, list):
        return {}, None
    attention = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        code = r.get('code')
        try:
            v = float(r.get('unique_posters') or 0)
        except (TypeError, ValueError):
            continue
        if code and v > 0:
            attention[code] = v
    if not attention:
        return {}, None
    return attention, _median(attention.values())


def _nearness(stock):
    """현재가 / 52주 고점. 52주 데이터가 없으면 None."""
    hi = float(stock.get('w52_hgpr', 0) or 0)
    lo = float(stock.get('w52_lwpr', 0) or 0)
    price = float(stock.get('price', 0) or 0)
    if hi <= 0 or lo <= 0 or price <= 0:
        return None
    return price / hi


def decide_accumulation(view, candidates, current_prices, funnel=None):
    """[Sim8] 선행매집 결정. 순수 함수. Order 리스트 반환."""
    orders = []
    portfolio = view['portfolio']
    sold = set()
    cand_by_code = {s.get('code'): s for s in candidates if s.get('code')}
    info, zamt = _features(candidates)
    attention, crowd_median = _crowd_baseline(candidates, view)

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
            _fn(funnel, code, 'sold_or_cooldown')
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
        near = _nearness(stock)
        iv = info.get(code)
        # 넷을 한 `if`로 묶으면 "안 샀다"만 남는다. 특히 `near`/`iv`가 None인 건
        # 전략 미달이 아니라 **입력 결손**(52주 정보·수급)이라 성격이 다르다 —
        # 이게 후보 전량이면 심이 아니라 데이터 경로를 봐야 한다.
        if price <= 0:
            _fn(funnel, code, 'no_price')
            continue
        if amount < MIN_AMOUNT:
            _fn(funnel, code, 'amount', amount=amount)
            continue
        if near is None:
            _fn(funnel, code, 'no_52w_anchor')
            continue
        if iv is None:
            _fn(funnel, code, 'no_investor_flow')
            continue
        if near < NEAR_FLOOR:
            _fn(funnel, code, 'below_anchor', near=near)
            continue

        # 군중 미도달 = 버즈 관심이 유니버스 중앙값 미만(목록에 없으면 0).
        # 기준선을 못 구했으면 판정 불가라 매집을 하지 않는다.
        crowd_absent = crowd_median is not None and attention.get(code, 0) < crowd_median
        av = zamt.get(code)
        is_accum = (NEAR_FLOOR <= near < NEAR_ACCUM_MAX and iv > INFO_ACCUM_MIN
                    and crowd_absent)
        is_break = (near >= NEAR_BREAK and iv > 0 and av is not None and av > 0)
        if not (is_accum or is_break):
            _fn(funnel, code, 'no_setup', near=near, info=iv,
                crowd_absent=crowd_absent, zamt=av)
            continue

        if code in portfolio:
            # 이미 매집 단계에 들어간 종목의 돌파 매수(피라미딩).
            # 목표 비중까지 남은 만큼만 채운다 — 별도 상태 없이 2단을 강제한다.
            if not is_break:
                _fn(funnel, code, 'held_awaiting_breakout')
                continue
            cost = portfolio[code].get('quantity', 0) * portfolio[code].get('avg_price', 0)
            room = full - cost
            if room < half * 0.5:
                _fn(funnel, code, 'no_room', room=room)
                continue
            qty = int(room / price)
            label = "돌파 추가매수"
        else:
            if held >= MAX_HOLDINGS:
                _fn(funnel, code, 'max_holdings', held=held)
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
    def __init__(self, initial_cash=DEFAULT_INITIAL_CASH):
        super().__init__("Accumulation", initial_cash)

    def get_universe(self):
        """외인·기관 순매수 상위 30 (FHPTJ04400000).

        버즈 유니버스로는 앵커 종목이 안 나온다 — 2026-07-29 실측 28종목 중
        52주 고점 85% 이상이 0개(최고 0.714)였다. 심8의 가설이 '정보거래자가
        먼저 산다'이므로 그 집단을 직접 본다. 순매수 상위 응답이 이미
        frgn/orgn_fake_ntby_qty·price·amount를 담고 있어 info 축 재료가 그대로
        따라오고, w52·foreign_change는 _enrich_universe가 채운다.
        """
        try:
            from src.trade.kis_data_provider import KISDataProvider
            return KISDataProvider().get_foreign_institution_rank(
                market='0001', etc_cls='0', limit=30)
        except Exception:
            return None

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        view = self._view(current_prices)
        # 군중축의 기준선은 후보 안에 없다 — 유니버스가 외인·기관 순매수 상위라
        # unique_posters가 애초에 붙지 않는다. 버즈 유니버스에서 따로 읽어 온다.
        view['buzz_attention'], view['buzz_median'] = crowd_reference(self.data_dir)
        funnel = []
        orders = decide_accumulation(view, candidates, current_prices, funnel=funnel)
        # 심8은 max_holdings에서 `continue`라 뒤 후보도 끝까지 본다. break 심과
        # 같이 취급해 미설명 경고를 끄면, 포트폴리오가 찬 날마다 게이트가 가장
        # 많은 심에서 감시가 통째로 사라진다.
        log_funnel('선행매집', candidates, funnel, orders, early_exit_breaks=False)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
