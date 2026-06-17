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

    def run(self, candidates, current_prices=None):
        if not candidates:
            # 분석할 데이터 없음 — 직전 국면 유지, 타임스탬프만 갱신
            self.state['last_run'] = get_kst_now().strftime('%Y-%m-%d %H:%M:%S')
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
        breadth = round(ups / total * 100, 1) if total else 0.0
        momentum = round(_median(period_changes), 2) if period_changes else 0.0
        trend = round(_median(adxs), 1) if adxs else 0.0
        foreign = round(_mean(foreigns), 3) if foreigns else 0.0
        volatility = round(_pstdev(dailies), 2) if len(dailies) > 1 else 0.0

        instant_regime = self.classify_regime(breadth, momentum, trend)
        bull_score = self.calc_bull_score(breadth, momentum, foreign, trend)

        # 국면 지속성(Smoothing): 최근 5회 중 과반 확정으로 False signal 방지
        history = list(self.state.get('regime_history', []))
        history.append(instant_regime)
        history = history[-5:]
        confirmed_regime, confidence = self._confirm_regime(history)

        # 날짜별 판단 로그 (최근 30일 유지, 하루 1회만 기록)
        today_str = get_kst_now().strftime('%Y-%m-%d')
        daily_log = list(self.state.get('daily_regime_log', []))
        if not daily_log or daily_log[-1].get('date') != today_str:
            daily_log.append({
                'date': today_str,
                'regime': confirmed_regime,
                'bull_score': bull_score,
                'breadth': breadth,
            })
            daily_log = daily_log[-30:]

        self.state.update({
            'last_run': get_kst_now().strftime('%Y-%m-%d %H:%M:%S'),
            'current_regime': confirmed_regime,
            'instant_regime': instant_regime,
            'regime_confidence': confidence,
            'bull_score': bull_score,
            'metrics': {
                'breadth_score': breadth,
                'momentum_score': momentum,
                'trend_strength': trend,
                'foreign_score': foreign,
                'volatility_score': volatility,
            },
            'regime_history': history,
            'recommended_sims': self.REGIME_TO_SIMS.get(confirmed_regime, []),
            'sample_size': total,
            'daily_regime_log': daily_log,
        })
        self.save_state()
        return self.state

    def record_calibration(self, actual_kospi_breadth: float) -> None:
        """
        실제 KOSPI 브레드스와 리베로 추정치의 갭을 calibration_log에 기록.
        하루 1회만 기록 (중복 방지). 최대 90일 롤링 보관.
        """
        today_str = get_kst_now().strftime('%Y-%m-%d')
        log = list(self.state.get('calibration_log', []))
        if log and log[-1].get('date') == today_str:
            return

        libero_breadth = self.state.get('metrics', {}).get('breadth_score', 0.0)
        bull_score = self.state.get('bull_score', 0.0)
        regime = self.state.get('current_regime', 'SIDEWAYS')

        log.append({
            'date':                 today_str,
            'libero_breadth':       round(libero_breadth, 1),
            'actual_kospi_breadth': round(actual_kospi_breadth, 1),
            'gap':                  round(libero_breadth - actual_kospi_breadth, 1),
            'bull_score':           round(bull_score, 1),
            'regime':               regime,
        })
        self.state['calibration_log'] = log[-90:]
        self.save_state()
        print(f"[Libero] 캘리브레이션: libero={libero_breadth:.1f}% / actual={actual_kospi_breadth:.1f}% / gap={libero_breadth - actual_kospi_breadth:+.1f}%")
