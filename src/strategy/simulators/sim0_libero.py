import statistics

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

    def calc_bull_score(self, breadth, momentum, trend):
        """0(극단 약세)~100(극단 강세). breadth/momentum/trend를 가중합. foreign 제거(top100 소스 없음)."""
        momentum_n = self._clamp(50 + momentum * 5)   # 0%→50, +10%→100, -10%→0
        trend_n = self._clamp(trend)                  # ADX 근사 0~100
        return round(breadth * 0.40 + momentum_n * 0.35 + trend_n * 0.25, 1)

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
        # breadth/momentum/trend는 top100 라이브 실측(live_market_metrics)만으로도
        # 산출 가능하다 — candidates(버즈 후보)는 foreign·volatility(둘 다 표시 전용,
        # calc_bull_score 미사용)에만 쓰인다. 그래서 candidates가 비어도 라이브
        # 실측이 있으면 국면을 판단한다. 스크래핑을 기다리지 않고 매매를 먼저
        # 내보내는 순서(needs_buzz=false 경로)의 입력이 이 판단이다.
        # 둘 다 없을 때만 판단 불가 — 직전 국면 유지, 타임스탬프만 갱신.
        metrics = getattr(self, 'live_market_metrics', None)
        if not candidates and not metrics:
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

        instant_regime = self.classify_regime(breadth, momentum, trend)
        bull_score = self.calc_bull_score(breadth, momentum, trend)

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
            'sample_size': breadth_sample,
            'breadth_source': breadth_source,
            'daily_regime_log': daily_log,
        })
        self.save_state()
        return self.state

    # ──────────────────────────────────────────────────
    # 나우캐스트: 시간당 실측 기록 + (+1h/EOD) 예측 + 채점
    # 실측은 채점 전용 — 예측에 정답을 섞지 않는다(룩어헤드 금지).
    # ──────────────────────────────────────────────────
    MARKET_CLOSE = '15:30'
    SCORE_LOG_MAX = 400   # ≈ 8건/일 × 50일
    EOD_DAMPING = 0.5     # 속도 외삽 감쇠(모멘텀은 마감까지 절반만 이어진다고 가정)

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
        ③ 이 시각 기준 +1h/EOD 예측 생성(최근 속도 외삽, 0~100 클램프)
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
                'target': p['target'], 'pred': p['value'], 'actual': actual,
                'gap': round(p['value'] - actual, 1),
            })
            p['scored'] = True

        # ③ 예측 생성 (시간대당 1회)
        if not any(p['made_at'] == label for p in preds):
            velocity = meas[-1]['breadth'] - meas[-2]['breadth'] if len(meas) >= 2 else 0.0
            last = meas[-1]['breadth']
            next_label = f"{now.hour + 1:02d}:00"
            if next_label <= '15:00':
                preds.append({'made_at': label, 'target': next_label, 'type': 'h1',
                              'value': round(self._clamp(last + velocity), 1), 'scored': False})
            hours_left = max(0.0, 15.5 - (now.hour + now.minute / 60.0))
            preds.append({'made_at': label, 'target': 'EOD', 'type': 'eod',
                          'value': round(self._clamp(last + velocity * hours_left * self.EOD_DAMPING), 1),
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
            if p['type'] == 'eod' and first_eod_pred is None:
                first_eod_pred = p['value']
            if p.get('scored'):
                continue
            if p['type'] == 'eod':
                self._append_score({
                    'date': today_str, 'type': 'eod', 'made_at': p['made_at'],
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
