from datetime import datetime

from .base_simulator import BaseSimulator, get_kst_now

_cooldown_active = BaseSimulator.cooldown_active

MAX_HOLDINGS = 5
POSITION_WEIGHT = 0.19  # 종목당 NAV 대비 비중 (0.19 × 5 = 최대 95% 투입, 전 심 통일)

# 갭소진 파라미터 (2026-06~07 42거래일, 체결 가능한 정보만으로 재측정해 확정)
# 최초 스펙(갭 3 / 되밀림 -3 / 필터 없음)은 거래당 +1.50%·승률 45.7%였고,
# 수익이 익일 상한가 5건에 전부 걸려 있었다(상위 5건 제외 시 -0.02%).
# 아래 3개 조건은 6월·7월 양쪽에서 같은 방향으로 개선됐고, 상위 5건을 빼도 +1.19%다.
GAP_MIN = 7.0            # 갭(시가/전일종가) 하한 %
INTRA_MAX = -6.0         # 장중(현재가/시가) 되밀림 상한 %
RANGE_POS_MAX = 0.20     # 진입가의 일중 위치 (0=당일 저가, 1=당일 고가)
ENTRY_AFTER_MIN = 14 * 60 + 30  # 14:30 이후에만 진입 (되밀림 확정 전 진입 금지)
ENTRY_BEFORE_MIN = 15 * 60 + 20  # 15:20 동시호가 시작 = 체결 가능 한계
STOP_PCT = -3.0          # 익일 손절
# 고정 익절 없음: 동일 표본(n=136) 검증에서 +3% 익절이 평균 +2.83%→-1.35%로 알파를
# 파괴했다. 승자를 3%에서 자르는 동안 패자는 종가까지 흐른다. 손절만 남기면 +5.14%.
MIN_AMOUNT = 1_000_000_000



def _skip(funnel, code, reason, **vals):
    """왜 안 샀는지를 한 줄 남긴다.

    2026-08-13 감사: 이 심은 배포 이래 매수가 **0건**인데, 로그에는 아무것도
    남지 않아 "신호가 없는 날"과 "구조적으로 못 사는 심"이 구분되지 않았다.
    유니버스(상승률 상위 50)와 진입 조건(갭 +7% 후 되밀림 -6% → 당일 등락률
    +0.6% 이하)이 서로 밀어내는 관계라는 의심이 있는데, 확정하려면 게이트별
    탈락 분포가 필요하다. 추측 대신 세어 본다.
    """
    if funnel is None:
        return
    funnel.append({'code': code, 'reason': reason, **vals})

def _minutes(now):
    return now.hour * 60 + now.minute


def _held_days(entry_str, today):
    """진입일로부터 경과한 달력 일수. 파싱 불가면 None."""
    if not entry_str:
        return None
    try:
        return (today - datetime.strptime(entry_str, '%Y-%m-%d').date()).days
    except ValueError:
        return None


def decide_gap_fade(view, candidates, current_prices, now=None, funnel=None):
    """[Sim9] 갭소진 반등 결정. 순수 함수. Order 리스트 반환.

    now를 주입받는 이유: 진입/청산이 모두 시각 게이트에 걸려 있어 테스트가
    시계에 의존하면 안 된다.
    """
    now = now or get_kst_now()
    mins = _minutes(now)
    today = now.date()
    orders = []
    portfolio = view['portfolio']
    sold = set()

    # 1. 청산 — 진입 당일은 손대지 않는다. 오버나이트 보유가 전략의 본체다.
    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        if cur <= 0:
            continue
        avg = p.get('avg_price', 0)
        if avg <= 0:
            continue
        days = _held_days(p.get('entry_date'), today)
        if days == 0:
            continue
        pr = (cur - avg) / avg * 100

        # entry_date를 못 읽으면(상태 손상) 1일 타임스탑을 보장할 수 없다.
        # 역추세 1일 전략에서 눌러앉은 포지션이 가장 위험하므로 즉시 청산한다.
        if days is None:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[갭소진] 진입일 불명 → 즉시 청산 ({pr:+.1f}%)",
                           'cooldown': None, 'mark_partial': False})
            sold.add(code); continue

        if pr <= STOP_PCT:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[갭소진] 손절 ({pr:+.1f}%)",
                           'cooldown': 2, 'mark_partial': False})
            sold.add(code); continue

        # 타임스탑 1일: 익일 장 막바지 청산. +5일까지 끌면 수익이 무너진다(실측 -0.39%).
        # 2일 이상 남아 있으면(휴장·데이터 누락으로 청산 창을 놓친 경우) 시각 불문 청산.
        if days >= 2 or ENTRY_AFTER_MIN <= mins < ENTRY_BEFORE_MIN:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[갭소진] 타임스탑 청산 ({days}일, {pr:+.1f}%)",
                           'cooldown': None, 'mark_partial': False})
            sold.add(code); continue

    # 2. 진입 — 갭 상승 후 장중 되밀림. 되밀림이 확정된 장 막바지에만 산다.
    # 시장 지수 게이트를 걸지 않는다: 하루짜리 역추세이고, 실측도 지수 조건 없이 나왔다.
    # 상한 15:20: 동시호가가 시작되면 이 가격으로 체결할 수 없다. 15:33 런에서 사는
    # 백테스트는 체결 불가능한 거래를 세는 것이라 상한이 없으면 결과가 거짓이 된다.
    if not (ENTRY_AFTER_MIN <= mins < ENTRY_BEFORE_MIN):
        return orders

    target_amount = view['nav'] * POSITION_WEIGHT
    held = len(portfolio) - len(sold)
    for stock in candidates:
        if held >= MAX_HOLDINGS:
            break
        code = stock.get('code')
        if not code or code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            _skip(funnel, code, 'held_or_cooldown')
            continue
        price = float(stock.get('price', 0))
        open_px = float(stock.get('open_price', 0))
        prev_cl = float(stock.get('prev_close', 0))
        amount = float(stock.get('amount', 0))
        if price <= 0 or open_px <= 0 or prev_cl <= 0:
            _skip(funnel, code, 'no_ohlc')
            continue
        if amount < MIN_AMOUNT:
            _skip(funnel, code, 'amount')
            continue

        gap = (open_px / prev_cl - 1) * 100
        intra = (price / open_px - 1) * 100
        if gap < GAP_MIN:
            _skip(funnel, code, 'gap', gap=gap, intra=intra)
            continue
        if intra > INTRA_MAX:
            _skip(funnel, code, 'intra', gap=gap, intra=intra)
            continue

        # 일중 위치: 되밀림이 '끝난' 종목과 '중간에 걸친' 종목을 가른다.
        # 저가 근처에서 마감한 것만 다음날 되돌아온다. 일중 위치 0.4~0.6 구간은
        # 실측 평균 -11.5%로 전 구간 최악이었다(6월·7월 모두 음수).
        # 고가/저가가 없으면 판단할 수 없다 — 없는 근거로 사지 않는다(fail-closed).
        hi = float(stock.get('day_high', 0) or 0)
        lo = float(stock.get('day_low', 0) or 0)
        if hi <= 0 or lo <= 0 or hi <= lo:
            _skip(funnel, code, 'no_hilo', gap=gap, intra=intra)
            continue
        pos = (price - lo) / (hi - lo)
        if pos > RANGE_POS_MAX:
            _skip(funnel, code, 'range_pos', gap=gap, intra=intra, pos=pos)
        if pos <= RANGE_POS_MAX:
            qty = int(target_amount / price)
            if qty > 0:
                orders.append({'action': 'BUY', 'code': code, 'name': stock.get('name', code),
                               'price': price, 'quantity': qty, 'cooldown': None,
                               'reason': f"[갭소진] 저가권 되밀림 매수 "
                                         f"(갭 {gap:+.1f}%, 장중 {intra:+.1f}%, "
                                         f"일중위치 {(price - lo) / (hi - lo):.2f})"})
                held += 1
    return orders


class GapFadeSimulator(BaseSimulator):
    """
    [Sim 9] 갭소진 반등 (Gap-Fade Rebound)
    - 가설: 급등주는 갭으로 오르고 장중에 되밀린다. 되밀림이 과도할수록 다음날 되돌아온다.
      레퍼런스: Lou, Polk & Skouras (2019, JFE) "A Tug of War: Overnight vs Intraday".
    - 진입: 14:30~15:20 & 거래대금>=10억 & 갭>=+7% & 장중<=-6% & 일중위치<=0.20.
            시각 게이트가 핵심 — 되밀림 확정 전에 사면 더 밀린다.
    - 청산: -3% 손절 / 익일 14:30~15:20 무조건 청산(타임스탑 1일). 고정 익절 없음.
            +5일까지 끌면 수익이 무너지므로 1일을 넘기지 않는다.
    - 데이터: open_price / day_high / day_low (전부 inquire-price 한 응답). 추가 콜 0.
    - ⚠ 실전 미승격(tradeable: false). 설계 근거였던 +2.98%는 '종가로 신호를 정의하고
      종가에 산다'는 룩어헤드였다. 체결 가능한 정보로 재측정한 뒤 위 조건을 얹어
      거래당 +4.32%·월 24건까지 올렸으나 승률 50%로 게이트(55%) 미달이다.
      이 전략은 우측 꼬리(익일 상한가)로 버는 구조라 승률 게이트와 구조적으로 충돌한다.
    - ⚠ 일중위치 임계 0.20은 스냅샷 근사 고가/저가로 정해졌다. 실제 고가/저가가
      쌓이면(2026-07-28 배선) 재검증해야 한다 — 시가와 같은 처지다.
    - **신호 빈도 실측 (2026-07-30, ohlcv_top100.csv 100거래일 · 9,900 종목-일):**
      거래대금 10억+ 9,897 → 갭 +7%+ 174 → 장중 -6%- 29 → 일중위치 0.20- **18건**.
      즉 종목-일의 0.18%다. 월 환산 3.8건이고, 위에 적힌 '월 24건'은 다른(더 넓은)
      유니버스에서 나온 숫자다 — top100 기준으로는 그보다 훨씬 드물다.
    - ⚠ 2026-08-05까지는 버즈(게시글) 유니버스(런당 16~24개, 45개로 추정했던 것의
      절반 이하)에 얹혀 있었다. 실측 기대 신호 ≈ 12거래일에 1건이라던 계산 자체가
      틀린 전제였다 — 실제로는 그보다 3배 가까이 드물었을 것이다. 그 상태로 배포
      이후(07-28~08-05, 실거래 약 6일) 매매 0건이었던 것은 통계적으로는 설명 가능한
      범위였지만, 이 페이스로는 검증 자체가 불가능해 get_universe()를 KIS 상승률
      상위(자체 유니버스)로 옮겼다(위 get_universe() 참고). 진입 창(14:30~15:20)에
      스크래퍼가 10분마다 도는 것은 확인됐다.
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("GapFade", initial_cash)

    def get_universe(self):
        """당일 등락률 상위(코스피, FHPST01700000)로 자체 유니버스를 쓴다.

        진입 신호(open_price/day_high/day_low/prev_close)는 버즈(게시글) 텍스트를
        전혀 쓰지 않는데도 버즈 후보 풀에 얹혀 있었다. 그 풀은 런당 16~24개뿐이라
        (2026-08-05 실측) 아래 '12거래일에 1건' 추정이 전제한 45개보다 훨씬 작아
        실제 기대 대기가 3배 가까이 늘어난다 — Sim2/3/4/6과 같은 이유로 KIS 자체
        유니버스로 옮긴다. 갭+7% 후 장중 -6% 되밀려도 전일 종가 대비로는 대개
        +5%대라 상승률 상위에 남으므로 limit을 넉넉히 잡는다.
        """
        try:
            from src.trade.kis_data_provider import KISDataProvider
            return KISDataProvider().get_fluctuation_rank(market='0001', sort='0', limit=50)
        except Exception:
            return None

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        funnel = []
        orders = decide_gap_fade(self._view(current_prices), candidates, current_prices,
                                 funnel=funnel)
        self._log_funnel(candidates, funnel, orders)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)

    @staticmethod
    def _log_funnel(candidates, funnel, orders) -> None:
        """게이트별 탈락 분포를 한 줄로 남긴다.

        이 심은 배포 이래 매수가 0건인데 로그에 아무것도 없어서, "신호가 없는
        날"과 "구조적으로 못 사는 심"이 구분되지 않았다. 의심은 유니버스
        (KOSPI 상승률 상위 50)와 진입 조건이 서로 밀어낸다는 것이다 — 갭 +7%
        후 되밀림 -6%면 당일 등락률이 +0.6% 이하라 상승률 상위에 남기 어렵다.
        추측으로 유니버스를 바꾸지 않고 먼저 센다.

        `gap` 탈락이 후보 전량이면 유니버스 문제가 확정된다. gap을 통과하는
        종목이 매일 몇 개씩 나오는데 뒤 게이트에서 죽으면 원인은 다른 데 있다.

        진단이 심을 죽이면 안 된다 — 통째로 삼킨다.
        """
        try:
            from collections import Counter
            if not funnel and not orders:
                return
            # 파일로도 남긴다. print는 Actions 로그에만 남아 며칠 뒤엔 못 찾는다 —
            # 심1이 `sim1_diag_*.csv`로 남기는 것과 같은 이유다(2026-08-17).
            # 이 심은 진입 창이 14:30~15:20뿐이라 "그 창에 후보가 조건에 닿았는가"를
            # 사후에 확인할 방법이 이것밖에 없다.
            try:
                from src.data import sim_diag
                sim_diag.append('sim9', [dict(f, decision='skip') for f in funnel]
                                + [dict(code=o.get('code'), reason='entry', decision='entry')
                                   for o in orders], log=lambda *_: None)
            except Exception:
                pass
            c = Counter(f['reason'] for f in funnel)
            passed_gap = [f for f in funnel if f['reason'] not in ('held_or_cooldown',
                                                                  'no_ohlc', 'amount', 'gap')]
            parts = ', '.join(f'{k} {v}' for k, v in c.most_common())
            print(f"[Sim9 깔때기] 후보 {len(candidates)} → 매수 {len(orders)} | 탈락: {parts}")
            for f in passed_gap[:5]:
                print(f"   갭통과 {f['code']}: gap={f.get('gap', 0):+.1f}% "
                      f"intra={f.get('intra', 0):+.1f}% 탈락={f['reason']}")
        except Exception as e:
            print(f'[Sim9 깔때기] 기록 실패(무시): {e}')
