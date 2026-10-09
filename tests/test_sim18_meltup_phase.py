"""Sim18 급등 고점 단계 — 앵커 탐색과 단계 경계.

이 심의 전부는 "앵커로부터 몇 달째인가"다. 그래서 여기서 지키는 것은 둘 —
  ① 앵커를 **첫 조건 만족일**에 잡고 그 뒤로 **움직이지 않는가**
     (탐색 단계에서 '구간 최고점'으로 옮겼다가 룩어헤드를 만들었다)
  ② 단계 경계가 과거 최저점 분포(0~6=0건 / 7~12=2건 / 13~24=7건)와 맞는가
"""
import pytest

from src.strategy.simulators.sim18_meltup_phase import (
    EARLY, EXPIRE_MONTHS, INACTIVE, TROUGH, TROUGH_COUNT, WATCH,
    classify, find_anchor, format_notice, months_between,
)


def _series(start_level=100.0, days=400, daily_gain=0.0):
    """연속 거래일 가짜 일봉. 날짜는 단순 증가라 달력과 무관하다."""
    out = {}
    lv = start_level
    for i in range(days):
        y = 2024 + i // 360
        rem = i % 360
        out['%04d-%02d-%02d' % (y, rem // 30 + 1, rem % 30 + 1)] = lv
        lv *= (1 + daily_gain)
    return out


# ── 개월 계산 ────────────────────────────────────────
@pytest.mark.parametrize('a,b,n', [
    ('2026-01-27', '2026-01-27', 0),
    ('2026-01-27', '2026-02-26', 0),      # 일자가 모자라면 아직 1개월이 아니다
    ('2026-01-27', '2026-02-27', 1),
    ('2026-01-27', '2026-10-08', 8),      # 코스피 실제 값
    ('2026-01-27', '2027-01-27', 12),
    ('2025-01-31', '2026-02-01', 12),   # 12개월 1일 — 아직 13개월이 아니다
])
def test_months_between(a, b, n):
    assert months_between(a, b) == n


# ── 단계 경계 ────────────────────────────────────────
@pytest.mark.parametrize('elapsed,stage', [
    (0, EARLY), (6, EARLY), (7, WATCH), (12, WATCH),
    (13, TROUGH), (24, TROUGH),
])
def test_stage_boundaries(elapsed, stage):
    y, m = 2026, 1 + elapsed
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    assert classify('2026-01-15', '%04d-%02d-15' % (y, m))[0] == stage


def test_no_anchor_is_inactive():
    assert classify(None, '2026-10-08') == (INACTIVE, None)


def test_anchor_expires_after_24_months():
    assert classify('2024-01-15', '2026-02-15')[0] == INACTIVE
    assert classify('2024-01-15', '2026-01-15')[0] == TROUGH


def test_trough_counts_match_the_research():
    """알림에 싣는 건수가 연구 결과와 어긋나면 사용자가 잘못된 수를 본다."""
    assert TROUGH_COUNT[EARLY] == 0, '0~6개월에 최저점이 온 사례는 없었다'
    assert TROUGH_COUNT[WATCH] == 2
    assert TROUGH_COUNT[TROUGH] == 7
    assert sum(TROUGH_COUNT.values()) == 9, '완결 사건은 9개다'


# ── 앵커 탐색 ────────────────────────────────────────
def test_no_anchor_when_runup_is_small():
    # 하루 0.1%면 252일에 약 +28% — 문턱 +100%에 못 미친다
    assert find_anchor(_series(daily_gain=0.001)) is None


def test_anchor_is_the_first_qualifying_day_not_the_highest():
    """구간 최고점을 고르면 룩어헤드다 — 첫 날이어야 한다."""
    d = _series(days=400, daily_gain=0.004)   # 252일에 약 +170%
    got = find_anchor(d)
    assert got is not None
    ks = sorted(d)
    anchor, level = got
    # 첫 자격일이므로 뒤에 더 높은 날이 반드시 남아 있다
    later = [d[k] for k in ks if k > anchor]
    assert later and max(later) > level, '더 높은 날이 뒤에 있어야 한다'
    # 그리고 그 앵커 이전에는 자격일이 없다
    before = {k: v for k, v in d.items() if k <= anchor}
    assert find_anchor(before)[0] == anchor


def test_short_series_has_no_anchor():
    assert find_anchor(_series(days=100, daily_gain=0.01)) is None


# ── 알림 본문 ────────────────────────────────────────
def test_notice_carries_the_count_and_the_limits():
    t = format_notice(EARLY, INACTIVE, '2026-01-27', 5084.9, 3, 6625.9)
    assert '0건' in t, '조기 구간의 핵심은 최저점이 0건이라는 사실이다'
    assert '관찰용' in t and 'n=9' in t, '한계가 본문에 있어야 한다'
    assert '2026-01-27' in t


def test_notice_marks_the_trough_window():
    t = format_notice(TROUGH, WATCH, '2026-01-27', 5084.9, 13, 4000.0)
    assert '7건' in t and '13개월' in t


# ── 매매하지 않는다 ──────────────────────────────────
def test_analyzer_flags_and_empty_universe():
    from src.strategy.simulators.sim18_meltup_phase import (
        MeltupPhaseSimulator)
    assert MeltupPhaseSimulator.IS_ANALYZER is True
    assert MeltupPhaseSimulator.IS_EOD is True
    sim = MeltupPhaseSimulator.__new__(MeltupPhaseSimulator)
    assert sim.get_universe() == []
    assert EXPIRE_MONTHS == 24
