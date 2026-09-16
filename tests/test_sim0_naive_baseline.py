"""나우캐스트 예측은 naive(직전 실측값 유지) 한 모델만 남긴다.

리베로는 +1h/EOD breadth를 **속도 외삽**(velocity)으로 예측하다가, 기준선이
없어서 그 오차가 좋은 건지 나쁜 건지 말해주지 못했다. 그래서 naive(직전
실측값 그대로)를 나란히 적어 채점했고(2026-08-12), 단일 구간 노이즈를 완화한
smoothed_velocity를 세 번째로 붙였다(2026-08-19).

**2026-09-16: 표본이 쌓여 판정이 났다.** 세 모델이 다 있는 19거래일 교집합
(08-20~09-15) 실측 MAE:

    모델                  +1h(n=114)    EOD(n=126)
    naive                     6.91         10.90
    smoothed_velocity         9.80         14.80
    velocity                 10.10         15.64

일별 클러스터 t = +2.9~+5.4, naive보다 나은 날이 19일 중 1~4일. 08-19의 4일
표본 결론(velocity < naive)이 6배 표본에서도 방향 그대로였고 격차는 벌어졌다.
속도 외삽은 남은 시간만큼 노이즈를 늘리는 일을 하고 있었다.

그래서 두 velocity 계열을 예측 경로에서 내렸다. 부수 효과로 채점 로그가
하루 39건(3모델)에서 13건(1모델)으로 줄어, 같은 SCORE_LOG_MAX=1200이
50거래일이 아니라 약 92거래일을 보관한다 — 롤링 절단으로 초기 표본이
조용히 사라지는 일이 없어진다.

이 파일은 그 판정 이후의 계약을 고정한다: 예측 모델은 naive 하나이고,
calibration_log(공식 노출값)는 모델 교체로 **한 자리도 바뀌지 않는다.**
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import datetime

from src.strategy.simulators.sim0_libero import LiberoSimulator

NOW_09 = datetime(2026, 8, 12, 9, 0)
NOW_10 = datetime(2026, 8, 12, 10, 0)
NOW_11 = datetime(2026, 8, 12, 11, 0)
EOD_RUN = datetime(2026, 8, 12, 15, 40)


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


def test_naive_is_the_only_forecast_model(tmp_path):
    """09-16 판정 이후 예측 경로에 남는 모델은 naive 하나다."""
    sim = _sim(tmp_path)
    sim.update_nowcast(50.0, now_kst=NOW_10)
    sim.update_nowcast(60.0, now_kst=NOW_11)

    h1 = _preds(sim, type='h1', made_at='11:00')
    eod = _preds(sim, type='eod', made_at='11:00')
    assert {p['model'] for p in h1} == {'naive'}
    assert {p['model'] for p in eod} == {'naive'}


def test_velocity_models_are_no_longer_produced(tmp_path):
    """제거의 반대 방향 가드 — 되살리면 이 테스트가 잡는다.

    옛 `test_velocity_forecast_is_unchanged`(velocity = 마지막값 + 속도 = 70.0)를
    뒤집은 것이다. 그 식을 지켰는지가 아니라, 그 식이 더는 로그를 만들지
    않는지를 본다."""
    sim = _sim(tmp_path)
    sim.update_nowcast(50.0, now_kst=NOW_10)
    sim.update_nowcast(60.0, now_kst=NOW_11)
    sim.finalize_eod(58.0, now_kst=EOD_RUN)

    models = {p['model'] for p in sim.state['intraday']['predictions']}
    models |= {s['model'] for s in sim.state['intraday_score_log']}
    assert models == {'naive'}
    assert not hasattr(LiberoSimulator, 'EOD_DAMPING')
    assert not hasattr(LiberoSimulator, 'VELOCITY_SMOOTH_WINDOW')


def test_naive_prediction_is_just_the_last_measurement(tmp_path):
    """naive는 '아무 것도 하지 않는' 예측이다 — 직전 실측값 그대로."""
    sim = _sim(tmp_path)
    sim.update_nowcast(50.0, now_kst=NOW_10)
    sim.update_nowcast(60.0, now_kst=NOW_11)

    naive = _preds(sim, type='h1', made_at='11:00', model='naive')
    assert [p['value'] for p in naive] == [60.0]


def test_scores_still_carry_the_model_field(tmp_path):
    """모델이 하나뿐이어도 채점 로그는 model을 계속 적는다 — 나중에 모델을
    다시 둘로 늘릴 때 로그 스키마가 조용히 갈리지 않게."""
    sim = _sim(tmp_path)
    sim.update_nowcast(50.0, now_kst=NOW_10)
    sim.update_nowcast(60.0, now_kst=NOW_11)
    sim.finalize_eod(58.0, now_kst=EOD_RUN)

    eod_scores = [s for s in sim.state['intraday_score_log'] if s['type'] == 'eod']
    assert eod_scores
    assert {s['model'] for s in eod_scores} == {'naive'}
    assert all(s['actual'] == 58.0 for s in eod_scores)


def test_one_model_a_day_fits_ninety_trading_days():
    """모델 수를 줄였으니 같은 상한이 더 긴 기간을 보관한다 — 상한을 같이
    줄이면 제거의 부수 이익(초기 표본 보존)이 사라진다.

    하루 13건(h1 6 + eod 7) × 90거래일 = 1170 ≤ SCORE_LOG_MAX."""
    assert LiberoSimulator.SCORE_LOG_MAX >= 13 * 90


def test_one_day_of_nowcast_logs_thirteen_scores(tmp_path):
    """위 예산의 '하루 13건'이 실제 산출과 맞는지 — 상수 옆의 주석이 아니라
    코드가 근거가 되게."""
    sim = _sim(tmp_path)
    for hour in range(9, 16):
        sim.update_nowcast(50.0 + hour, now_kst=datetime(2026, 8, 12, hour, 0))
    sim.finalize_eod(58.0, now_kst=EOD_RUN)

    log = sim.state['intraday_score_log']
    assert len([s for s in log if s['type'] == 'eod']) == 7
    assert len([s for s in log if s['type'] == 'h1']) == 6


def test_calibration_gap_uses_the_days_first_eod_forecast(tmp_path):
    """calibration_log는 '그날 첫 EOD 예측 vs 확정 실측'이다. 그 자리를 집던
    조건이 `model == 'velocity'`였는데, 그 모델이 사라지면 조건이 영원히
    거짓이 되고 갭 차트가 **조용히 안 쓰인다** — 남은 모델로 옮겨야 한다."""
    sim = _sim(tmp_path)
    sim.update_nowcast(50.0, now_kst=NOW_10)
    sim.update_nowcast(60.0, now_kst=NOW_11)
    sim.finalize_eod(58.0, now_kst=EOD_RUN)

    assert sim.state['calibration_log'], 'calibration_log가 아예 기록되지 않았다'
    first_eod = _preds(sim, type='eod')[0]['value']
    assert sim.state['calibration_log'][-1]['libero_breadth'] == first_eod
    assert sim.state['calibration_log'][-1]['v'] == 2


def test_calibration_value_is_bit_identical_to_what_velocity_wrote(tmp_path):
    """**모델을 갈아도 공식 노출값은 한 자리도 바뀌지 않아야 한다.**

    그날 첫 예측 버킷(09:00)에는 관측이 1개뿐이다. 그래서 옛 식
    `last + velocity * hours_left * EOD_DAMPING`의 velocity는 `len(meas) >= 2`가
    거짓이라 0이고, smoothed_velocity도 `k = min(4, 0) = 0`이라 0이다 — 세 모델의
    예측이 전부 `last`로 같아진다 — db-data 라이브 상태의 22거래일 전부(22/22)에서
    그날 첫 버킷은 09:00이고 세 모델의 EOD 예측이 동일했다. naive만 남겨도
    calibration_log에 들어가는 값은 그래서 동일하다.

    이 성질이 깨지는 건 그날 첫 버킷에 관측이 2개 이상 들어올 때뿐이다 — 그때는
    갭 차트가 과거와 다른 계산의 값을 그리게 되므로 여기서 고정해 둔다."""
    sim = _sim(tmp_path)
    first_measurement = 50.0
    sim.update_nowcast(first_measurement, now_kst=NOW_09)   # 그날 첫 런: 관측 1개
    sim.update_nowcast(60.0, now_kst=NOW_10)
    sim.update_nowcast(71.0, now_kst=NOW_11)
    sim.finalize_eod(58.0, now_kst=EOD_RUN)

    legacy_velocity = 0.0          # len(meas) >= 2 가 거짓
    legacy_hours_left = 15.5 - 9.0
    legacy_eod_pred = round(first_measurement
                            + legacy_velocity * legacy_hours_left * 0.5, 1)

    assert legacy_eod_pred == first_measurement
    entry = sim.state['calibration_log'][-1]
    assert entry['libero_breadth'] == legacy_eod_pred
    assert entry['gap'] == round(legacy_eod_pred - 58.0, 1)


def test_first_bucket_prediction_equals_the_single_measurement(tmp_path):
    """위 불변의 전제 — 관측이 1개인 버킷의 예측은 그 관측값 자체다."""
    sim = _sim(tmp_path)
    sim.update_nowcast(50.0, now_kst=NOW_09)

    assert [p['value'] for p in _preds(sim, made_at='09:00')] == [50.0, 50.0]
