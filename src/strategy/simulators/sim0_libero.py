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
        # breadth는 top100 라이브 실측(trade_engine이 주입)을 우선 사용.
        # 버즈 후보군(3~30개)은 표본 편향·양자화가 심해 top100 breadth의 추정치로 부적합
        # (2026-07-08 갭 분석). 라이브 수집 실패 시에만 기존 후보 기반으로 폴백.
        metrics = getattr(self, 'live_market_metrics', None)
        if metrics:
            breadth = round(float(metrics['breadth']), 1)
            momentum = round(float(metrics['momentum']), 2)
            trend = round(float(metrics['trend']), 1)
            breadth_sample = int(metrics.get('sample', 0))
            breadth_source = 'top100_live'
        else:
            breadth = round(ups / total * 100, 1) if total else 0.0
            momentum = round(_median(period_changes), 2) if period_changes else 0.0
            trend = round(_median(adxs), 1) if adxs else 0.0
            breadth_sample = total
            breadth_source = 'candidates'
        foreign = round(_mean(foreigns), 3) if foreigns else 0.0   # metrics 표시 전용(bull_score 미사용)
        volatility = round(_pstdev(dailies), 2) if len(dailies) > 1 else 0.0

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
