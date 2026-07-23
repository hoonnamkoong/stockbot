import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.strategy.simulators.sim0_libero import classify_by_score

FIX = os.path.join(os.path.dirname(__file__), 'fixtures', 'sim0_calibration_snapshot.json')


def _load():
    with open(FIX, encoding='utf-8') as f:
        return json.load(f)['calibration_log']


def truth_regime(actual_breadth):
    """확정 실측 breadth로 정의한 그날의 기준 국면."""
    if actual_breadth >= 60:
        return "BULL"
    if actual_breadth <= 35:
        return "BEAR"
    return "SIDEWAYS"


def _accuracy(cal, theta_bull, theta_bear):
    hit = bull_hit = bull_tot = 0
    for e in cal:
        truth = truth_regime(e['actual_kospi_breadth'])
        pred = classify_by_score(e['bull_score'], theta_bull, theta_bear)
        hit += (pred == truth)
        if truth == "BULL":
            bull_tot += 1
            bull_hit += (pred == "BULL")
    return hit / len(cal), (bull_hit / bull_tot if bull_tot else None)


def _old_accuracy(cal):
    hit = bull_hit = bull_tot = 0
    for e in cal:
        truth = truth_regime(e['actual_kospi_breadth'])
        hit += (e.get('regime') == truth)
        if truth == "BULL":
            bull_tot += 1
            bull_hit += (e.get('regime') == "BULL")
    return hit / len(cal), (bull_hit / bull_tot if bull_tot else None)


def sweep_best(cal):
    """θ_bull(45~70), θ_bear(20~45) 스윕. 전체 적중률 최대, 동률 시 상승장 포착률 우선."""
    best = None
    for tb in range(45, 71, 1):
        for tr in range(20, 46, 1):
            if tr >= tb:
                continue
            acc, bull = _accuracy(cal, tb, tr)
            key = (acc, bull or 0)
            if best is None or key > best[0]:
                best = (key, tb, tr, acc, bull)
    return best


def test_backtest_report_and_gate():
    cal = _load()
    assert len(cal) >= 20, "검증 표본 부족 — 픽스처 재수집 필요"
    old_acc, old_bull = _old_accuracy(cal)
    _, tb, tr, new_acc, new_bull = sweep_best(cal)
    print(f"\n[구 로직]  적중률 {old_acc:.1%}, 상승장 포착 {old_bull}")
    print(f"[신 밴드]  최적 θ_bull={tb} θ_bear={tr} → 적중률 {new_acc:.1%}, 상승장 포착 {new_bull}")
    # 배포 게이트: 신규가 구 대비 전체 적중률·상승장 포착 둘 다 개선(비열등)
    assert new_acc > old_acc, f"전체 적중률 개선 없음 ({new_acc:.1%} vs {old_acc:.1%}) — 배포 보류"
    assert (new_bull or 0) >= (old_bull or 0), "상승장 포착 후퇴 — 배포 보류"
