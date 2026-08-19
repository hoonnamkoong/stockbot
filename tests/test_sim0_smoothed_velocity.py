"""나우캐스트에 평활 속도(smoothed_velocity) 모델을 세 번째로 붙인다.

08-19 실측: velocity(관측 두 개 사이 단일 차분을 남은 시간만큼 그대로 외삽)가
naive(직전값 유지)보다 못했다 — EOD MAE 12.1 vs 8.8(같은 4일 비교). 원인은
velocity 자체가 약 10분짜리 단일 구간의 노이즈라, 남은 시간에 곱해 늘리면
튄 값이 그대로 증폭되기 때문이다.

smoothed_velocity는 최근 VELOCITY_SMOOTH_WINDOW개 구간의 평균 변화율을 써서
단일 구간의 튐을 상쇄한다. 감쇠(EOD_DAMPING)나 클램프 같은 나머지 로직은
velocity와 완전히 같게 둬서, "속도를 평활화한 효과"만 골라 비교할 수 있게
한다 — naive를 붙였을 때(test_sim0_naive_baseline.py)와 같은 방식으로,
calibration_log(공식 노출값)는 건드리지 않고 intraday_score_log에서만
나란히 채점해 표본을 쌓는다.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.sim0_libero import LiberoSimulator

NOW_09 = datetime(2026, 8, 12, 9, 0)
NOW_10 = datetime(2026, 8, 12, 10, 0)
NOW_11 = datetime(2026, 8, 12, 11, 0)
NOW_12 = datetime(2026, 8, 12, 12, 0)
NOW_13 = datetime(2026, 8, 12, 13, 0)


def _sim(tmp_path):
    s = object.__new__(LiberoSimulator)
    s.state = {}
    s.state_file = str(tmp_path / 's.json')
    s.log_file = str(tmp_path / 's.log')
    s.csv_file = str(tmp_path / 's.csv')
    s.save_state = lambda *a, **k: None
    return s


def _preds(sim, **kw):
    out = sim.state['intraday']['predictions']
    return [p for p in out if all(p.get(k) == v for k, v in kw.items())]


def test_smoothed_velocity_is_recorded_next_to_the_others(tmp_path):
    """세 모델의 예측이 같은 시각·같은 대상에 함께 남아야 비교가 성립한다."""
    sim = _sim(tmp_path)
    sim.update_nowcast(50.0, now_kst=NOW_10)
    sim.update_nowcast(60.0, now_kst=NOW_11)

    h1 = _preds(sim, type='h1', made_at='11:00')
    assert {p['model'] for p in h1} == {'velocity', 'smoothed_velocity', 'naive'}


def test_smoothed_velocity_degenerates_to_raw_velocity_with_only_two_points(tmp_path):
    """관측이 둘뿐이면 평균낼 구간이 하나라 velocity와 같아야 한다."""
    sim = _sim(tmp_path)
    sim.update_nowcast(50.0, now_kst=NOW_10)
    sim.update_nowcast(60.0, now_kst=NOW_11)

    vel = _preds(sim, type='h1', made_at='11:00', model='velocity')[0]['value']
    smooth = _preds(sim, type='h1', made_at='11:00', model='smoothed_velocity')[0]['value']
    assert smooth == vel == 70.0  # 60 + (60-50)


def test_smoothed_velocity_averages_recent_intervals(tmp_path):
    """단일 구간이 튀어도 최근 구간들의 평균 변화율로 완화돼야 한다.

    09:00=30, 10:00=32, 11:00=34, 12:00=50(튐, +16) — 직전 한 칸(velocity)은
    +16이지만, 최근 3구간 평균(smoothed_velocity, window=4→len(meas)-1=3)은
    (50-30)/3=+6.67이어야 한다."""
    sim = _sim(tmp_path)
    sim.update_nowcast(30.0, now_kst=NOW_09)
    sim.update_nowcast(32.0, now_kst=NOW_10)
    sim.update_nowcast(34.0, now_kst=NOW_11)
    sim.update_nowcast(50.0, now_kst=NOW_12)

    vel = _preds(sim, type='h1', made_at='12:00', model='velocity')[0]['value']
    smooth = _preds(sim, type='h1', made_at='12:00', model='smoothed_velocity')[0]['value']
    assert vel == 66.0                                     # 50 + (50-34)
    assert smooth == round(50.0 + (50.0 - 30.0) / 3, 1)     # 50 + 평균변화율 6.67
    assert smooth < vel, '단일 구간 튐이 평활화로 완화돼야 한다'


def test_smoothed_velocity_window_caps_at_the_configured_size(tmp_path):
    """구간이 VELOCITY_SMOOTH_WINDOW보다 많이 쌓여도 그 개수만큼만 평균낸다."""
    sim = _sim(tmp_path)
    sim.update_nowcast(10.0, now_kst=NOW_09)   # 이 값이 window=4 안에 포함돼야 함
    sim.update_nowcast(20.0, now_kst=NOW_10)
    sim.update_nowcast(22.0, now_kst=NOW_11)
    sim.update_nowcast(24.0, now_kst=NOW_12)
    sim.update_nowcast(30.0, now_kst=NOW_13)

    smooth = _preds(sim, type='h1', made_at='13:00', model='smoothed_velocity')[0]['value']
    # len(meas)=5, k=min(4, 4)=4 → (30-10)/4=5.0, 09:00(10.0)이 포함돼야 함
    assert smooth == round(30.0 + (30.0 - 10.0) / 4, 1)


def test_smoothed_velocity_is_scored_separately(tmp_path):
    sim = _sim(tmp_path)
    sim.update_nowcast(50.0, now_kst=NOW_10)
    sim.update_nowcast(60.0, now_kst=NOW_11)
    sim.finalize_eod(58.0, now_kst=datetime(2026, 8, 12, 15, 40))

    eod_scores = [s for s in sim.state['intraday_score_log'] if s['type'] == 'eod']
    assert {s['model'] for s in eod_scores} == {'velocity', 'smoothed_velocity', 'naive'}
    smoothed = [s for s in eod_scores if s['model'] == 'smoothed_velocity']
    assert all(s['actual'] == 58.0 for s in smoothed)


def test_score_log_still_holds_fifty_days_with_three_models():
    """모델이 셋이면 하루 기록량이 1.5배(2→3)다. 상한을 그대로 두면 보관 기간이
    조용히 줄어든다 — 표본을 늘리려는 변경이 표본 기간을 깎으면 앞뒤가 안 맞는다."""
    assert LiberoSimulator.SCORE_LOG_MAX >= 24 * 50


def test_velocity_and_naive_forecasts_are_unchanged(tmp_path):
    """회귀 방지 — 기존 두 모델은 smoothed_velocity 추가와 무관하게 그대로여야 한다."""
    sim = _sim(tmp_path)
    sim.update_nowcast(50.0, now_kst=NOW_10)
    sim.update_nowcast(60.0, now_kst=NOW_11)

    vel = _preds(sim, type='h1', made_at='11:00', model='velocity')
    naive = _preds(sim, type='h1', made_at='11:00', model='naive')
    assert [p['value'] for p in vel] == [70.0]
    assert [p['value'] for p in naive] == [60.0]


def test_smoothed_velocity_does_not_disturb_calibration_gap(tmp_path):
    """calibration_log는 '그날 첫 EOD 예측 vs 실측'이다 — 공식 노출값은 여전히
    velocity여야 한다. smoothed_velocity는 표본을 쌓는 동안 옆에서만 채점된다."""
    sim = _sim(tmp_path)
    sim.update_nowcast(50.0, now_kst=NOW_10)
    sim.update_nowcast(60.0, now_kst=NOW_11)
    sim.finalize_eod(58.0, now_kst=datetime(2026, 8, 12, 15, 40))

    first_eod_velocity = _preds(sim, type='eod', model='velocity')[0]['value']
    assert sim.state['calibration_log'][-1]['libero_breadth'] == first_eod_velocity
