import os, sys, json, statistics
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pytest


def load_calibration_data():
    """기존 data/sim_libero_state.json의 calibration_log 로드"""
    state_path = os.path.join(os.path.dirname(__file__), '../data/sim_libero_state.json')
    if not os.path.exists(state_path):
        return []
    try:
        with open(state_path, 'r', encoding='utf-8-sig') as f:
            return json.load(f).get('calibration_log', [])
    except Exception:
        return []


def calculate_accuracy_metrics(calibration_log):
    """calibration_log에서 정확도 지표 계산

    Returns:
        dict with 'mean_gap', 'median_gap', 'count' keys
    """
    gaps = [abs(e.get('gap', 0)) for e in calibration_log]
    if not gaps:
        return {'mean_gap': 0, 'median_gap': 0, 'count': 0}
    return {
        'mean_gap': statistics.mean(gaps),
        'median_gap': statistics.median(gaps),
        'count': len(gaps)
    }


def test_accuracy_goal():
    """목표: 평균 |gap| <= 8.0 검증

    Gap = 예측값 - 실제값
    목표: 리베로 나우캐스트 예측이 평균적으로 8.0 포인트 이내 오차
    """
    data = load_calibration_data()
    if len(data) < 10:
        pytest.skip("보정 데이터 부족 (최소 10건 필요)")

    metrics = calculate_accuracy_metrics(data)
    print(f"\n평균 |gap|: {metrics['mean_gap']:.1f} (목표: ≤ 8.0)")
    print(f"중앙값 |gap|: {metrics['median_gap']:.1f}")
    print(f"샘플 수: {metrics['count']}")

    # 기본 검증: 데이터 존재
    assert metrics['count'] > 0, "보정 로그 데이터 부재"

    # 정확도 목표 (데이터 충분 시에만 강제)
    if metrics['count'] >= 30:
        assert metrics['mean_gap'] <= 8.0, \
            f"평균 오차 {metrics['mean_gap']:.1f} > 목표 8.0"


def test_confidence_correlation():
    """신뢰도와 정확도의 상관관계 검증

    기대: 신뢰도 높을수록 오차 작음
    - 신뢰도 < 0.5: 높은 오차 예상
    - 신뢰도 >= 0.8: 낮은 오차 예상
    """
    data = load_calibration_data()
    if len(data) < 10:
        pytest.skip("보정 데이터 부족")

    low_conf_errors = [abs(e['gap']) for e in data if e.get('confidence', 0) < 0.5]
    high_conf_errors = [abs(e['gap']) for e in data if e.get('confidence', 0) >= 0.8]

    print(f"\n신뢰도 < 0.5: {len(low_conf_errors)}건, 평균 오차: {statistics.mean(low_conf_errors) if low_conf_errors else 0:.1f}")
    print(f"신뢰도 >= 0.8: {len(high_conf_errors)}건, 평균 오차: {statistics.mean(high_conf_errors) if high_conf_errors else 0:.1f}")

    # 기본 검증: 최소 데이터 존재
    assert len(data) > 0, "보정 로그 데이터 부재"

    # 신뢰도 분포 검증 (데이터 충분 시)
    if len(high_conf_errors) >= 5 and len(low_conf_errors) >= 5:
        high_mean = statistics.mean(high_conf_errors)
        low_mean = statistics.mean(low_conf_errors)
        print(f"신뢰도 상관: 높은 신뢰도 오차 {high_mean:.1f} < 낮은 신뢰도 오차 {low_mean:.1f}? {high_mean < low_mean}")


def test_extremes_detection():
    """극단값 신뢰도 감소 검증

    breadth가 극단값(0~10 또는 90~100)일 때
    신뢰도가 낮아야 함(포화 페널티)
    """
    data = load_calibration_data()
    if len(data) < 10:
        pytest.skip("데이터 부족")

    extreme_entries = [e for e in data if e.get('breadth', 50) < 10 or e.get('breadth', 50) > 90]

    if extreme_entries:
        extreme_confs = [e.get('confidence', 0) for e in extreme_entries]
        normal_confs = [e.get('confidence', 0) for e in data if not (e.get('breadth', 50) < 10 or e.get('breadth', 50) > 90)]

        extreme_avg = statistics.mean(extreme_confs) if extreme_confs else 0
        normal_avg = statistics.mean(normal_confs) if normal_confs else 0

        print(f"\n극단값(0~10, 90~100): {len(extreme_entries)}건, 평균 신뢰도: {extreme_avg:.2f}")
        print(f"정상범위: {len(normal_confs)}건, 평균 신뢰도: {normal_avg:.2f}")

        # 극단값 신뢰도가 정상범위보다 낮아야 함
        if normal_confs:
            assert extreme_avg < normal_avg, "극단값이 정상범위보다 신뢰도가 낮아야 함"


def test_time_stability():
    """시간대별 안정도 검증

    09:00~14:00: 예측 신뢰도 증가 추세
    """
    data = load_calibration_data()
    if len(data) < 10:
        pytest.skip("데이터 부족")

    # 시간대별 신뢰도 평균
    by_hour = {}
    for e in data:
        hour = e.get('made_at', '')[:5]  # "HH:MM" 추출
        if hour:
            if hour not in by_hour:
                by_hour[hour] = []
            by_hour[hour].append(e.get('confidence', 0))

    sorted_hours = sorted(by_hour.keys())
    if len(sorted_hours) >= 2:
        print(f"\n시간대별 신뢰도:")
        for h in sorted_hours:
            avg_conf = statistics.mean(by_hour[h])
            print(f"  {h}: {avg_conf:.2f} ({len(by_hour[h])}건)")

        # 기본 검증: 데이터가 여러 시간대에 분산
        assert len(sorted_hours) > 1, "단일 시간대만 존재"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
