import statistics

from .. import regime_state as rs
from .base_simulator import BaseSimulator, get_kst_now


def calculate_kospi_trend(kospi_price, kospi_ma5):
    """KOSPI 추세 = (KOSPI / 5일MA - 1) * 100

    Returns: -100 ~ 100 범위로 클립된 추세값
    """
    if kospi_ma5 <= 0:
        return 0.0
    trend = ((kospi_price / kospi_ma5) - 1) * 100
    return min(100, max(-100, trend))


def normalize_foreigner_score(foreigner_buy_amount, historical_max=100000000000):
    """외국인 순매수액을 0~100으로 정규화

    Args:
        foreigner_buy_amount: 외국인 순매수액 (음수 허용)
        historical_max: 과거 최대값 기준 (학습 데이터에서 산출)

    Returns: 0 ~ 100 (0 = 최대 매도, 50 = 중립, 100 = 최대 매수)
    """
    normalized = (foreigner_buy_amount / historical_max) * 50 + 50
    return min(100, max(0, normalized))


def calculate_decline_ratio(declining_count, rising_count):
    """낙폭장 비율 = 낙폭종목 / (낙폭 + 상승) * 100

    Returns: 0 ~ 100 (0 = 모두 상승, 100 = 모두 낙폭)
    """
    total = declining_count + rising_count
    if total == 0:
        return 50.0
    ratio = (declining_count / total) * 100
    return ratio


def collect_signals(market_data, kospi_data, foreigner_data):
    """4개 입력 신호 수집

    Args:
        market_data: {'breadth': float (0-100), 'declining': int, 'rising': int}
        kospi_data: {'price': float, 'ma5': float}
        foreigner_data: {'buy_amount': float}

    Returns:
        {'breadth': float, 'kospi_trend': float, 'foreigner_score': float, 'decline_ratio': float}
    """
    breadth = market_data.get('breadth', 50.0)
    breadth = min(100, max(0, breadth))

    kospi_trend = calculate_kospi_trend(
        kospi_data.get('price', 0),
        kospi_data.get('ma5', 1)
    )

    foreigner_score = normalize_foreigner_score(
        foreigner_data.get('buy_amount', 0)
    )

    decline_ratio = calculate_decline_ratio(
        market_data.get('declining', 0),
        market_data.get('rising', 1)
    )

    return {
        'breadth': breadth,
        'kospi_trend': kospi_trend,
        'foreigner_score': foreigner_score,
        'decline_ratio': decline_ratio
    }


def ensemble_breadth(signals):
    """4개 신호의 가중평균으로 최종 국면 강도 점수 생성

    final_breadth = 0.5 * breadth + 0.2 * kospi_trend_normalized + 0.2 * foreigner_score + 0.1 * decline_ratio

    Args:
        signals: {'breadth': float (0-100), 'kospi_trend': float (-100~100),
                  'foreigner_score': float (0-100), 'decline_ratio': float (0-100)}

    Returns:
        float (0~100): 최종 breadth 점수
    """
    breadth = signals.get('breadth', 50)
    kospi_trend = signals.get('kospi_trend', 0)
    foreigner_score = signals.get('foreigner_score', 50)
    decline_ratio = signals.get('decline_ratio', 50)

    # kospi_trend를 -100~100에서 0~100으로 정규화
    kospi_normalized = (kospi_trend + 100) / 2
    kospi_normalized = min(100, max(0, kospi_normalized))

    final = (
        0.5 * breadth +
        0.2 * kospi_normalized +
        0.2 * foreigner_score +
        0.1 * decline_ratio
    )

    return min(100, max(0, final))


def score_saturation(final_breadth):
    """예측이 극단값인가 (포화 감지)

    Returns: float (0.0 ~ 1.0)
    - 포화(0~0.1 또는 0.9~1.0 정규화 후): 0.2
    - 극단값(0.1~0.2 또는 0.8~0.9): 0.5
    - 정상 범위(0.2~0.8): 0.9
    """
    normalized = final_breadth / 100.0

    if normalized < 0.1 or normalized > 0.9:
        return 0.2
    elif (0.1 <= normalized <= 0.2) or (0.8 <= normalized <= 0.9):
        return 0.5
    else:
        return 0.9


def score_volatility(recent_logs):
    """최근 3시간 예측 진동 (표준편차)

    Args:
        recent_logs: list of {'breadth': float} (최근 3시간)

    Returns: float (0.0 ~ 1.0)
    - 표준편차 > 25: 0.3 (높은 진동)
    - 표준편차 15~25: 0.6 (중간)
    - 표준편차 < 15: 0.9 (낮은 진동)
    """
    if len(recent_logs) < 2:
        return 0.9  # 데이터 부족하면 안정적으로 판단

    breadths = [log.get('breadth', 50) for log in recent_logs]
    std = statistics.stdev(breadths)

    if std > 25:
        return 0.3
    elif std >= 15:
        return 0.6
    else:
        return 0.9


def score_input_agreement(signals):
    """4개 신호 일치도 (방향 일치)

    Args:
        signals: {'breadth': float, 'kospi_trend': float, 'foreigner_score': float, 'decline_ratio': float}

    Returns: float (0.0 ~ 1.0)
    - 모두 상승/하락 방향 (모두 >= 50 또는 모두 < 50): 0.9
    - 3개 일치: 0.7
    - 2개 이하: 0.5
    """
    breadth = signals.get('breadth', 50)
    kospi_trend = signals.get('kospi_trend', 0)
    foreigner_score = signals.get('foreigner_score', 50)
    decline_ratio = signals.get('decline_ratio', 50)

    # 상승 신호 카운트 (50 이상은 상승 신호)
    bullish = sum([
        breadth >= 50,
        kospi_trend >= 0,  # kospi_trend는 -100~100 범위에서 0 기준
        foreigner_score >= 50,
        decline_ratio < 50  # 낙폭 < 50 = 상승 신호
    ])

    if bullish == 4 or bullish == 0:  # 모두 일치
        return 0.9
    elif bullish == 3 or bullish == 1:  # 3개 일치
        return 0.7
    else:  # 2개씩 갈림
        return 0.5


def score_timeframe(current_hour):
    """시간 경과에 따른 안정도

    Args:
        current_hour: str ("09:00", "10:00", ... "15:00")

    Returns: float (0.0 ~ 1.0)
    - 09:00: 0.5 (아침, 불안정)
    - 10:00~14:00: 선형 증가
    - 15:00: 0.9 (장 종료, 안정)
    """
    hour_map = {
        '09:00': 0.5,
        '10:00': 0.6,
        '11:00': 0.7,
        '12:00': 0.7,
        '13:00': 0.8,
        '14:00': 0.85,
        '15:00': 0.9,
    }
    return hour_map.get(current_hour, 0.7)


def calculate_confidence(final_breadth, recent_logs, current_hour, signals):
    """신뢰도 계산 (포화 최우선)

    confidence = saturation * (0.6 + 0.2*volatility + 0.1*input_agreement + 0.1*timeframe)

    Args:
        final_breadth: float (0~100)
        recent_logs: list of {'breadth': float}
        current_hour: str
        signals: dict with 4 keys

    Returns: float (0.0 ~ 1.0)
    """
    sat = score_saturation(final_breadth)
    vol = score_volatility(recent_logs)
    agreement = score_input_agreement(signals)
    timeframe = score_timeframe(current_hour)

    confidence = sat * (0.6 + 0.2 * vol + 0.1 * agreement + 0.1 * timeframe)

    return min(1.0, max(0.0, confidence))


def _median(xs):
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    m = n // 2
    return float(s[m]) if n % 2 else (s[m - 1] + s[m]) / 2.0


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _pstdev(xs):
    if len(xs) < 2:
        return 0.0
    mu = _mean(xs)
    return (sum((x - mu) ** 2 for x in xs) / len(xs)) ** 0.5


def classify_by_score(bull_score, theta_bull, theta_bear):
    """bull_score(0~100)를 3상태 국면으로 매핑. AND게이트 대체.
    경계값은 각각 BULL/BEAR에 포함(>=, <=)."""
    if bull_score >= theta_bull:
        return "BULL"
    if bull_score <= theta_bear:
        return "BEAR"
    return "SIDEWAYS"


# ──────────────────────────────────────────────────
# 6단계 국면(권장안 R) — 정본. current_regime(3단계)은 여기서 파생된다.
# 설계서: docs/superpowers/specs/2026-09-29-libero-regime6-design.md §4
# 상수는 표본 내(2023-06~2025-06)에서 정하고 동결한 값이다. 바꾸면 설계서의
# 평가(§5)가 더는 이 코드를 설명하지 않는다.
# ──────────────────────────────────────────────────
R6_LOOKBACK_ROWS = 21      # 종가 행 수(20일선 + 여유 1행). 미만이면 판정 불가
R6_AB_WIN = 20             # ab20: 20일선(오늘 포함 20행) 위 종목 비율
R6_RET_WIN = 10            # ret10: 균등지수 10일 수익률
R6_RET_SCALE = 0.06        # ret10 정규화(±6%에서 포화)
R6_VOL_WIN = 10            # vol10: 균등지수 일간수익 10일 표본표준편차(%)
R6_VOL_HI = 0.98           # 횡보에서 vol10 > 0.98이면 강한횡보
R6_D_CUTS = (-0.90, -0.40, 0.40, 0.90)   # 방향 5단계 대칭 문턱
R6_BAND = 0.05             # 히스테리시스 폭
R6_CONFIRM_DAYS = 2        # 같은 이동 후보가 2일 연속이면 확정
R6_MIN_SAMPLE = 80         # 종목 표본 하한(라이브 top100 가드와 같은 값)
R6_INTRADAY_FROM = '10:00'  # 이 시각 전에는 전일 확정값 유지(설계서 §4.4·§5.5)
# CSV 마지막 행이 '전일 종가'인지 확인하는 허용오차. 네이버 등락률로 되돌린
# 전일 종가와 CSV 값의 상대 차이. 표본의 80% 이상이 맞아야 붙인다.
R6_PREV_CLOSE_TOL = 0.005
R6_PREV_CLOSE_MIN_RATIO = 0.8

_R6_LABEL_BY_LEVEL = {-2: rs.STRONG_BEAR, -1: rs.BEAR, 1: rs.BULL, 2: rs.STRONG_BULL}


def load_top100_closes(path):
    """종가 wide CSV(`date,005930_삼성전자,...` / 행 `YYYYMMDD,가격,...`) → dict.

    반환: {'dates': ['YYYY-MM-DD'], 'codes': ['005930', ...], 'rows': [[float|None]]}
    읽지 못하면 None. 빈 칸·숫자 아님은 None 칸이다(0으로 채우지 않는다).
    """
    import csv as _csv
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            lines = list(_csv.reader(f))
    except Exception:
        return None
    if len(lines) < 2:
        return None
    header = lines[0]
    ncol = len(header) - 1
    codes = [h.split('_', 1)[0].strip() for h in header[1:]]
    dates, rows = [], []
    for r in lines[1:]:
        if not r or len(r[0].strip()) != 8:
            continue
        d = r[0].strip()
        row = []
        for j in range(ncol):
            v = r[j + 1].strip() if j + 1 < len(r) else ''
            try:
                x = float(v)
                row.append(x if x > 0 else None)
            except ValueError:
                row.append(None)
        dates.append(f'{d[:4]}-{d[4:6]}-{d[6:]}')
        rows.append(row)
    return {'dates': dates, 'codes': codes, 'rows': rows}


def regime6_metrics(rows):
    """종가 행렬(마지막 행 = 판정일 t, 장중이면 현재가) → (지표 dict, None) 또는 (None, 사유).

    ab20  = 100 × #{P_t > SMA20} / #{SMA20 계산 가능}
    ret10 = 균등지수 10일 수익률, vol10 = 균등지수 일간수익 10일 표본표준편차(%)
    D     = 0.5·(ab20−50)/25 + 0.5·clip(ret10/0.06, −1, 1)
    """
    if len(rows) < R6_LOOKBACK_ROWS:
        return None, f'close_csv rows<{R6_LOOKBACK_ROWS} ({len(rows)})'
    rows = rows[-R6_LOOKBACK_ROWS:]
    n = len(rows[-1])

    ew = []
    for t in range(len(rows) - R6_VOL_WIN, len(rows)):
        prev, cur = rows[t - 1], rows[t]
        rets = [cur[i] / prev[i] - 1 for i in range(n)
                if prev[i] is not None and cur[i] is not None]
        if len(rets) < R6_MIN_SAMPLE:
            return None, f'return sample<{R6_MIN_SAMPLE} ({len(rets)})'
        ew.append(sum(rets) / len(rets))

    above = with_sma = 0
    for i in range(n):
        win = [r[i] for r in rows[-R6_AB_WIN:]]
        if any(x is None for x in win):
            continue
        with_sma += 1
        if win[-1] > sum(win) / len(win):
            above += 1
    if with_sma < R6_MIN_SAMPLE:
        return None, f'sma20 sample<{R6_MIN_SAMPLE} ({with_sma})'

    ab20 = 100.0 * above / with_sma
    level = 1.0
    for e in ew[-R6_RET_WIN:]:
        level *= 1 + e
    ret10 = level - 1
    vol10 = statistics.stdev(ew[-R6_VOL_WIN:]) * 100
    d = 0.5 * (ab20 - 50) / 25 + 0.5 * max(-1.0, min(1.0, ret10 / R6_RET_SCALE))
    return {'D': d, 'ab20': ab20, 'ret10': ret10, 'vol10': vol10}, None


def direction_level(d):
    """D → 방향 단계 −2..+2(대칭 문턱, 경계는 위 단계에 포함)."""
    level = -2
    for cut in R6_D_CUTS:
        if d >= cut:
            level += 1
    return level


def regime6_label(level, vol10):
    """방향 단계 + vol10 → 6단계 문자열. 횡보인데 vol10을 모르면 None."""
    if level is None:
        return None
    if level != 0:
        return _R6_LABEL_BY_LEVEL[level]
    if vol10 is None:
        return None
    return rs.STRONG_SIDEWAYS if vol10 > R6_VOL_HI else rs.WEAK_SIDEWAYS


def regime6_step(state, d, date):
    """하루치 판정을 확정 상태에 반영한다 → (새 상태, 원시 단계).

    state: {'level','candidate','candidate_days','confirmed_since'}.
    원시 단계가 확정 단계와 다르면 D를 확정 쪽으로 0.05 당겨 다시 본다. 그래도
    다를 때만 이동 후보이고, 같은 후보가 2일 연속이면 확정한다.
    d가 None(판정 불가일)이면 후보를 끊는다 — 증거 없이 국면을 바꾸지 않는다.
    (연구 라벨러는 결측일에 후보를 유지한다. 운영은 더 보수적인 쪽을 택했다.)
    """
    s = dict(state)
    if d is None:
        s['candidate'], s['candidate_days'] = None, 0
        return s, None
    raw = direction_level(d)
    cur = s['level']
    target = raw
    if raw != cur:
        target = direction_level(d - R6_BAND if raw > cur else d + R6_BAND)
    if target == cur:
        s['candidate'], s['candidate_days'] = None, 0
        return s, raw
    days = s['candidate_days'] + 1 if s.get('candidate') == target else 1
    if days >= R6_CONFIRM_DAYS:
        s.update(level=target, candidate=None, candidate_days=0, confirmed_since=date)
    else:
        s.update(candidate=target, candidate_days=days)
    return s, raw


def _live_row(closes, live):
    """장중 현재가 행을 만든다. CSV 마지막 행이 전일 종가가 아니면 (None, 사유).

    네이버 등락률로 전일 종가를 되돌려(현재가 / (1 + 등락률)) CSV 마지막 행과
    맞춰 본다. 달력 없이 'CSV가 낡았다'를 잡는 방법이다 — 낡은 행에 오늘 현재가를
    붙이면 이틀치 변화가 하루 수익으로 들어간다.
    """
    last = closes['rows'][-1]
    row, compared, matched = [], 0, 0
    for code, q in zip(closes['codes'], last):
        v = live.get(code) or {}
        p, rate = v.get('price'), v.get('change_rate')
        row.append(float(p) if p else None)
        if p and rate is not None and q:
            compared += 1
            implied_prev = float(p) / (1 + float(rate) / 100)
            if abs(implied_prev / q - 1) <= R6_PREV_CLOSE_TOL:
                matched += 1
    if compared < R6_MIN_SAMPLE:
        return None, f'live sample<{R6_MIN_SAMPLE} ({compared})'
    if matched < compared * R6_PREV_CLOSE_MIN_RATIO:
        return None, (f'csv last row({closes["dates"][-1]}) is not previous close '
                      f'({matched}/{compared} match)')
    return row, None


def advance_regime6(prev, closes, live, now):
    """6단계 국면을 한 런만큼 진행한다. 순수 함수(파일·네트워크 없음).

    prev:   직전 런이 남긴 상태({'base','today'}) 또는 None
            base  = 마지막으로 **끝난 날**까지 반영한 확정 상태(date 포함)
            today = 오늘 장중에 마지막으로 계산한 판정(다음 날 커밋용)
    closes: load_top100_closes() 결과 또는 None
    live:   {code: {'price','change_rate'}} 또는 None(수집 실패)
    now:    KST datetime

    확정 규칙은 일 단위다(설계서 §4.4). 오늘 장중 판정은 언제나
    `어제까지의 확정 상태 + 오늘 원시 단계`로 다시 계산한다 — 같은 날 여러 런이
    쌓여 후보 일수를 올리지 않는다. 지난 날은 CSV 종가로 커밋하고, CSV에 그날이
    없을 때만 그날 마지막 장중 판정을 쓴다.
    """
    today = now.strftime('%Y-%m-%d')
    hhmm = now.strftime('%H:%M')
    prev = prev or {}
    base = dict(prev['base']) if prev.get('base') else None
    stored = prev.get('today')
    reasons = []

    csv_ok = closes is not None and len(closes.get('rows') or []) >= R6_LOOKBACK_ROWS
    if closes is None:
        reasons.append('close_csv unreadable')
    elif not csv_ok:
        reasons.append(f'close_csv rows<{R6_LOOKBACK_ROWS} ({len(closes.get("rows") or [])})')

    def _commit(b, d, m):
        """d일의 판정 m(None=판정 불가)을 확정 상태 b에 반영."""
        if b is None:
            if m is None:
                return None
            lv = direction_level(m['D'])
            return {'date': d, 'level': lv, 'candidate': None, 'candidate_days': 0,
                    'confirmed_since': d, 'vol10': m['vol10'], 'metrics': m}
        nb, _ = regime6_step(b, None if m is None else m['D'], d)
        nb['date'] = d
        nb['vol10'] = b.get('vol10') if m is None else m['vol10']
        nb['metrics'] = m      # 판정 불가일이면 None — 그날 지표를 지어내지 않는다
        return nb

    # ① 끝난 날 커밋 — CSV 종가가 정본
    if csv_ok:
        for i, d in enumerate(closes['dates']):
            if d >= today or (base is not None and d <= base['date']):
                continue
            if i + 1 < R6_LOOKBACK_ROWS:
                continue
            m, _ = regime6_metrics(closes['rows'][i + 1 - R6_LOOKBACK_ROWS:i + 1])
            if base is None and m is None:
                continue
            base = _commit(base, d, m)
    if (stored and base is not None and base['date'] < stored['date'] < today):
        base = _commit(base, stored['date'], stored.get('metrics'))

    # ② 오늘 판정
    m_today, source = None, None
    if csv_ok and closes['dates'][-1] == today:
        m_today, why = regime6_metrics(closes['rows'])
        source = 'close_csv'
        if why:
            reasons.append(why)
    elif hhmm < R6_INTRADAY_FROM:
        pass
    elif not live:
        reasons.append('live top100 unavailable')
    elif csv_ok and closes['dates'][-1] < today:
        row, why = _live_row(closes, live)
        if why:
            reasons.append(why)
        else:
            m_today, why = regime6_metrics(closes['rows'][-(R6_LOOKBACK_ROWS - 1):] + [row])
            source = 'live'
            if why:
                reasons.append(why)

    fresh = m_today is not None
    if fresh:
        new_today = {'date': today, 'source': source, 'metrics': m_today}
    elif stored and stored.get('date') == today and hhmm >= R6_INTRADAY_FROM:
        new_today = stored           # 오늘 앞선 런의 판정을 유지
        m_today, source = stored['metrics'], stored.get('source')
    else:
        new_today = stored if stored and stored.get('date') == today else None

    # ③ 출력
    raw = None
    m_shown = m_today
    if m_today is not None:
        cur, raw = (regime6_step(base, m_today['D'], today) if base is not None
                    else (_commit(None, today, m_today), direction_level(m_today['D'])))
        vol10 = m_today['vol10']
    else:
        cur, vol10 = base, (base or {}).get('vol10')
        if base is not None and base.get('metrics'):
            m_shown, source = base['metrics'], f"prev_confirmed:{base['date']}"

    if fresh:
        status = 'ok'
    elif hhmm < R6_INTRADAY_FROM and not reasons and base is not None:
        status = 'hold_pre10'
    else:
        status = 'stale'
    if hhmm < R6_INTRADAY_FROM and not fresh:
        reasons.insert(0, f'before {R6_INTRADAY_FROM}: previous confirmed kept')

    level = cur['level'] if cur else None
    cand = cur.get('candidate') if cur else None
    shown = m_shown or {}
    return {
        'state': {'base': base, 'today': new_today},
        'regime6': regime6_label(level, vol10),
        'level': level,
        'candidate': regime6_label(cand, vol10) if cand is not None else None,
        'candidate_days': cur.get('candidate_days', 0) if cur else 0,
        'confirmed_since': cur.get('confirmed_since') if cur else None,
        'raw_level': raw,
        'status': status,
        'metrics': {
            'D': shown.get('D'), 'ab20': shown.get('ab20'),
            'ret10': shown.get('ret10'), 'vol10': vol10,
            'source': source,
            'reason': '; '.join(reasons) or None,
        },
    }


class LiberoSimulator(BaseSimulator):
    """
    [Sim 0] 리베로 (Libero) — 시장 국면 감지기 + 전략 추천.
    매매하지 않는다(현금 0, 포트폴리오 없음). 매 실행마다 후보 전체에서
    시장 지표를 역산(Breadth)하여 BULL/SIDEWAYS/BEAR 국면을 판단하고,
    방향성 점수(bull_score)와 국면별 추천 전략을 state에 저장한다.
    Sim 1~6이 개별 선수라면 리베로는 국면을 읽는 지휘자 역할.
    """
    IS_ANALYZER = True  # reset 시 자본 부여 대상에서 제외 (현금 0 유지)

    REGIME_TO_SIMS = {
        "BULL":     ["sim4_bull", "sim_psych", "sim_risk"],
        "SIDEWAYS": ["sim5_sideways", "sim_psych", "sim_spillover"],
        "BEAR":     ["sim6_bear"],  # 나머지는 슬립 모드 권고
    }

    def __init__(self, initial_cash=0):
        super().__init__("Libero", initial_cash)

    @staticmethod
    def _clamp(v, lo=0.0, hi=100.0):
        return max(lo, min(hi, v))

    def calc_bull_score(self, breadth, momentum, trend):
        """0(극단 약세)~100(극단 강세). breadth/momentum/trend를 가중합. foreign 제거(top100 소스 없음)."""
        momentum_n = self._clamp(50 + momentum * 5)   # 0%→50, +10%→100, -10%→0
        trend_n = self._clamp(trend)                  # ADX 근사 0~100
        return round(breadth * 0.40 + momentum_n * 0.35 + trend_n * 0.25, 1)

    def _update_regime6(self, now):
        """6단계 국면을 갱신하고 current_regime 등 파생 필드를 state에 쓴다.

        입력은 trade_engine이 주입하는 `regime6_inputs`
        ({'closes': load_top100_closes(...), 'live': {code: {price, change_rate}}})다.
        없으면 판정 불가 — 직전 확정값을 유지하고, 그것도 없으면 None이다.
        SIDEWAYS로 채우지 않는다(모르는 것과 횡보는 다르다).
        """
        inputs = getattr(self, 'regime6_inputs', None) or {}
        out = advance_regime6(self.state.get('regime6_state'), inputs.get('closes'),
                              inputs.get('live'), now)
        m = out['metrics']
        regime6 = out['regime6']
        regime3 = rs.to_regime3(regime6)
        raw = out['raw_level']
        # instant_regime = 오늘 원시 방향 단계(미확정)의 3단계. 10시 전·판정 불가면 None.
        instant = None if raw is None else ('BEAR' if raw < 0 else 'BULL' if raw > 0 else 'SIDEWAYS')
        history = list(self.state.get('regime_history', []))
        if instant is not None:
            history = (history + [instant])[-5:]
        self.state.update({
            'regime6_state': out['state'],
            'regime6': regime6,
            'regime6_level': out['level'],
            'regime6_candidate': out['candidate'],
            'regime6_candidate_days': out['candidate_days'],
            'regime6_confirmed_since': out['confirmed_since'],
            'regime6_status': out['status'],
            'regime6_metrics': {
                'D': None if m['D'] is None else round(m['D'], 4),
                'ab20': None if m['ab20'] is None else round(m['ab20'], 1),
                'ret10': None if m['ret10'] is None else round(m['ret10'] * 100, 2),  # %
                'vol10': None if m['vol10'] is None else round(m['vol10'], 3),        # %
                'raw_level': raw,
                'source': m['source'],
                'judged_at': now.strftime('%Y-%m-%d %H:%M:%S'),
                'reason': m['reason'],
            },
            'current_regime': regime3,
            'instant_regime': instant,
            # 옛 5런 최빈값 신뢰도는 새 판정에 대응하는 값이 없다 — 지어내지 않는다.
            'regime_confidence': None,
            'regime_history': history,
            'recommended_sims': self.REGIME_TO_SIMS.get(regime3, []),
        })
        if m['reason']:
            print(f"[Libero] 6단계 국면 {out['status']}: {m['reason']}")

    def run(self, candidates, current_prices=None):
        # 국면(regime6 → current_regime)은 top100 종가 CSV + 장중 현재가로만
        # 정한다(_update_regime6). breadth/momentum/trend는 bull_score·metrics
        # 표시용으로만 남아 있다 — 국면 판정에는 쓰지 않는다.
        #
        # bull_score 입력: top100 라이브 실측(live_market_metrics) 우선, 없으면
        # candidates(버즈 후보) 폴백. 둘 다 없으면 bull_score·metrics는 직전 값을 둔다.
        now = get_kst_now()
        self._update_regime6(now)

        metrics = getattr(self, 'live_market_metrics', None)
        if candidates or metrics:
            self._update_bull_score(candidates, metrics)

        # 날짜별 판단 로그 (최근 30일 유지, 하루 1행). 같은 날 뒤 런은 regime·regime6를
        # 최신 값으로 덮는다 — 10시 전 첫 런은 늘 전일 확정값이라, 첫 런만 남기면 로그가
        # 하루씩 밀린다. bull_score·breadth는 종전대로 그날 첫 값이다.
        today_str = now.strftime('%Y-%m-%d')
        daily_log = list(self.state.get('daily_regime_log', []))
        if not daily_log or daily_log[-1].get('date') != today_str:
            daily_log.append({
                'date': today_str,
                'bull_score': self.state.get('bull_score'),
                'breadth': (self.state.get('metrics') or {}).get('breadth_score'),
            })
            daily_log = daily_log[-30:]
        daily_log[-1] = {**daily_log[-1], 'regime': self.state.get('current_regime'),
                         'regime6': self.state.get('regime6')}

        self.state.update({
            'last_run': now.strftime('%Y-%m-%d %H:%M:%S'),
            'daily_regime_log': daily_log,
        })
        self.save_state()
        return self.state

    def _update_bull_score(self, candidates, metrics):
        """bull_score·metrics(표시용) 갱신. 계산식은 종전 그대로다."""
        ups = 0
        period_changes, adxs, foreigns, dailies = [], [], [], []
        for s in candidates:
            daily = self.parse_change_rate(s)
            dailies.append(daily)
            if daily > 0:
                ups += 1
            sp = s.get('sparkline_price', []) or []
            period_changes.append(self.calc_period_change(sp))
            adxs.append(self.calculate_adx(sp) if len(sp) >= 2 else 0.0)
            foreigns.append(float(s.get('foreign_change', 0) or 0))

        total = len(candidates)
        # breadth/momentum/trend는 top100 라이브 실측(trade_engine이 주입)을 우선 사용.
        # 버즈 후보군(3~30개)은 표본 편향·양자화가 심해 top100 지표의 추정치로 부적합
        # (2026-07-08 갭 분석). trend는 CSV 파싱 실패 시에만 버즈 ADX median으로 개별 폴백하고,
        # breadth/momentum은 라이브 실측 실패(live_market_metrics=None) 시에만 후보 기반으로 폴백.
        if metrics:
            breadth = round(float(metrics['breadth']), 1)
            momentum = round(float(metrics['momentum']), 2)
            trend = round(float(metrics['trend']), 1) if metrics.get('trend') is not None \
                else (round(_median(adxs), 1) if adxs else 0.0)
            breadth_sample = int(metrics.get('sample', 0))
            breadth_source = 'top100_live'
        else:
            breadth = round(ups / total * 100, 1) if total else 0.0
            momentum = round(_median(period_changes), 2) if period_changes else 0.0
            trend = round(_median(adxs), 1) if adxs else 0.0
            breadth_sample = total
            breadth_source = 'candidates'
        if candidates:
            foreign = round(_mean(foreigns), 3) if foreigns else 0.0   # metrics 표시 전용(bull_score 미사용)
            volatility = round(_pstdev(dailies), 2) if len(dailies) > 1 else 0.0
        else:
            # candidates 없이 top100 실측만으로 판단하는 경로 — foreign·volatility는
            # 후보 종목에서만 뽑을 수 있어 여기서는 측정 불가. 0.0(중립)으로 지어내지
            # 않고 None으로 남긴다.
            foreign = None
            volatility = None

        self.state.update({
            'bull_score': self.calc_bull_score(breadth, momentum, trend),
            'metrics': {
                'breadth_score': breadth,
                'momentum_score': momentum,
                'trend_strength': trend,
                'foreign_score': foreign,
                'volatility_score': volatility,
            },
            'sample_size': breadth_sample,
            'breadth_source': breadth_source,
        })

    # ──────────────────────────────────────────────────
    # 나우캐스트: 시간당 실측 기록 + (+1h/EOD) 예측 + 채점
    # 실측은 채점 전용 — 예측에 정답을 섞지 않는다(룩어헤드 금지).
    # ──────────────────────────────────────────────────
    MARKET_CLOSE = '15:30'
    # 하루 13건(h1 6 + EOD 7) x 약 92거래일. 2026-09-16에 예측 모델을 셋에서
    # 하나로 줄이면서 생산량이 하루 39건에서 13건이 됐다. 상한을 그대로 둔 것은
    # 롤링 절단이 초기 표본을 조용히 지우는 걸 막기 위해서다(당시 1133/1200).
    SCORE_LOG_MAX = 1200
    # 예측 모델 이름. 로그 스키마의 model 필드가 이 값이며, 미기재 로그의
    # 기본값도 이것이다(구 로그의 'velocity'/'smoothed_velocity'는 그대로 읽힌다).
    FORECAST_MODEL = 'naive'

    @staticmethod
    def _hour_label(now):
        return now.strftime('%H:00')

    def _intraday(self, today_str):
        """오늘 자 intraday 버킷 반환(날짜 바뀌면 리셋). 채점 로그는 별도 키라 유지됨."""
        intr = self.state.get('intraday')
        if not intr or intr.get('date') != today_str:
            intr = {'date': today_str, 'measurements': [], 'predictions': []}
            self.state['intraday'] = intr
        return intr

    def _append_score(self, entry):
        log = list(self.state.get('intraday_score_log', []))
        log.append(entry)
        self.state['intraday_score_log'] = log[-self.SCORE_LOG_MAX:]

    def update_nowcast(self, measured_breadth, now_kst=None, backfill=None):
        """장중 매 런 호출.
        ① 이 시각 top100 실측 breadth 기록(시간대당 1건)
        ② 도래한 +1h 예측을 실측으로 채점 — 해당 시각 실측이 없으면 backfill(KIS 분봉)로 복원 시도
        ③ 이 시각 기준 +1h/EOD 예측 생성(naive = 직전 실측값 유지, 0~100 클램프)
        measured_breadth가 None이면 아무것도 하지 않는다(fail-quiet)."""
        if measured_breadth is None:
            return
        now = now_kst or get_kst_now()
        today_str = now.strftime('%Y-%m-%d')
        label = self._hour_label(now)
        intr = self._intraday(today_str)
        meas = intr['measurements']
        preds = intr['predictions']

        # ① 실측 기록 (같은 시간대 재실행 시 첫 값 유지)
        if not any(m['t'] == label for m in meas):
            meas.append({'t': label, 'breadth': round(float(measured_breadth), 1)})
            meas.sort(key=lambda m: m['t'])

        # ② 도래한 +1h 예측 채점
        for p in preds:
            if p['type'] != 'h1' or p.get('scored') or p['target'] > label:
                continue
            actual = next((m['breadth'] for m in meas if m['t'] == p['target']), None)
            if actual is None and backfill:
                try:
                    filled = backfill(p['target'])
                except Exception as e:
                    print(f"[Libero] 백필 실패({p['target']}): {e}")
                    filled = None
                if filled is not None:
                    actual = round(float(filled), 1)
                    meas.append({'t': p['target'], 'breadth': actual})
                    meas.sort(key=lambda m: m['t'])
            if actual is None:
                continue  # 다음 런에서 재시도 (EOD finalize에서 정리)
            self._append_score({
                'date': today_str, 'type': 'h1', 'made_at': p['made_at'],
                'model': p.get('model', self.FORECAST_MODEL),
                'target': p['target'], 'pred': p['value'], 'actual': actual,
                'gap': round(p['value'] - actual, 1),
            })
            p['scored'] = True

        # ③ 예측 생성 (시간대당 1회)
        # **예측 모델은 naive(직전 실측값 유지) 하나다.** 원래는 속도 외삽
        # (velocity = 마지막값 + 최근 변화율 × 남은 시간 × 감쇠)이 본선이었고
        # naive는 기준선으로, smoothed_velocity는 단일 구간 노이즈를 평활한
        # 변형으로 옆에서 같이 채점했다. 2026-09-16에 세 모델이 다 있는 19거래일
        # (08-20~09-15) 표본으로 판정이 났다 — MAE(낮을수록 좋다):
        #
        #     모델                  +1h(n=114)    EOD(n=126)
        #     naive                     6.91         10.90
        #     smoothed_velocity         9.80         14.80
        #     velocity                 10.10         15.64
        #
        # 일별 클러스터 t = +2.9~+5.4이고, naive보다 나은 날이 19일 중 1~4일뿐이다.
        # 속도 외삽은 10분짜리 단일 구간의 노이즈를 남은 시간만큼 늘리는 일을
        # 하고 있었고, 평활해도 그 방향이 바뀌지 않았다. 그래서 두 velocity 계열을
        # 예측 경로에서 내렸다(기록은 intraday_score_log에 09-15까지 남아 있다).
        if not any(p['made_at'] == label for p in preds):
            last = meas[-1]['breadth']
            next_label = f"{now.hour + 1:02d}:00"
            value = round(self._clamp(last), 1)
            if next_label <= '15:00':
                preds.append({'made_at': label, 'target': next_label, 'type': 'h1',
                              'model': self.FORECAST_MODEL, 'value': value,
                              'scored': False})
            preds.append({'made_at': label, 'target': 'EOD', 'type': 'eod',
                          'model': self.FORECAST_MODEL, 'value': value,
                          'scored': False})

        self.save_state()

    def finalize_eod(self, actual_eod, now_kst=None):
        """마감 후 런에서 호출(멱등). 확정 EOD breadth로:
        ① 당일 EOD 예측 전량 채점 ② 남은 +1h 예측 정리 ③ calibration_log 기록
        (그날 첫 EOD 예측 vs 확정 실측 — 진짜 예측 갭)."""
        if actual_eod is None:
            return
        now = now_kst or get_kst_now()
        today_str = now.strftime('%Y-%m-%d')
        intr = self.state.get('intraday')
        if not intr or intr.get('date') != today_str:
            return  # 오늘 예측이 없으면 채점할 것도 없음 (주말/휴장 보호)
        actual_eod = round(float(actual_eod), 1)

        if not any(m['t'] == self.MARKET_CLOSE for m in intr['measurements']):
            intr['measurements'].append({'t': self.MARKET_CLOSE, 'breadth': actual_eod})

        first_eod_pred = None
        for p in intr['predictions']:
            model = p.get('model', self.FORECAST_MODEL)
            # calibration_log(프론트 갭 차트)는 **예측 모델**의 갭이어야 한다.
            # 2026-09-16까지는 이 조건이 `model == 'velocity'`였다. 예측 모델이
            # naive로 바뀌었으니 이름을 따라가야 한다 — 상수를 안 쓰고 문자열을
            # 박아두면 모델이 사라진 뒤 조건이 영원히 거짓이 되고, 갭 차트가
            # 에러 없이 **갱신만 멈춘다**(그래서 여기서 FORECAST_MODEL을 쓴다).
            # 값 자체는 바뀌지 않는다: calibration에 들어가는 건 그날 첫 EOD
            # 예측이고, 그 버킷(09:00)에는 관측이 1개뿐이라 옛 velocity는 0,
            # smoothed도 k=min(4,0)=0이어서 세 모델의 예측이 전부 last로
            # 같았다 — db-data 라이브 상태의 22거래일 전부(22/22)에서 그날 첫
            # 버킷은 09:00이고 세 모델의 EOD 예측이 한 자리도 다르지 않았다.
            if p['type'] == 'eod' and model == self.FORECAST_MODEL and first_eod_pred is None:
                first_eod_pred = p['value']
            if p.get('scored'):
                continue
            if p['type'] == 'eod':
                self._append_score({
                    'date': today_str, 'type': 'eod', 'made_at': p['made_at'],
                    'model': model,
                    'target': 'EOD', 'pred': p['value'], 'actual': actual_eod,
                    'gap': round(p['value'] - actual_eod, 1),
                })
            p['scored'] = True  # 미채점 h1도 종료 처리(익일 재시도 무의미)

        if first_eod_pred is not None:
            self.record_calibration(actual_eod, predicted=first_eod_pred)
        else:
            self.save_state()

    def record_calibration(self, actual_kospi_breadth: float, predicted: float | None = None) -> None:
        """
        예측 breadth와 확정 실측의 갭을 calibration_log에 기록.
        predicted가 주어지면 그날 첫 EOD 예측(v2 방식), 없으면 종전처럼 최신 추정치 사용.
        하루 1회만 기록 (중복 방지). 최대 90일 롤링 보관.
        """
        today_str = get_kst_now().strftime('%Y-%m-%d')
        log = list(self.state.get('calibration_log', []))
        if log and log[-1].get('date') == today_str:
            return

        libero_breadth = predicted if predicted is not None \
            else self.state.get('metrics', {}).get('breadth_score', 0.0)
        bull_score = self.state.get('bull_score', 0.0)
        regime = self.state.get('current_regime', 'SIDEWAYS')

        entry = {
            'date':                 today_str,
            'libero_breadth':       round(libero_breadth, 1),
            'actual_kospi_breadth': round(actual_kospi_breadth, 1),
            'gap':                  round(libero_breadth - actual_kospi_breadth, 1),
            'bull_score':           round(bull_score, 1),
            'regime':               regime,
        }
        if predicted is not None:
            entry['v'] = 2  # 예측 vs 확정 실측 방식 (프론트가 구형 죽은 라벨과 구분)
        log.append(entry)
        self.state['calibration_log'] = log[-90:]
        self.save_state()
        print(f"[Libero] 캘리브레이션: libero={libero_breadth:.1f}% / actual={actual_kospi_breadth:.1f}% / gap={libero_breadth - actual_kospi_breadth:+.1f}%")


# ──────────────────────────────────────────────────
# 상태 JSON 포맷 변경 & 마이그레이션
# ──────────────────────────────────────────────────

def init_state_v2():
    """새 상태 JSON 초기화

    Returns:
        dict: 새 포맷 상태
    """
    return {
        "current_regime": "SIDEWAYS",
        "confidence": 0.5,
        "instant_regime": "SIDEWAYS",
        "hourly_regime_log": [],
        "calibration_log": []
    }


def _determine_regime_from_breadth(breadth):
    """breadth에서 국면 판정

    Args:
        breadth: float (0-100)

    Returns:
        str: "BULL", "SIDEWAYS", "BEAR"
    """
    if breadth >= 60:
        return "BULL"
    elif breadth <= 40:
        return "BEAR"
    else:
        return "SIDEWAYS"


def load_state_with_migration(state_path):
    """기존 상태를 새 포맷으로 로드/변환

    기존 필드 유지:
    - current_regime, confidence (존재하면 그대로)
    - intraday_score_log → hourly_regime_log 변환
    - calibration_log (그대로)

    Args:
        state_path: str - 상태 파일 경로

    Returns:
        dict: 새 포맷 상태
    """
    import json
    import os

    if not os.path.exists(state_path):
        return init_state_v2()

    try:
        with open(state_path, 'r', encoding='utf-8-sig') as f:
            old_state = json.load(f)
    except Exception:
        return init_state_v2()

    # 새 상태 초기화
    new_state = init_state_v2()

    # 기존 국면, 신뢰도 복사
    if 'current_regime' in old_state:
        new_state['current_regime'] = old_state['current_regime']
    if 'confidence' in old_state:
        new_state['confidence'] = old_state['confidence']

    # intraday_score_log → hourly_regime_log 변환
    if 'intraday_score_log' in old_state:
        for entry in old_state['intraday_score_log']:
            regime = _determine_regime_from_breadth(entry.get('breadth', 50))
            new_log_entry = {
                'hour': entry.get('hour', '09:00'),
                'regime': regime,
                'confidence': entry.get('confidence', 0.5),
                'breadth': entry.get('breadth', 50.0),
                'inputs': {}  # 기존 데이터는 inputs 없음
            }
            new_state['hourly_regime_log'].append(new_log_entry)

    # calibration_log 그대로 복사
    if 'calibration_log' in old_state:
        new_state['calibration_log'] = old_state['calibration_log']

    return new_state


def save_state_v2(state, state_path):
    """새 포맷으로 상태 저장

    Args:
        state: dict - 상태 객체
        state_path: str - 저장할 파일 경로
    """
    import json
    import os

    os.makedirs(os.path.dirname(state_path), exist_ok=True)

    with open(state_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def determine_regime(final_breadth):
    """3상태 국면 판정

    Args:
        final_breadth: float (0-100)

    Returns:
        str: "BULL", "SIDEWAYS", "BEAR"
    """
    if final_breadth >= 60:
        return "BULL"
    elif final_breadth <= 40:
        return "BEAR"
    else:
        return "SIDEWAYS"


def update_hourly(current_hour, state, market_data, kospi_data, foreigner_data):
    """매시간 갱신

    1. 신호 수집
    2. 앙상블 계산
    3. 국면 판정
    4. 신뢰도 계산
    5. 로그 추가 (최대 7개)
    6. current_regime, confidence 갱신

    Args:
        current_hour: str ("09:00", "10:00", ... "15:00")
        state: dict - 상태 객체
        market_data: {'breadth': float (0-100), 'declining': int, 'rising': int}
        kospi_data: {'price': float, 'ma5': float}
        foreigner_data: {'buy_amount': float}

    Returns:
        dict: {'regime': str, 'confidence': float}
    """
    signals = collect_signals(market_data, kospi_data, foreigner_data)
    final_breadth = ensemble_breadth(signals)
    regime = determine_regime(final_breadth)
    recent_logs = state.get('hourly_regime_log', [])[-3:]
    confidence = calculate_confidence(final_breadth, recent_logs, current_hour, signals)

    log_entry = {
        'hour': current_hour,
        'regime': regime,
        'confidence': confidence,
        'breadth': final_breadth,
        'inputs': signals
    }
    state['hourly_regime_log'].append(log_entry)

    if len(state['hourly_regime_log']) > 7:
        state['hourly_regime_log'] = state['hourly_regime_log'][-7:]

    state['current_regime'] = regime
    state['confidence'] = confidence

    return {'regime': regime, 'confidence': confidence}
