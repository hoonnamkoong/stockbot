from src.data import hype_dict, sim_diag

from .base_simulator import BaseSimulator

_parse_change_rate = BaseSimulator.parse_change_rate
_cooldown_active = BaseSimulator.cooldown_active

MIN_AMOUNT = 1_000_000_000
MAX_HOLDINGS = 6             # 전 심 통일 (0.15 × 6 = 최대 90% 투입)
POSITION_WEIGHT = 0.15
MIN_SAMPLE = 10              # 횡단면 z 최소 표본. 미달이면 z를 만들지 않는다.

# 점화 임계값 — 잠정값이다.
# 설계안은 ignition = 1.0*z_posters + 1.0*z(d_sov) + 0.7*z(d_hype) + 0.5*z(likes_per_post)
# 에 2.5였으나, d_sov·d_hype는 전일 이력이 있어야 만들 수 있다. 지금은 관측 가능한
# 3항(z_posters + z_sov + z_likes)만 합산한다.
# 2.5를 그대로 쓰는 근거: 실제 횡단면(881런·14,751 종목-런)에서 통과율이
# T=1.5→22.0%, 2.5→18.6%, 3.0→17.3%로 거의 평평하다. 관심 분포가 강한 우편향이라
# 임계값이 결과를 좌우하지 않는다 — 즉 이 값은 위험한 자유도가 아니다.
# 이력이 붙어 항이 채워지면 재조정할 것.
IGNITION_MIN = 2.5

BUZZ_RATIO_MIN = 2.2         # 평상시 대비 관심 배수
BUZZ_COUNT_MIN = 30
POSTS_PER_POSTER_MAX = 3.0   # 도배 배제: 한 사람이 3글 넘게 쓰는 판은 관심이 아니다
CHANGE_MIN, CHANGE_MAX = -3.0, 3.0   # '가격 정체' 가설 원복 (-5~+7 완화가 가설을 희석했다)
ADX_MIN = 15.0
TICK_POWER_MIN = 120.0

TRAIL_ARM_PCT = 5.0
TRAIL_CALLBACK_PCT = 3.0
TP_ATR_MULT = 3.0
SL_ATR_MULT = 1.5


def _zmap(pairs):
    """[(code, value)] → {code: z}. 표본 부족·분산 0이면 빈 dict."""
    vals = [v for _, v in pairs]
    n = len(vals)
    if n < MIN_SAMPLE:
        return {}
    mu = sum(vals) / n
    sd = (sum((v - mu) ** 2 for v in vals) / n) ** 0.5
    if sd <= 0:
        return {}
    return {c: (v - mu) / sd for c, v in pairs}


HIST_MAX_DAYS = 5            # 주말 낀 연휴(금~화)까지는 '전일'로 인정한다
ACCEL_START_HHMM = '0930'    # 개장 30분은 z가 90분위 2.46z로 요동한다(실측)


def resolve_history(prev_day, snapshot, today):
    """(prev_day, last_run) 결정. 순수함수.

    직전 런 스냅샷의 날짜가 오늘이 아니면 그것이 곧 전일 마지막 런이다.
    이 사실 하나로 승격이 끝나므로 '당일 마지막'을 따로 추적할 필요가 없다.
    """
    if snapshot and snapshot.get('date') != today:
        return snapshot, None
    return prev_day, snapshot


def _days_between(older, newer):
    """'YYYYMMDD' 두 개의 일수 차. 못 읽으면 None."""
    from datetime import datetime
    try:
        a = datetime.strptime(str(older), '%Y%m%d')
        b = datetime.strptime(str(newer), '%Y%m%d')
    except (ValueError, TypeError):
        return None
    return (b - a).days


def history_terms(rows, prev_day, last_run, today, hhmm):
    """rows에 이력 파생값을 제자리로 채운다.

    결측은 중립 0이다. 매일 후보의 38~48%가 신규 유입이라(실측) 이건
    예외 처리가 아니라 절반의 정책이다. fail-closed는 Sim1이 노리는
    '새로 터진 관심'을 구조적으로 배제한다.
    """
    pz = (prev_day or {}).get('z', {})
    lz = (last_run or {}).get('z', {})
    days_ago = _days_between((prev_day or {}).get('date'), today)
    usable = bool(pz) and days_ago is not None and 0 < days_ago <= HIST_MAX_DAYS
    accel_ok = str(hhmm) >= ACCEL_START_HHMM

    raw = {}
    for r in rows:
        c = r['code']
        p = pz.get(c) if usable else None
        r['hist_days_ago'] = days_ago if days_ago is not None else ''
        r['hist_missing'] = 0 if p else 1
        if p:
            raw[c] = ((r.get('z_sov') or 0) - p['z_sov'], (r.get('z_hype') or 0) - p['z_hype'])
            r['accel_d1'] = (r.get('z_posters') or 0) - p['z_posters']
        else:
            r['accel_d1'] = 0

        l = lz.get(c)
        r['accel'] = ((r.get('z_posters') or 0) - l['z_posters']) if (l and accel_ok) else 0

    # 델타의 횡단면 z는 이력 있는 종목만으로 만든다.
    # 결측의 0을 분포에 넣으면 z가 왜곡된다.
    zd_sov = _zmap([(c, v[0]) for c, v in raw.items()])
    zd_hype = _zmap([(c, v[1]) for c, v in raw.items()])
    for r in rows:
        c = r['code']
        r['d_sov'] = raw[c][0] if c in raw else 0
        r['d_hype'] = raw[c][1] if c in raw else 0
        # 설계식 4항. 계산만 하고 진입에는 쓰지 않는다 — 3항과 나란히
        # 기록해 다음 거래일 로그로 분포·통과율을 비교하기 위한 값이다.
        parts = [1.0 * (r.get('z_posters') or 0),
                 1.0 * zd_sov.get(c, 0),
                 0.7 * zd_hype.get(c, 0),
                 0.5 * (r.get('z_likes') or 0)]
        r['ignition4'] = sum(parts)


def build_snapshot(rows, today, ts):
    """이번 런의 z를 스냅샷으로. z 스케일만 담는다 — 원값은 당일 누적이라
    오전에 60~77% 어긋난다(실측)."""
    z = {}
    for r in rows:
        if r.get('z_sov') is None or r.get('z_posters') is None or r.get('z_hype') is None:
            continue
        z[r['code']] = {'z_sov': r['z_sov'], 'z_posters': r['z_posters'],
                        'z_hype': r['z_hype']}
    return {'date': today, 'ts': ts, 'z': z}


def _features(candidates):
    """후보 횡단면 → 종목별 심리 지표.

    sov(버즈 점유율)를 쓰는 이유: 게시글 절대수로 보면 대형주가 항상 이긴다.
    `or buzz_count>=500`이 정확히 그 함정이었다 — 소형주를 하나도 더 잡지 못하고
    평상시 대형주만 통과시켰다(실제 진입 로그: 삼성전자 Buzz 602/800).
    """
    rows = []
    total_posts = sum(float(s.get('recent_posts_count', 0) or 0) for s in candidates) or 1.0
    for s in candidates:
        code = s.get('code')
        if not code:
            continue
        posts = float(s.get('recent_posts_count', 0) or 0)
        posters = float(s.get('unique_posters', 0) or 0)
        likes = float(s.get('total_likes', 0) or 0)
        rows.append({
            'code': code,
            'posts': posts,
            'posters': posters,
            'posts_per_poster': (posts / posters) if posters > 0 else 0.0,
            'likes_per_post': (likes / posts) if posts > 0 else 0.0,
            'sov': posts / total_posts,
            'hype': hype_dict.hype_score([p.get('title') for p in (s.get('posts') or [])]),
        })

    z_posters = _zmap([(r['code'], r['posters']) for r in rows])
    z_sov = _zmap([(r['code'], r['sov']) for r in rows])
    z_likes = _zmap([(r['code'], r['likes_per_post']) for r in rows])
    z_hype = _zmap([(r['code'], r['hype']) for r in rows])
    feat = {}
    for r in rows:
        c = r['code']
        r['z_posters'] = z_posters.get(c)
        r['z_sov'] = z_sov.get(c)
        r['z_likes'] = z_likes.get(c)
        r['z_hype'] = z_hype.get(c)
        # 관측 가능한 항만 합산한 잠정 점화 지표. 임계값은 아직 걸지 않는다 —
        # d_sov·accel(이력 필요)이 빠져 있어 스케일이 설계안과 다르다.
        # 로그로 분포를 본 뒤 임계값을 정한다.
        parts = [v for v in (r['z_posters'], r['z_sov'], r['z_likes']) if v is not None]
        r['ignition'] = sum(parts) if parts else None
        feat[c] = r
    return feat


def decide_psych(view, candidates, current_prices, today=None, hhmm=None, ts=None):
    """[Sim1] 심리 괴리형 결정. (orders, diags, snapshot) 반환. 순수 함수.

    today·hhmm·ts는 주입받는다. 순수함수가 date.today()를 부르면
    백테스트에서 스냅샷 롤오버가 영영 돌지 않는다.
    """
    orders, diags = [], []
    portfolio = view['portfolio']
    sold = set()
    cand_by_code = {s.get('code'): s for s in candidates if s.get('code')}
    feat = _features(candidates)

    rows = list(feat.values())
    # 승격 판정은 run()이 이미 끝냈다. 여기서 다시 해석하지 않는다.
    history_terms(rows, view.get('psych_prev_day'), view.get('psych_last_run'),
                  today, hhmm)
    snapshot = build_snapshot(rows, today, ts)

    # 1. 청산 — ATR 기반 동적 익절/손절 + 트레일링 (기존 유지)
    for code in list(portfolio.keys()):
        p = portfolio[code]
        cur = current_prices.get(code, 0)
        avg = p.get('avg_price', 0)
        if cur <= 0 or avg <= 0:
            continue
        pr = (cur - avg) / avg * 100

        peak = p.get('peak_price', avg)
        if peak >= avg * (1 + TRAIL_ARM_PCT / 100) and cur <= peak * (1 - TRAIL_CALLBACK_PCT / 100):
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[심리] 트레일링 스탑 익절 ({pr:+.1f}%)",
                           'cooldown': 2, 'mark_partial': False})
            sold.add(code); continue

        stock = cand_by_code.get(code)
        sparkline = (stock or {}).get('sparkline_price', []) or []
        # sparkline 부족 시 1원 fallback은 즉시 손절을 유발한다 → 진입가의 1.5%
        atr = BaseSimulator.calculate_atr(sparkline) if len(sparkline) >= 3 else avg * 0.015

        if cur >= avg + atr * TP_ATR_MULT:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[심리] 동적 목표가 달성 (ATR 기반, {pr:+.1f}%)",
                           'cooldown': 2, 'mark_partial': False})
            sold.add(code)
        elif cur <= avg - atr * SL_ATR_MULT:
            orders.append({'action': 'SELL', 'code': code, 'price': cur, 'quantity': None,
                           'reason': f"[심리] 동적 손절가 이탈 (ATR 기반, {pr:+.1f}%)",
                           'cooldown': 3, 'mark_partial': False})
            sold.add(code)

    # 2. 진입
    if not view['market_index_healthy']:
        return orders, diags, snapshot

    target_amount = view['nav'] * POSITION_WEIGHT
    held = len([c for c in portfolio if c not in sold])
    for stock in candidates:
        code = stock.get('code')
        if not code:
            continue
        f = feat.get(code, {})
        price = float(stock.get('price', 0) or 0)
        amount = float(stock.get('amount', 0) or 0)
        change_rate = _parse_change_rate(stock)
        sparkline = stock.get('sparkline_price', []) or []
        adx = BaseSimulator.calculate_adx(sparkline) if len(sparkline) >= 3 else 0.0
        avg_posts = float(stock.get('avg_posts', 1) or 1)
        buzz_ratio = f.get('posts', 0) / (avg_posts if avg_posts > 0 else 1)

        d = {
            'code': code, 'name': stock.get('name', ''), 'price': price,
            'change_rate': f"{change_rate:.2f}", 'amount': amount,
            'adx': f"{adx:.1f}", 'tick_power': stock.get('tick_power', 0),
            'posts': f.get('posts', 0), 'unique_posters': f.get('posters', 0),
            'posts_per_poster': f"{f.get('posts_per_poster', 0):.2f}",
            'avg_posts': avg_posts, 'buzz_ratio': f"{buzz_ratio:.2f}",
            'total_likes': stock.get('total_likes', 0),
            'likes_per_post': f"{f.get('likes_per_post', 0):.2f}",
            'sov': f"{f.get('sov', 0):.4f}",
            'z_posters': _fmt(f.get('z_posters')), 'z_sov': _fmt(f.get('z_sov')),
            'z_likes': _fmt(f.get('z_likes')), 'ignition': _fmt(f.get('ignition')),
            'hype_score': f"{f.get('hype', 0):.3f}",
            'fact_score': stock.get('fact_score', 0),
            'z_hype': _fmt(f.get('z_hype')),
            'd_sov': _fmt(f.get('d_sov')), 'd_hype': _fmt(f.get('d_hype')),
            'accel': _fmt(f.get('accel')), 'accel_d1': _fmt(f.get('accel_d1')),
            'hist_missing': f.get('hist_missing', 1),
            'hist_days_ago': f.get('hist_days_ago', ''),
            'ignition4': _fmt(f.get('ignition4')),
        }

        skip = _skip_reason(stock, view, code, price, amount, change_rate,
                            sparkline, adx, buzz_ratio, f, portfolio, sold, held)
        if skip:
            d['decision'], d['reason'] = 'skip', skip
            diags.append(d)
            continue

        qty = int(target_amount / price)
        if qty <= 0:
            d['decision'], d['reason'] = 'skip', 'qty=0'
            diags.append(d)
            continue

        d['decision'], d['reason'] = 'entry', ''
        diags.append(d)
        held += 1
        orders.append({'action': 'BUY', 'code': code, 'name': stock.get('name', code),
                       'price': price, 'quantity': qty, 'cooldown': None,
                       'reason': f"[심리] 관심 폭발 + 가격 정체 "
                                 f"(작성자 {int(f.get('posters', 0))}명, "
                                 f"배수 {buzz_ratio:.1f}x, ADX {adx:.1f})"})
    return orders, diags, snapshot


def _fmt(v):
    return '' if v is None else f"{v:.3f}"


def _skip_reason(stock, view, code, price, amount, change_rate,
                 sparkline, adx, buzz_ratio, f, portfolio, sold, held):
    """첫 번째로 걸린 게이트 이름. 통과하면 None.

    순서가 곧 로그의 의미다 — 앞쪽 게이트가 뒤쪽을 가린다.
    """
    if code in portfolio or code in sold:
        return 'held'
    if held >= MAX_HOLDINGS:
        return 'full'
    if _cooldown_active(view['cooldown_codes'], code):
        return 'cooldown'
    if price <= 0:
        return 'no_price'
    if amount < MIN_AMOUNT:
        return 'illiquid'
    if len(sparkline) < 3:
        return 'no_sparkline'
    # 도배 배제. 한 사람이 여러 글을 쓰는 판은 '관심'이 아니다.
    if f.get('posters', 0) <= 0:
        return 'no_posters'
    if f.get('posts_per_poster', 0) >= POSTS_PER_POSTER_MAX:
        return 'spam'
    # `or buzz_count>=500` 삭제. 소형주를 하나도 더 잡지 못하고 평상시
    # 대형주만 통과시키던 OR절이었다.
    if not (buzz_ratio >= BUZZ_RATIO_MIN and f.get('posts', 0) >= BUZZ_COUNT_MIN):
        return 'buzz'
    if not (CHANGE_MIN <= change_rate <= CHANGE_MAX):
        return 'price_moved'
    if not BaseSimulator.validate_tick_power(stock, threshold=TICK_POWER_MIN):
        return 'weak_demand'
    if adx < ADX_MIN:
        return 'no_trend'
    # 점화 강도. 표본이 얇아 z를 못 내면 통과시키지 않는다 —
    # '신호 없음'을 '신호 있음'으로 취급하면 안 된다(fail-closed).
    ign = f.get('ignition')
    if ign is None:
        return 'no_ignition'
    if ign < IGNITION_MIN:
        return 'weak_ignition'
    return None


class PsychDivergenceSimulator(BaseSimulator):
    """
    [Sim 1] 심리 괴리형 (Psych-Divergence)
    - 원리: 대중의 관심이 폭증했는데 가격은 아직 정체일 때 매집.
    - 2026-07-28 개조. 백테스트 69거래·승률 36.4%·순수익 +0.11%(수수료가 이익의
      85%)로 실패했는데, 원인은 가설이 아니라 구현이었다:
        · `or buzz_count>=500` OR절이 소형주를 하나도 더 잡지 못하고 평상시
          대형주만 통과시켰다(진입 로그: 삼성전자 Buzz 602/800). → 삭제
        · `is_price_stable`이 -5~+7%로 완화돼 '가격 정체' 가설이 희석됐다. → 원복
        · 도배(한 사람이 여러 글)를 걸러내지 않았다. → posts_per_poster 게이트 추가
    - **후보 전부의 판단 근거를 sim_diag에 남긴다.** 6개월간 실패 원인을 몰랐던
      이유가 이 로그의 부재였다.
    - ignition(z_posters+z_sov+z_likes) >= 2.5. **잠정값**이다 — 설계안의
      d_sov·d_hype가 전일 이력을 요구해 아직 항이 빠져 있다. 실제 횡단면에서
      통과율이 T=1.5~3.0 구간 내내 22%→17%로 평평해(관심 분포가 강한 우편향)
      임계값이 결과를 좌우하지 않는다는 점은 확인했다. 이력이 붙으면 재조정.
    - 사이징은 전 심 통일값(NAV×15%, 최대 6종목). 이전에는 NAV/10에 보유
      상한이 없어 Sim1만 통일에서 빠져 있었다.
    """
    def __init__(self, initial_cash=3000000):
        super().__init__("Psych", initial_cash)

    def run(self, candidates, current_prices=None):
        from datetime import datetime, timedelta, timezone
        current_prices = current_prices or {}
        self.update_peak_prices(current_prices)

        now = datetime.now(timezone(timedelta(hours=9)))
        today = now.strftime('%Y%m%d')

        # 승격은 여기 한 곳에서만 판정한다.
        prev_day, last_run = resolve_history(self.state.get('psych_prev_day'),
                                             self.state.get('psych_snapshot'),
                                             today)
        view = self._view(current_prices)
        view['psych_prev_day'] = prev_day
        view['psych_last_run'] = last_run

        orders, diags, snapshot = decide_psych(
            view, candidates, current_prices,
            today=today, hhmm=now.strftime('%H%M'),
            ts=now.strftime('%Y-%m-%d %H:%M:%S'))

        self.state['psych_prev_day'] = prev_day
        self.state['psych_snapshot'] = snapshot

        self._apply(orders, current_prices)
        sim_diag.append('sim1', diags)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
