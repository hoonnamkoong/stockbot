from .base_simulator import BaseSimulator, get_kst_now


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


class LiberoSimulator(BaseSimulator):
    """
    [Sim 0] 리베로 (Libero) — 실시간 시장 국면 예측기 + 전략 추천.
    매매하지 않는다(현금 0, 포트폴리오 없음). 매 실행(장중 하루 여러 번)마다
    KOSPI top100의 '장중 등락'(trade_engine이 네이버 시총 페이지에서 나우캐스트)으로
    오늘 마감 국면을 미리 예측한다 — 장중가는 알지만 마감가는 모름(측정 아닌 예측).
    두 예측기를 병렬 운용: P0=원시 최신 나우캐스트, P1=오늘 이전 측정값 궤적 보정.
    마감 후 EOD 실제값으로 채점(score_pending)해 이긴 쪽을 live 국면 소스로 채택.
    출력: live_regime(속보)+confirmed_regime(스무딩)+confidence, bull_score, 추천 전략.
    (나우캐스트 미가용 시 공용 buzz 후보군으로 폴백.)
    Sim 1~10이 개별 선수라면 리베로는 국면을 읽는 지휘자 역할.
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

    def classify_regime(self, breadth, momentum, trend):
        """5개 집계 지표로 국면 분류."""
        if breadth >= 60 and momentum >= 2.0 and trend >= 20:
            return "BULL"
        if breadth <= 40 and momentum <= -2.0 and trend >= 15:
            return "BEAR"
        return "SIDEWAYS"

    def calc_bull_score(self, breadth, momentum, foreign, trend):
        """0(극단 약세)~100(극단 강세). 각 지표를 0~100으로 정규화 후 가중합."""
        momentum_n = self._clamp(50 + momentum * 5)   # 0%→50, +10%→100, -10%→0
        foreign_n = self._clamp(50 + foreign * 50)    # 외인 변화 ±1%p 기준
        trend_n = self._clamp(trend)                  # ADX 근사 0~100
        return round(breadth * 0.30 + momentum_n * 0.25 + foreign_n * 0.25 + trend_n * 0.20, 1)

    def _confirm_regime(self, history):
        """최근 국면 히스토리에서 최빈 국면과 신뢰도를 반환.
        5회 표본에서 과반(3) 미만이면 방향 불명확 → SIDEWAYS로 보수 확정."""
        if not history:
            return "SIDEWAYS", 0.0
        counts = {r: history.count(r) for r in set(history)}
        top = max(counts, key=counts.get)
        confidence = round(counts[top] / len(history), 2)
        if len(history) >= 3 and counts[top] < (len(history) // 2 + 1):
            return "SIDEWAYS", confidence
        return top, confidence

    @staticmethod
    def _zone(v):
        return "BULL" if v >= 60 else ("BEAR" if v <= 40 else "SIDEWAYS")

    @staticmethod
    def _project(xs):
        """오늘 장중 breadth 표본들로 P1 예측: 최근 속도(추세)를 외삽.
        속도 = 최근 최대 3개 스텝 변화의 평균 → 노이즈 완화하면서 추세 방향 반영.
        (평활/EWMA는 상승·하락 추세에서 오히려 지연되어 부적합.) 룰 기반 고정
        파라미터 → 과적합 없음. 이전 측정값 활용이 EOD 예측에 도움되는지는
        P0(원시 최신)와 병렬 채점으로 데이터가 판정한다."""
        if not xs:
            return 0.0
        if len(xs) == 1:
            return round(xs[0], 1)
        diffs = [xs[i] - xs[i - 1] for i in range(1, len(xs))]
        recent = diffs[-3:]
        vel = sum(recent) / len(recent)
        return max(0.0, min(100.0, round(xs[-1] + vel, 1)))

    def run(self, candidates, current_prices=None):
        now = get_kst_now()
        if not candidates:
            # 분석할 데이터 없음 — 직전 국면 유지, 타임스탬프만 갱신
            self.state['last_run'] = now.strftime('%Y-%m-%d %H:%M:%S')
            self.save_state()
            return self.state

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
        breadth_p0 = round(ups / total * 100, 1) if total else 0.0   # P0: 원시 최신 나우캐스트
        momentum = round(_median(period_changes), 2) if period_changes else 0.0
        trend = round(_median(adxs), 1) if adxs else 0.0
        foreign = round(_mean(foreigns), 3) if foreigns else 0.0
        volatility = round(_pstdev(dailies), 2) if len(dailies) > 1 else 0.0

        today = now.strftime('%Y-%m-%d')
        ts = now.strftime('%H:%M')
        intraday = dict(self.state.get('intraday', {}))
        today_log = list(intraday.get(today, []))

        # P1: 오늘 이전 측정값들 + 현재값으로 궤적 보정 예측
        prior_breadths = [x['breadth_p0'] for x in today_log]
        breadth_p1 = self._project(prior_breadths + [breadth_p0])

        regime_p0 = self.classify_regime(breadth_p0, momentum, trend)
        regime_p1 = self.classify_regime(breadth_p1, momentum, trend)

        # 채택된 예측기(누적 적중률로 결정, 기본 P0)의 값을 live로
        preferred = self.state.get('preferred_predictor', 'P0')
        if preferred == 'P1':
            live_breadth, live_regime = breadth_p1, regime_p1
        else:
            live_breadth, live_regime = breadth_p0, regime_p0

        # confirmed: 최근 장중 표본의 채택-예측기 국면 과반 확정(스무딩)
        history = list(self.state.get('regime_history', []))
        history.append(live_regime)
        history = history[-5:]
        confirmed_regime, confidence = self._confirm_regime(history)

        bull_score = self.calc_bull_score(live_breadth, momentum, foreign, trend)

        # 오늘 장중 예측 로그 append (마감 후 EOD로 채점)
        today_log.append({
            'ts': ts,
            'breadth_p0': breadth_p0, 'regime_p0': regime_p0,
            'breadth_p1': breadth_p1, 'regime_p1': regime_p1,
            'momentum': momentum, 'trend': trend,
        })
        intraday[today] = today_log
        if len(intraday) > 30:  # 최근 30 거래일만 보관
            for d in sorted(intraday)[:-30]:
                intraday.pop(d, None)

        # daily_regime_log: 오늘 항목을 매 실행마다 최신화(중복 append 방지)
        daily_log = [d for d in self.state.get('daily_regime_log', []) if d.get('date') != today]
        daily_log.append({
            'date': today, 'regime': confirmed_regime,
            'bull_score': bull_score, 'breadth': live_breadth,
        })
        daily_log = daily_log[-30:]

        self.state.update({
            'last_run': now.strftime('%Y-%m-%d %H:%M:%S'),
            'current_regime': confirmed_regime,     # 프론트/타 심 호환 유지(=confirmed)
            'confirmed_regime': confirmed_regime,
            'live_regime': live_regime,
            'instant_regime': regime_p0,
            'regime_confidence': confidence,
            'confidence': confidence,
            'preferred_predictor': preferred,
            'bull_score': bull_score,
            'metrics': {
                'breadth_score': live_breadth,      # 채택 예측기 값
                'breadth_p0': breadth_p0,
                'breadth_p1': breadth_p1,
                'momentum_score': momentum,
                'trend_strength': trend,
                'foreign_score': foreign,
                'volatility_score': volatility,
            },
            'regime_history': history,
            'recommended_sims': self.REGIME_TO_SIMS.get(confirmed_regime, []),
            'sample_size': total,
            'daily_regime_log': daily_log,
            'intraday': intraday,
        })
        self.save_state()
        return self.state

    def score_pending(self, actual_date: str, actual_breadth: float) -> None:
        """마감 후 확정된 EOD 실제 breadth로 해당일 장중 예측(P0/P1)을 채점한다.

        - 시각별 국면 적중(zone(pred)==zone(actual)) + breadth MAE 산출 → prediction_scores.
        - 누적 적중률로 preferred_predictor(P0/P1) 갱신(이긴 쪽을 live 소스로). 동률→P0.
        - calibration_log: 그날 첫 장중 예측 vs EOD(프론트 갭 차트용 '진짜' 예측 갭).
        이미 채점한 날짜는 재채점하지 않음(idempotent). 룩어헤드 없음(EOD는 채점 전용).
        """
        scores = dict(self.state.get('prediction_scores', {}))
        if actual_date in scores:
            return
        samples = self.state.get('intraday', {}).get(actual_date)
        if not samples:
            return

        actual_zone = self._zone(actual_breadth)
        by_time, p0_hits, p1_hits, p0_err, p1_err = [], 0, 0, 0.0, 0.0
        for s in samples:
            h0 = self._zone(s['breadth_p0']) == actual_zone
            h1 = self._zone(s['breadth_p1']) == actual_zone
            p0_hits += 1 if h0 else 0
            p1_hits += 1 if h1 else 0
            p0_err += abs(s['breadth_p0'] - actual_breadth)
            p1_err += abs(s['breadth_p1'] - actual_breadth)
            by_time.append({'ts': s['ts'],
                            'p0_breadth': s['breadth_p0'], 'p0_hit': h0,
                            'p1_breadth': s['breadth_p1'], 'p1_hit': h1})
        n = len(samples)
        scores[actual_date] = {
            'actual_breadth': round(actual_breadth, 1),
            'actual_zone': actual_zone,
            'n': n,
            'p0': {'hit_rate': round(p0_hits / n, 3), 'mae': round(p0_err / n, 2)},
            'p1': {'hit_rate': round(p1_hits / n, 3), 'mae': round(p1_err / n, 2)},
            'by_time': by_time,
        }
        for d in sorted(scores)[:-90]:  # 최근 90일 유지
            scores.pop(d, None)

        # 누적 집계 → preferred 갱신
        totals = dict(self.state.get('score_totals', {}))
        t0 = dict(totals.get('P0', {'hits': 0, 'n': 0}))
        t1 = dict(totals.get('P1', {'hits': 0, 'n': 0}))
        t0['hits'] += p0_hits; t0['n'] += n
        t1['hits'] += p1_hits; t1['n'] += n
        totals['P0'], totals['P1'] = t0, t1
        r0 = t0['hits'] / t0['n'] if t0['n'] else 0.0
        r1 = t1['hits'] / t1['n'] if t1['n'] else 0.0
        preferred = 'P1' if r1 > r0 else 'P0'   # 동률 → P0(단순 최신값)

        # calibration_log: 그날 첫 장중 예측(채택 예측기) vs EOD → 프론트 갭 차트용 실제 예측 갭
        first = samples[0]
        pred_b = first['breadth_p1'] if preferred == 'P1' else first['breadth_p0']
        pred_r = first['regime_p1'] if preferred == 'P1' else first['regime_p0']
        cal = [c for c in self.state.get('calibration_log', []) if c.get('date') != actual_date]
        cal.append({
            'date': actual_date,
            'libero_breadth': round(pred_b, 1),
            'actual_kospi_breadth': round(actual_breadth, 1),
            'gap': round(pred_b - actual_breadth, 1),
            'bull_score': round(self.state.get('bull_score', 0.0), 1),
            'regime': pred_r,
        })
        cal = cal[-90:]

        self.state['prediction_scores'] = scores
        self.state['score_totals'] = totals
        self.state['preferred_predictor'] = preferred
        self.state['calibration_log'] = cal
        self.save_state()
        print(f"[Libero] 채점 {actual_date}: P0 {p0_hits}/{n}(MAE {p0_err/n:.1f}) "
              f"P1 {p1_hits}/{n}(MAE {p1_err/n:.1f}) → 채택 {preferred}")
