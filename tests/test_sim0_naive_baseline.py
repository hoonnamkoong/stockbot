"""나우캐스트 예측에 나이브 기준선을 붙인다.

리베로는 +1h/EOD breadth를 **속도 외삽**으로 예측하고 실측으로 채점한다. 그런데
비교 대상이 없어서, 쌓이는 오차가 좋은 건지 나쁜 건지 말해주지 못했다 —
"속도 외삽이 그냥 직전 값을 쓰는 것보다 나은가"에 답할 수 없는 상태였다.

기준선(naive/persistence)은 예측 평가의 최소 요건이다. 같은 시각·같은 대상에
대해 "직전 실측값 그대로"를 함께 적어 두면, 기존 채점 경로가 두 값을 같이
채점하고 로그만으로 우열이 나온다.

이건 2026-07-01 PR #1이 P0/P1 병렬 채점으로 제안했던 아이디어인데, 그 브랜치는
main이 299커밋 앞서면서 통째로 낡았다. 아이디어만 옮긴다.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime

from src.strategy.simulators.sim0_libero import LiberoSimulator

NOW_10 = datetime(2026, 8, 12, 10, 0)
NOW_11 = datetime(2026, 8, 12, 11, 0)


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


def test_naive_baseline_is_recorded_next_to_velocity_forecast(tmp_path):
    """같은 시각·같은 대상에 대해 두 모델의 예측이 함께 남아야 비교가 성립한다."""
    sim = _sim(tmp_path)
    sim.update_nowcast(50.0, now_kst=NOW_10)
    sim.update_nowcast(60.0, now_kst=NOW_11)

    h1 = _preds(sim, type='h1', made_at='11:00')
    assert {p['model'] for p in h1} == {'velocity', 'naive'}


def test_naive_prediction_is_just_the_last_measurement(tmp_path):
    """기준선은 '아무 것도 하지 않는' 예측이다 — 직전 실측값 그대로."""
    sim = _sim(tmp_path)
    sim.update_nowcast(50.0, now_kst=NOW_10)
    sim.update_nowcast(60.0, now_kst=NOW_11)

    naive = _preds(sim, type='h1', made_at='11:00', model='naive')
    assert [p['value'] for p in naive] == [60.0]


def test_velocity_forecast_is_unchanged(tmp_path):
    """회귀 방지 — 기존 속도 외삽(마지막값 + 속도)은 그대로여야 한다."""
    sim = _sim(tmp_path)
    sim.update_nowcast(50.0, now_kst=NOW_10)
    sim.update_nowcast(60.0, now_kst=NOW_11)

    vel = _preds(sim, type='h1', made_at='11:00', model='velocity')
    assert [p['value'] for p in vel] == [70.0]     # 60 + (60-50)


def test_both_models_are_scored_separately(tmp_path):
    """채점 로그가 모델을 구분해야 나중에 우열을 계산할 수 있다."""
    sim = _sim(tmp_path)
    sim.update_nowcast(50.0, now_kst=NOW_10)
    sim.update_nowcast(60.0, now_kst=NOW_11)
    sim.finalize_eod(58.0, now_kst=datetime(2026, 8, 12, 15, 40))

    eod_scores = [s for s in sim.state['intraday_score_log'] if s['type'] == 'eod']
    assert {s['model'] for s in eod_scores} == {'velocity', 'naive'}
    naive = [s for s in eod_scores if s['model'] == 'naive']
    assert all(s['actual'] == 58.0 for s in naive)


def test_score_log_still_holds_fifty_days_with_two_models():
    """모델을 둘로 늘리면 하루 기록량이 2배다 — 상한을 그대로 두면 보관 기간이
    조용히 절반(50일→25일)으로 줄어든다. 비교 표본을 늘리려고 한 변경이
    표본 기간을 깎으면 앞뒤가 안 맞는다."""
    assert LiberoSimulator.SCORE_LOG_MAX >= 16 * 50


def test_naive_baseline_does_not_disturb_calibration_gap(tmp_path):
    """calibration_log는 '그날 첫 EOD 예측 vs 실측'이다 — 기준선이 그 자리를
    차지하면 프론트 갭 차트의 의미가 바뀐다. 예측 모델(velocity)이어야 한다."""
    sim = _sim(tmp_path)
    sim.update_nowcast(50.0, now_kst=NOW_10)
    sim.update_nowcast(60.0, now_kst=NOW_11)
    sim.finalize_eod(58.0, now_kst=datetime(2026, 8, 12, 15, 40))

    first_eod_velocity = _preds(sim, type='eod', model='velocity')[0]['value']
    assert sim.state['calibration_log'][-1]['libero_breadth'] == first_eod_velocity
