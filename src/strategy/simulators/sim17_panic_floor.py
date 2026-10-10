"""Sim17 패닉 바닥 — 저점 국면 판정기. 매매하지 않는다.

2026-10-07 탐색에서 다섯 경로(저점 유형 군집 · 전환점 전수 스캔 · 지수별 선행
스캔 · 규칙 검정 · 코스피 EPU 분위)가 전부 한 곳으로 수렴했다:

    글로벌 정책 불확실성과 금융스트레스가 극단일 때 **코스피만** 크게 반등한다.

과거 성과(코스피). **에피소드 단위**로 센다 — 월 단위로 세면 15개월짜리
에피소드가 15번 계산돼 승률이 부풀려진다(2026-10-07 수정: 승률 86%로 적어
놓았던 것이 그 오류였다).

    관찰(EPU 12M변화 분위≥80)  25에피소드  3개월 +2.6%(68%) · 12개월 +14.7%(76%)
    패닉바닥(두 z 모두 ≥2)      5에피소드  3개월 +28.0%(80%) · 12개월 +58.3%(80%)

코스피 기저율이 3개월 상승 60.1% · 12개월 64.7%다. 그래서 **패닉바닥의 80%는
기저율과 통계적으로 구분되지 않는다**(이항 p=0.34 / 0.38). 기저율 60%에서
80%가 운이 아니라고 말하려면 에피소드가 14개 필요한데 5개뿐이다.

S&P500은 같은 조건에서 평시와 차이가 거의 없다 — 그래서 이 판정기는
**한국 시장용**이다.

치명적 한계를 먼저 적는다. 이 신호는 **설계 구간(2000~2014)에 없다**
(EPU 12M변화 → 코스피 3개월, 설계 t=+1.70 / 확인 t=+4.88). 2015년 이후
데이터로만 만든 규칙이고 그 구간에 코로나·관세가 몰려 있다. 아웃오브샘플
검증이 원리적으로 불가능하므로 **관찰 전용**이고 매매에 쓰지 않는다.

판정은 오직 상태를 기록하고 단계가 바뀔 때 알린다. 포지션을 만들지 않는다.
"""
from __future__ import annotations

from src.data import macro_panic

from .base_simulator import BaseSimulator, get_kst_now

try:
    from src import alerts
except Exception:       # 알림 모듈이 없어도 판정은 돈다
    alerts = None

# 문턱. 2026-10-07 탐색값이고 바꾸면 위 성과표가 이 코드를 설명하지 않는다.
WATCH_PCT = 80.0        # EPU 12개월 변화 백분위 — 상위 20%
PANIC_Z = 2.0           # 금융스트레스 z와 EPU z를 동시에 넘어야 한다

NORMAL, WATCH, PANIC = '정상', '관찰', '패닉바닥'
UNKNOWN = '판정불가'
ALERT_COOLDOWN_MIN = 24 * 60


def classify(metrics):
    """지표 → (단계, 사유). 지표가 모자라면 판정하지 않는다."""
    if not metrics or not metrics.get('ready'):
        return UNKNOWN, '지표 미완성'
    pct = metrics.get('epu_12m_pct')
    ez, sz = metrics.get('epu_z'), metrics.get('stress_z')
    if pct is None or ez is None or sz is None:
        return UNKNOWN, '지표 결측'
    if sz >= PANIC_Z and ez >= PANIC_Z:
        return PANIC, f'금융스트레스 z={sz:+.2f} · EPU z={ez:+.2f} (둘 다 ≥{PANIC_Z})'
    if pct >= WATCH_PCT:
        return WATCH, f'EPU 12개월 변화 상위 {100 - pct:.0f}% (분위 {pct:.0f})'
    return NORMAL, f'EPU 분위 {pct:.0f} · 스트레스 z={sz:+.2f} · EPU z={ez:+.2f}'


def format_notice(stage, reason, metrics, prev_stage):
    lines = [f'[패닉바닥 판정] {prev_stage} → {stage}', '', reason, '']
    if metrics.get('stale'):
        lines.append(f"⚠ 어제 값 사용(갱신 실패: {metrics.get('stale_reason')})")
    partial = ' ⚠미완결' if metrics.get('epu_month_partial') else ''
    lines.append(f"미EPU 수준 {metrics.get('epu_level')} "
                 f"({metrics.get('epu_month')}, {metrics.get('epu_obs')}일{partial})")
    lines.append(f"금융스트레스 수준 {metrics.get('stress_level')} ({metrics.get('stress_month')})")
    aux = [(k[4:], v) for k, v in metrics.items() if k.startswith('aux_')]
    if aux:
        lines.append('참고: ' + ' · '.join(f'{k} {v}' for k, v in aux))
    if stage == PANIC:
        lines += ['', '과거 이 조건은 5번뿐이다 (1998-08 · 2001-09 · 2008-09 · '
                  '2018-12 · 2020-03).',
                  '그 뒤 코스피 3개월 +28.0%(4/5) · 12개월 +58.3%(4/5).',
                  '코스피 기저 상승률이 60~65%라 4/5는 운과 구분되지 않는다'
                  '(이항 p=0.34). 관찰용이고 매매 근거가 아니다.']
    return '\n'.join(lines)


class PanicFloorSimulator(BaseSimulator):
    """매매하지 않는다. 저점 국면만 판정하고 단계 전이를 알린다."""

    IS_ANALYZER = True
    IS_EOD = True       # 거시 지표는 하루 한 번이면 충분하다. 장중 루프에서 뺀다

    def __init__(self, initial_cash=0):
        super().__init__("PanicFloor", initial_cash)
        self.state.setdefault('stage', UNKNOWN)
        self.state.setdefault('stage_since', None)
        self.state.setdefault('history', [])

    def get_universe(self):
        return []       # 종목을 고르지 않는다

    def run(self, candidates, current_prices=None):
        now = get_kst_now()
        today = now.strftime('%Y-%m-%d')
        prev_stage = self.state.get('stage', UNKNOWN)

        metrics = macro_panic.get_metrics(self.state.get('metrics'), log=print)
        stage, reason = classify(metrics)

        self.state['metrics'] = metrics
        self.state['reason'] = reason
        self.state['checked_at'] = now.strftime('%Y-%m-%d %H:%M:%S')
        if stage != prev_stage:
            self.state['stage'] = stage
            self.state['stage_since'] = today
            self._append_history(today, stage, reason)
            self._notify(stage, reason, metrics, prev_stage, now)
            print(f'[Sim17 패닉바닥] {prev_stage} → {stage} | {reason}')
        else:
            print(f'[Sim17 패닉바닥] {stage} 유지 | {reason}')

        self.save_state(current_prices)
        return []       # 매매 신호를 내지 않는다

    def _append_history(self, date, stage, reason):
        h = self.state.setdefault('history', [])
        h.append({'date': date, 'stage': stage, 'reason': reason})
        del h[:-200]

    def _notify(self, stage, reason, metrics, prev_stage, now):
        # 판정불가로 떨어지는 것은 데이터 문제이므로 조용히 로그만 남긴다.
        if alerts is None or stage == UNKNOWN:
            return
        # 첫 실행(판정불가 → 정상)은 알리지 않는다. 사건이 아니라 기동이다.
        # 판정불가 → 관찰/패닉바닥은 알린다 — 데이터가 돌아오자마자 신호면 사건이다.
        if prev_stage == UNKNOWN and stage == NORMAL:
            return
        try:
            alerts.send_alert_once(f'panic_floor_{stage}',
                                   format_notice(stage, reason, metrics, prev_stage),
                                   now, cooldown_min=ALERT_COOLDOWN_MIN)
        except Exception as e:
            print(f'[Sim17 패닉바닥] 알림 실패: {type(e).__name__}: {e}')
