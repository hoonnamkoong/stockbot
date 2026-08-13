"""개장 직후 "아직 안 움직임"을 "전부 하락"으로 적지 않는다.

2026-08-06부터 리베로 예측이 통째로 망가졌다. calibration_log:

    08-05   pred 73.0 / actual 84.0   gap -11.0    ← 정상
    08-06   pred  0.0 / actual 44.0   gap -44.0    ← 여기서 끊김
    08-13   pred  3.0 / actual 66.0   gap -63.0

실측(actual)은 EOD CSV라 멀쩡했다. **라이브 breadth만 죽었다.**

`regime_observations.csv`를 보면 원인이 한 줄로 드러난다 — 그날 첫 관측 시각이
08-06부터 09:01 → 09:00으로 앞당겨졌다:

    08-05  09:01  breadth 73.0  momentum 1.44
    08-06  09:00  breadth  0.0  momentum 0.00
    08-13  09:00  breadth  3.0  momentum 0.00   (10분 뒤 95.0)

`momentum 0.00`이 증거다. 등락률 중앙값이 정확히 0이면 전 종목 보합인데,
개장 직후엔 그게 "보합"이 아니라 **"아직 측정 전"**이다. 네이버 시총 페이지가
09:00 정각엔 전일 종가 그대로라 100종목이 전부 0.00%로 보인다.

`_fetch_top100_breadth`에는 표본 수 가드(80 미만이면 None)가 있었지만
"표본은 100개인데 전부 안 움직였다"를 거르는 가드가 없었다. 그래서 breadth 0이
정상 측정값으로 기록되고, `finalize_eod`가 **그날 첫 EOD 예측**을 calibration에
쓰므로 예측값이 통째로 0이 됐다.

타이밍 변경은 이 결함을 **드러냈을 뿐** 원인이 아니다. 0을 측정값으로 적는
코드가 원인이고, 09:01에 돌던 시절에도 잠재해 있었다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers.trade_engine import MIN_MOVED_RATIO, TradeEngineWorker


def _bm(rates):
    return TradeEngineWorker._breadth_momentum(rates)


def test_all_flat_is_not_measurable():
    """08-06 09:00이 정확히 이 모양이다 — 100종목 전부 0.00%."""
    assert _bm([0.0] * 100) is None


def test_almost_all_flat_is_not_measurable():
    """08-13 09:00: 3종목만 틱이 나왔고 97종목이 0.00%였다. breadth 3.0이
    기록됐는데 10분 뒤 실제 값은 95.0이었다."""
    assert _bm([1.2, 0.5, 0.8] + [0.0] * 97) is None


def test_just_enough_movement_is_measurable():
    moved = int(100 * MIN_MOVED_RATIO)
    out = _bm([0.5] * moved + [0.0] * (100 - moved))

    assert out is not None
    assert out[0] == moved   # 움직인 만큼이 그대로 상승 비율


def test_small_samples_are_not_rejected_by_an_absolute_count():
    """이 함수는 표본 크기를 가정하지 않는다. 절대 개수로 자르면 4건짜리
    호출이 조용히 '측정 불가'가 된다(기존 테스트가 그걸 잡았다)."""
    assert _bm([2.0, -1.0, 3.0, -4.0]) is not None


def test_a_genuinely_bearish_open_is_still_measured():
    """전 종목이 **하락**한 날은 측정 가능하다. 0.00과 -1.2는 다르다 —
    이 구분을 놓치면 진짜 폭락일을 '측정 불가'로 버린다."""
    out = _bm([-1.2] * 100)

    assert out is not None
    assert out[0] == 0.0, '하락 100%면 상승 비율은 0이 맞다'


def test_mixed_day_is_unaffected():
    out = _bm([2.0, -1.0, 3.0, -4.0] * 25)

    assert out is not None
    assert out[0] == 50.0


def test_empty_is_still_none():
    assert _bm([]) is None
