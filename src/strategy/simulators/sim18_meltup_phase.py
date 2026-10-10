"""Sim18 급등 고점 단계 — 경과 개월로 국면만 알린다. 매매하지 않는다.

2026-10-08~09 탐색 결과다. 전 세계 19지수에서 **"직전 12개월 +100% 이상
상승한 상태에서 252거래일 신고가"**를 찍은 사건을 사후 조건 없이 모았다
(완결 9사건). 그 뒤 최저점이 언제 왔는지만 보면:

    0~3개월   0건
    4~6개월   0건
    7~12개월  2건
    13~24개월 7건   ← 중앙 13개월

**9건 전부 최저점이 7개월 이후였고 7건은 13개월 이후다.** 그래서 이 심은
"지금 바닥인가"를 판정하지 않는다 — **앵커로부터 몇 달째인지**만 알린다.
0~6개월 구간에서 바닥을 주장할 근거가 과거에 한 건도 없다는 사실이
이 심의 전부다.

치명적 한계를 먼저 적는다:
  · **n=9**이고 그중 반도체 4건·상하이 2건으로 두 시장에 쏠려 있다.
  · 통계 검정이 아니라 **참조 분포**다. "코스피가 중앙 경로를 따를 확률"을
    말하지 않는다.
  · 코스피는 이 표본에서 처음 걸린 한국 사례다(2000년 버블은 전12M +81%로
    +100% 문턱 미달).
  · 2026년 코스피는 앵커 5개월째에 고점을 찍었다. 과거 "계속 오른" 2건은
    7·10개월째였고 둘 다 그 뒤 −56%·−69%로 끝났다. **어느 유형에도 깨끗이
    맞지 않는다.**

앵커는 한 번 잡으면 24개월까지 **움직이지 않는다**. 탐색 단계에서 "급등기
안의 가장 높은 신고가"로 앵커를 옮겼다가 룩어헤드를 만들었다 — 미래를 보고
시점을 고르면 그 뒤가 내려가는 게 당연하다.
"""
from __future__ import annotations

from src.data import kospi_index

from .base_simulator import BaseSimulator, get_kst_now

try:
    from src import alerts
except Exception:       # 알림 모듈이 없어도 판정은 돈다
    alerts = None

# 문턱. 2026-10-09 탐색값이고 바꾸면 위 표가 이 코드를 설명하지 않는다.
RUNUP = 100.0           # 앵커 조건: 직전 12개월 상승률(%)
HIGH_WINDOW = 252       # 앵커 조건: 신고가 창(거래일)
EXPIRE_MONTHS = 24      # 앵커 유효 기간

INACTIVE, EARLY, WATCH, TROUGH = '비활성', '조기', '관찰', '최저권'
UNKNOWN = '판정불가'
ALERT_COOLDOWN_MIN = 24 * 60

# 과거 9사건에서 최저점이 그 구간에 온 건수 — 알림 본문에 같이 싣는다.
TROUGH_COUNT = {EARLY: 0, WATCH: 2, TROUGH: 7}


def months_between(a, b):
    """'YYYY-MM-DD' 두 개의 개월 차이(일 단위 반올림 없이 월만 센다)."""
    ya, ma, da = int(a[:4]), int(a[5:7]), int(a[8:10])
    yb, mb, db = int(b[:4]), int(b[5:7]), int(b[8:10])
    n = (yb - ya) * 12 + (mb - ma)
    if db < da:
        n -= 1
    return n


def find_anchor(daily):
    """조건을 만족한 **첫 날**. 없으면 None.

    첫 날을 쓰는 이유는 docstring 마지막 절에 적었다 — 구간 최고점을 고르면
    룩어헤드가 된다.
    """
    ks = sorted(daily)
    if len(ks) < HIGH_WINDOW + 20:
        return None
    for i in range(HIGH_WINDOW, len(ks)):
        k = ks[i]
        window = [daily[x] for x in ks[i - HIGH_WINDOW:i + 1]]
        if daily[k] < max(window):
            continue
        # 12개월 전 가장 가까운 거래일
        y, m, d = int(k[:4]), int(k[5:7]), int(k[8:10])
        tgt = '%04d-%02d-%02d' % (y - 1, m, d)
        prior = [x for x in ks[:i] if x <= tgt]
        if not prior:
            continue
        base = daily[prior[-1]]
        if base <= 0:
            continue
        if (daily[k] / base - 1) * 100 >= RUNUP:
            return k, daily[k]
    return None


def classify(anchor_date, today):
    """앵커와 오늘 → (단계, 경과개월). 앵커가 없으면 (비활성, None)."""
    if not anchor_date:
        return INACTIVE, None
    el = months_between(anchor_date, today)
    if el < 0:
        return UNKNOWN, el
    if el > EXPIRE_MONTHS:
        return INACTIVE, el
    if el <= 6:
        return EARLY, el
    if el <= 12:
        return WATCH, el
    return TROUGH, el


def format_notice(stage, prev_stage, anchor, anchor_level, elapsed, now_level):
    lines = ['[급등 고점 단계] %s → %s' % (prev_stage, stage), '']
    if anchor:
        chg = (now_level / anchor_level - 1) * 100 if anchor_level else None
        lines.append('앵커 {} (코스피 {:,.0f}) 이후 {}개월째'
                     .format(anchor, anchor_level, elapsed))
        if chg is not None:
            lines.append('앵커 대비 현재 %+.1f%% (코스피 %.0f)'
                         % (chg, now_level))
    n = TROUGH_COUNT.get(stage)
    if n is not None:
        lines += ['', '과거 9사건 중 이 구간에서 최저점이 온 건수: **%d건**' % n]
        if stage == EARLY:
            lines.append('0~6개월에 최저점이 온 사례가 한 건도 없다 — '
                         '바닥을 주장할 근거가 없다.')
        elif stage == TROUGH:
            lines.append('최저점 중앙값이 13개월이다. 가장 많이 몰린 구간이다.')
    lines += ['',
              'n=9(반도체 4·상하이 2 쏠림)이고 통계 검정이 아니라 참조 분포다. '
              '코스피는 앵커 5개월째에 고점을 찍어 과거 어느 유형에도 '
              '깨끗이 맞지 않는다. 관찰용이고 매매 근거가 아니다.']
    return '\n'.join(lines)


class MeltupPhaseSimulator(BaseSimulator):
    """매매하지 않는다. 급등 고점 앵커로부터의 경과 단계만 알린다."""

    IS_ANALYZER = True
    IS_EOD = True       # 일봉 기반이고 하루 한 번이면 충분하다

    def __init__(self, initial_cash=0):
        super().__init__("Meltup", initial_cash)
        self.state.setdefault('stage', INACTIVE)
        self.state.setdefault('anchor', None)
        self.state.setdefault('anchor_level', None)
        self.state.setdefault('history', [])

    def get_universe(self):
        return []       # 종목을 고르지 않는다

    def run(self, candidates, current_prices=None):
        now = get_kst_now()
        today = now.strftime('%Y-%m-%d')
        prev_stage = self.state.get('stage', INACTIVE)

        daily, err = kospi_index.fetch_daily()
        if daily is None:
            # 조회 실패를 0이나 '비활성'으로 바꾸지 않는다 — 직전 상태를 유지한다.
            print('[Sim18 급등고점] 지수 조회 실패(%s) — 직전 상태 유지: %s'
                  % (err, prev_stage))
            self.state['last_error'] = err
            self.state['checked_at'] = now.strftime('%Y-%m-%d %H:%M:%S')
            self.save_state(current_prices)
            return []

        anchor = self.state.get('anchor')
        anchor_level = self.state.get('anchor_level')
        # 앵커가 없거나 만료됐으면 새로 찾는다. 있으면 **움직이지 않는다**.
        if not anchor or months_between(anchor, today) > EXPIRE_MONTHS:
            found = find_anchor(daily)
            if found:
                anchor, anchor_level = found
            else:
                anchor, anchor_level = None, None

        stage, elapsed = classify(anchor, today)
        last = daily[sorted(daily)[-1]]
        self.state.update(anchor=anchor, anchor_level=anchor_level,
                          elapsed=elapsed, kospi=last,
                          last_error=None,
                          checked_at=now.strftime('%Y-%m-%d %H:%M:%S'))
        if stage != prev_stage:
            self.state['stage'] = stage
            self.state['stage_since'] = today
            h = self.state.setdefault('history', [])
            h.append({'date': today, 'stage': stage, 'anchor': anchor,
                      'elapsed': elapsed})
            del h[:-200]
            self._notify(stage, prev_stage, anchor, anchor_level, elapsed,
                         last, now)
            print('[Sim18 급등고점] %s → %s | 앵커 %s, %s개월째'
                  % (prev_stage, stage, anchor, elapsed))
        else:
            print('[Sim18 급등고점] %s 유지 | 앵커 %s, %s개월째'
                  % (stage, anchor, elapsed))
        self.save_state(current_prices)
        return []       # 매매 신호를 내지 않는다

    def _notify(self, stage, prev_stage, anchor, anchor_level, elapsed,
                last, now):
        if alerts is None or stage == UNKNOWN:
            return
        # 첫 실행(판정불가/없음 → 비활성)은 사건이 아니라 기동이다.
        if prev_stage in (INACTIVE, UNKNOWN) and stage == INACTIVE:
            return
        try:
            alerts.send_alert_once(
                'meltup_phase_%s' % stage,
                format_notice(stage, prev_stage, anchor, anchor_level,
                              elapsed, last),
                now, cooldown_min=ALERT_COOLDOWN_MIN)
        except Exception as e:
            print('[Sim18 급등고점] 알림 실패: %s: %s' % (type(e).__name__, e))
