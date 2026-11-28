"""리베로 bull_score 입력 — 이력이 없을 때 0.0을 지어내지 않는다.

배경(2026-11-28): sparkline_price 생산자가 제거돼 후보의 `sparkline_price`가 항상 []가
됐고, calc_period_change([])·ADX 0.0 폴백이 모든 후보에 0.0을 넣었다. 그 값이
momentum/trend → bull_score → 일별 국면 로그·엑셀·레이더 차트로 흘렀다.
0점은 '최악의 장'이라 사람이 그 숫자로 시장을 판단한다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.sim0_libero import LiberoSimulator


def _sim(tmp_path):
    s = LiberoSimulator()
    s.state_file = str(tmp_path / "libero.json")
    s.csv_file = str(tmp_path / "libero.csv")
    s.log_file = str(tmp_path / "libero.log")
    s.state = {'last_run': None, 'current_regime': None}
    return s


def _cand(code, closes, change='+1.00%'):
    hist = [{'date': f'2026112{i}', 'close': c} for i, c in enumerate(closes)]
    return {'code': code, 'change_rate': change, 'foreign_change': 0,
            'price_history': hist}


def test_history_candidates_produce_nonzero_momentum_and_trend(tmp_path):
    s = _sim(tmp_path)
    cands = [_cand('A', [100, 102, 104, 106, 110]), _cand('B', [200, 204, 208, 212, 220])]
    s._update_bull_score(cands, None)
    m = s.state['metrics']
    assert m['momentum_score'] == 10.0          # 둘 다 +10%
    assert m['trend_strength'] > 0               # 단조 상승이라 ADX 근사가 0이 아니다
    assert s.state['bull_score'] is not None


def test_no_history_means_unmeasurable_not_zero(tmp_path):
    s = _sim(tmp_path)
    cands = [{'code': 'A', 'change_rate': '+1.00%', 'foreign_change': 0},
             {'code': 'B', 'change_rate': '-1.00%', 'foreign_change': 0, 'price_history': []}]
    s._update_bull_score(cands, None)
    m = s.state['metrics']
    assert m['momentum_score'] is None
    assert m['trend_strength'] is None
    assert s.state['bull_score'] is None         # 0.0이 아니다 — 0점은 '최악의 장'


def test_candidate_without_history_is_excluded_not_counted_as_zero(tmp_path):
    """이력 없는 후보는 평균에서 빠진다. 0.0으로 넣으면 중앙값이 끌려내려간다."""
    s = _sim(tmp_path)
    cands = [_cand('A', [100, 102, 104, 106, 110]),
             {'code': 'B', 'change_rate': '+1.00%', 'foreign_change': 0},
             {'code': 'C', 'change_rate': '+1.00%', 'foreign_change': 0}]
    s._update_bull_score(cands, None)
    assert s.state['metrics']['momentum_score'] == 10.0


def test_live_metrics_trend_missing_and_no_history_is_not_zero(tmp_path):
    """라이브 실측에 trend가 없고 후보 폴백도 못 만들면 trend·bull_score는 None."""
    s = _sim(tmp_path)
    s._update_bull_score([{'code': 'A', 'change_rate': '+1.00%', 'foreign_change': 0}],
                         {'breadth': 60.0, 'momentum': 2.0, 'sample': 100})
    assert s.state['metrics']['trend_strength'] is None
    assert s.state['bull_score'] is None
