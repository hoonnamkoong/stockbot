"""US Sim2 — 돈치안 채널 돌파(터틀), 국내 Sim9-1의 미국 이식.

판단 로직(20일 채널 상단 돌파 진입, 10일 채널 이탈/2*ATR 손절 청산, 거래대금
교차단면 z-score)은 국내 Sim9-1(sim9_1_donchian.py)과 동일하다 — 통화·데이터
소스만 다르다.

EOD 배치(scripts/run_eod_sim_us.py)가 채널 상단·하단·ATR을 하루 1회 계산해
워치리스트에 남기고, 실제 매수/매도는 장중 루프(scripts/us_trade_loop.py)가
실시간에 가까운 가격으로 판단한다(US Sim1과 동일한 program-trading-parity 원칙).

미너비니(US Sim1)와 달리 EOD 단계의 후보 필터가 "20일치 종가 이력"뿐이라 그대로
두면 유니버스 전체가 워치리스트에 들어간다. 장중 루프는 워치리스트 종목마다
5분 간격으로 야후 실시간가를 개별 호출하므로, 워치리스트가 크면 한 사이클에
호출이 수백 건이 되어 타임아웃·야후 429 차단 리스크가 커진다. 그래서 EOD
단계에서 평균거래대금 문턱(MIN_AMOUNT)을 미리 걸어 워치리스트를 좁힌다 — 국내
원본의 "거래대금 동반" 의도와도 맞는다. 장중 진입 시점의 거래대금 z-score는
당일 실시간 값이라 EOD에서 대체 불가능해 그대로 런타임에 남긴다.

**MIN_AMOUNT만으로는 부족했다(2026-08-26).** 유니버스 조회가 복구되고 처음
실제로 돌려보니 998종목 중 930종목이 문턱을 통과했다 — 시총 상위 1000 종목에
일 거래대금 $10M은 사실상 아무 제약이 아니다. 그래서 거래대금 상위
MAX_WATCHLIST개로 한 번 더 자른다(위에서 우려한 타임아웃이 실제 값이 되었다).
"""
import json
import os

from .us_base_simulator import USBaseSimulator
from .us_calendar import us_trading_date
from .base_simulator import BaseSimulator

_cooldown_active = BaseSimulator.cooldown_active

MAX_HOLDINGS = 5
POSITION_WEIGHT = 0.19   # US Sim1과 동일 비중

CHANNEL_DAYS = 20        # 진입 채널 (원 터틀 System 1) — 국내 Sim9-1과 동일
EXIT_DAYS = 10           # 청산 채널
ATR_STOP_MULT = 2.0      # 손절 = 진입가 - 2*ATR
MIN_SAMPLE = 10          # 거래대금 횡단면 z 최소 표본. 미달이면 신호 없음(fail-closed)
MIN_AMOUNT = 10_000_000  # 미국 대형주 유동성 기준 일일 거래대금 최소 문턱(USD) — US Sim1과 동일

# 워치리스트 상한(거래대금 상위 N). 장중 루프의 잡 타임아웃에서 역산한 값이다:
#   러너 실측 0.26초/종목(2026-08-26 EOD 런: 998종목 406초 중 슬립 150초 제외)
#   잡 타임아웃 240초 - 오버헤드 40초(체크아웃·pip) = 가용 200초
#   안전마진 50% → 조회 예산 100초 → 총 385종목
#   run_cycle은 심마다 따로 조회한다(심 간 중복 제거 없음) — US Sim1 ~18 +
#   US Sim3 20 + 보유 ~15 = 55를 빼면 이 심 몫이 약 330. 내려서 300.
# 신호 필터가 아니라 유동성·호출예산 제약이다. 순서도 그래서 중요하다 —
# 돌파 셋업 판정을 먼저 하고, 통과한 것 중에서 가장 유동적인 300을 남긴다.
MAX_WATCHLIST = 300

WATCHLIST_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'data',
    'sim_us2_donchian_watchlist.json')


def _clean(closes):
    return [c for c in (closes or []) if c and c > 0]


def _zmap(pairs):
    """[(code, value)] → {code: z}. 표본 부족·분산 0이면 빈 dict(=신호 없음)."""
    vals = [v for _, v in pairs]
    n = len(vals)
    if n < MIN_SAMPLE:
        return {}
    mu = sum(vals) / n
    sd = (sum((v - mu) ** 2 for v in vals) / n) ** 0.5
    if sd <= 0:
        return {}
    return {c: (v - mu) / sd for c, v in pairs}


def _surge_pairs(candidates):
    """[(code, 당일거래대금 / 그 종목의 평균거래대금)] — '거래대금 급증' 배수.

    2026-08-26까지는 절대 거래대금을 그대로 횡단면 z에 넣었다. 그런데 당일
    거래대금 분포는 초대형주가 평균을 끌어올려 심하게 치우친다(그날 후보 300종목
    실측: 평균 $469M / 중앙값 $164M / 최대 $12,310M). z>0을 통과하는 건 상위
    18%뿐이라, 게이트 이름은 "거래대금 동반(급증)"인데 실제로는 "다른 종목보다
    큰가" = 초대형주 필터로 동작했다. 그날 20일 채널을 돌파한 16종목이 **전부**
    이 게이트에서 막혔다(z가 -0.09 ~ -0.38로 전부 음수).

    자기 평균 대비 배수로 바꾸면 종목 크기가 상쇄되고 '평소보다 얼마나 많이
    도는가'만 남는다. 이 배수를 다시 횡단면 z로 만드는 이유는 장중 경과시간
    때문이다 — amount는 당일 누적이라 개장 2시간이면 정상 종목도 배수가 0.3대다.
    모든 후보가 같은 경과시간을 공유하므로 횡단면 z를 취하면 그 효과가 상쇄된다.

    평균거래대금을 모르는 종목은 **뺀다**. 0으로 두면 0으로 나누거나 '측정 불가'가
    '급증 없음'으로 둔갑한다(US Sim3 build_watchlist와 같은 관례).
    """
    out = []
    for s in candidates:
        code = s.get('code')
        base = s.get('avg_dollar_volume')
        if not code or base is None or float(base) <= 0:
            continue
        out.append((code, float(s.get('amount', 0) or 0) / float(base)))
    return out


def _atr(hist):
    """종가 간 절대변동의 평균(근사 ATR). 국내 Sim9-1과 동일 근사식 — 고가/저가
    없이 종가만으로 계산하므로 갭을 못 보고 실제보다 작게 나온다(손절이 타이트해진다)."""
    if len(hist) < 2:
        return 0.0
    diffs = [abs(hist[i] - hist[i - 1]) for i in range(1, len(hist))]
    return sum(diffs) / len(diffs)


def build_watchlist_entry(name: str, daily_closes: list[float], avg_dollar_volume: float) -> dict | None:
    """name: 종목명. daily_closes: 오늘 미포함 종가 이력(과거→최근 순).
    avg_dollar_volume: 최근 거래대금 평균(USD). 자격 미달이면 None."""
    hist = _clean(daily_closes)
    if len(hist) < CHANNEL_DAYS:
        return None
    if avg_dollar_volume < MIN_AMOUNT:
        return None
    window = hist[-CHANNEL_DAYS:]
    return {
        'name': name,
        'channel_high': max(window),
        'channel_low': min(hist[-EXIT_DAYS:]),
        'atr': _atr(window),
        'avg_dollar_volume': avg_dollar_volume,
    }


def cap_watchlist(entries: dict[str, dict]) -> dict[str, dict]:
    """거래대금 상위 MAX_WATCHLIST개만 남긴다. 상한 이하면 그대로 돌려준다.

    거래대금을 모르는(None) 종목은 0으로 취급해 '최하위'로 줄 세우지 않고 뺀다 —
    측정 실패를 최하위로 두면 조회에 실패한 종목이 조용히 밀려나기만 하고 실패
    사실 자체가 사라진다(US Sim3의 build_watchlist와 같은 관례)."""
    measured = {k: v for k, v in entries.items()
                if v.get('avg_dollar_volume') is not None}
    if len(measured) <= MAX_WATCHLIST:
        return measured
    top = sorted(measured.items(),
                 key=lambda kv: -float(kv[1]['avg_dollar_volume']))[:MAX_WATCHLIST]
    return dict(top)


def save_watchlist(entries: dict[str, dict], date_str: str) -> None:
    os.makedirs(os.path.dirname(WATCHLIST_PATH), exist_ok=True)
    with open(WATCHLIST_PATH, 'w', encoding='utf-8') as f:
        json.dump({'date': date_str, 'entries': entries}, f, ensure_ascii=False)


def load_watchlist(date_str: str) -> dict[str, dict]:
    """오늘 날짜와 일치할 때만 돌려준다(fail-closed) — US Sim1과 동일 관례."""
    try:
        with open(WATCHLIST_PATH, encoding='utf-8-sig') as f:
            data = json.load(f)
    except Exception:
        return {}
    if not isinstance(data, dict) or data.get('date') != date_str:
        return {}
    entries = data.get('entries')
    return entries if isinstance(entries, dict) else {}


def decide_us_donchian(view, candidates, current_prices):
    """[US Sim2] 돈치안 채널 돌파 결정. 순수 함수. Order 리스트 반환.

    국내 decide_donchian과 동일 구조 — range_history(원시 종가 배열) 대신
    워치리스트에 미리 계산된 channel_high/channel_low/atr을 읽는다.

    유동성 문턱(MIN_AMOUNT)은 실시간 amount가 아니라 워치리스트의
    avg_dollar_volume(EOD 배치가 계산한 최근 평균거래대금)으로 판정한다 — 실시간
    amount는 당일 누적 거래량 기준이라 개장 직후 몇 시간은 채널 돌파가 스퓨리어스
    하게 막힌다(2026-08-24 리뷰에서 발견). 거래대금 z-score(zamt)는 당일 실시간
    급증을 보는 지표라 그대로 실시간 amount를 쓰되, **자기 평균 대비 배수**로
    바꿔서 쓴다(_surge_pairs 참고)."""
    orders = []
    portfolio = view['portfolio']
    sold = set()
    cand_by_code = {s.get('code'): s for s in candidates if s.get('code')}
    zamt = _zmap(_surge_pairs(candidates))

    # 1. 청산 — 10일 채널 이탈 또는 2*ATR 손절. 고정 익절 없음(터틀은 추세를 끝까지 탄다).
    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        avg = p.get('avg_price', 0)
        if cur <= 0 or avg <= 0:
            continue
        pr = (cur - avg) / avg * 100

        info = cand_by_code.get(code) or {}
        atr = info.get('atr')
        if atr is not None:
            stop = avg - ATR_STOP_MULT * atr
            if cur <= stop:
                orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                               'reason': f"[US돈치안] 2*ATR 손절 ({pr:+.1f}%)",
                               'cooldown': 3, 'mark_partial': False})
                sold.add(code); continue

        ch_lo = info.get('channel_low')
        if ch_lo is not None and cur < ch_lo:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[US돈치안] {EXIT_DAYS}일 채널 이탈 (${ch_lo:,.2f} 하회, {pr:+.1f}%)",
                           'cooldown': 1, 'mark_partial': False})
            sold.add(code); continue

    # 2. 진입 — 20일 채널 상단 돌파 + 거래대금 동반.
    target_amount = view['nav'] * POSITION_WEIGHT
    held = len([c for c in portfolio if c not in sold])
    for stock in candidates:
        if held >= MAX_HOLDINGS:
            break
        code = stock.get('code')
        if not code or code in portfolio or code in sold or _cooldown_active(view['cooldown_codes'], code):
            continue
        price = float(stock.get('price', 0) or 0)
        avg_dollar_volume = stock.get('avg_dollar_volume')
        ch_hi = stock.get('channel_high')
        if price <= 0 or ch_hi is None or avg_dollar_volume is None or avg_dollar_volume < MIN_AMOUNT:
            continue
        av = zamt.get(code)
        if av is None or av <= 0:
            continue

        if price > ch_hi:
            qty = int(target_amount / price)
            if qty > 0:
                orders.append({'action': 'BUY', 'code': code, 'name': stock.get('name', code),
                               'price': price, 'quantity': qty, 'cooldown': None,
                               'reason': f"[US돈치안] {CHANNEL_DAYS}일 채널 돌파 (${ch_hi:,.2f} 상회, 거래대금z {av:+.1f})"})
                held += 1
    return orders


class USDonchianSimulator(USBaseSimulator):
    """[US Sim2] 돈치안 채널 돌파 — 국내 Sim9-1 이식. 상세 배경은 위 모듈 docstring."""

    def __init__(self, initial_cash=20000):
        super().__init__("Us2Donchian", initial_cash)

    def get_universe(self):
        today = us_trading_date()
        entries = load_watchlist(today)
        return [
            {'code': code, 'name': e.get('name', code),
             'channel_high': e.get('channel_high'), 'channel_low': e.get('channel_low'),
             'atr': e.get('atr'), 'avg_dollar_volume': e.get('avg_dollar_volume')}
            for code, e in entries.items()
        ]

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)
        orders = decide_us_donchian(self._view(current_prices), candidates, current_prices)
        self._apply(orders, current_prices)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
