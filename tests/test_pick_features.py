"""pick_features.build_features는 이미 계산된 값을 모으기만 한다 — 신규 계산 0.

Design: ~/.gstack/projects/hoonnamkoong-stockbot/Hoon_DT-main-design-20260811-222707.md
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy import pick_features
from src.strategy.pick_features import build_features, rank_top


def test_merges_candidate_and_simulation_fields():
    candidates = [{
        'code': '005930', 'name': '삼성전자', 'fact_score': 0.7,
        'sentiment': 'Positive', 'tick_power': 120.5, 'consecutive_days': 3,
    }]
    simulation_results = [{'code': '005930', 'signal': 'BUY', 'reason': '추세 전환'}]

    out = build_features(candidates, simulation_results, cycle_id=123)

    assert out == [{
        'cycle_id': 123, 'code': '005930', 'name': '삼성전자',
        'fact_score': 0.7, 'sentiment': 'Positive', 'tick_power': 120.5,
        'consecutive_days': 3, 'engine_signal': 'BUY', 'engine_reason': '추세 전환',
    }]


def test_missing_simulation_result_does_not_crash():
    """시뮬레이터 판단이 없는 종목(예: 시그널 맵에서 빠짐)도 빈 문자열로 채워 반환한다."""
    candidates = [{'code': '000660', 'name': 'SK하이닉스'}]

    out = build_features(candidates, simulation_results=[], cycle_id=1)

    assert out[0]['engine_signal'] == ''
    assert out[0]['engine_reason'] == ''
    assert out[0]['fact_score'] == 0.0
    assert out[0]['tick_power'] == 0.0


def test_candidate_without_code_is_skipped():
    """code가 없는 후보는 조인 키가 없어 로그에 넣을 수 없다 — 건너뛴다."""
    candidates = [{'name': '코드없음'}]

    out = build_features(candidates, simulation_results=[], cycle_id=1)

    assert out == []


def test_empty_candidates_returns_empty_list():
    assert build_features([], [], cycle_id=1) == []


def test_simulation_result_without_code_is_ignored():
    """reason_map 구성 시 code 없는 시뮬레이션 결과가 매핑을 깨면 안 된다."""
    candidates = [{'code': '005930', 'name': '삼성전자'}]
    simulation_results = [{'signal': 'WATCH', 'reason': '코드 누락'}]

    out = build_features(candidates, simulation_results, cycle_id=1)

    assert out[0]['engine_signal'] == ''


def _feat(code='005930'):
    return {'cycle_id': 1, 'code': code, 'name': '삼성전자', 'fact_score': 0.5,
            'sentiment': 'Positive', 'tick_power': 1.0, 'consecutive_days': 1,
            'engine_signal': 'BUY', 'engine_reason': 'test'}


def _logs():
    out = []
    return out, out.append


# ── log_features — sim_diag.append와 같은 원칙: 0을 돌려주는 세 갈래를 구분한다ㅡ

def test_log_features_empty_says_so(tmp_path):
    logs, log = _logs()
    n = pick_features.log_features([], path=str(tmp_path / 'd.csv'), log=log)

    assert n == 0
    assert logs, '빈 features가 아무 흔적도 안 남겼다'


def test_log_features_write_failure_names_the_exception(tmp_path):
    blocked = tmp_path / 'd.csv'
    blocked.mkdir()  # 파일이 아니라 디렉터리 → open 실패
    logs, log = _logs()
    n = pick_features.log_features([_feat()], path=str(blocked), log=log)

    assert n == 0
    assert logs, '쓰기 실패가 조용히 삼켜졌다'


def test_log_features_stale_header_that_cannot_move_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(pick_features, '_move_stale_if_needed', lambda p: False)
    logs, log = _logs()
    n = pick_features.log_features([_feat()], path=str(tmp_path / 'd.csv'), log=log)

    assert n == 0
    assert logs, '헤더 이동 실패가 조용히 삼켜졌다'


def test_log_features_never_raises(tmp_path):
    blocked = tmp_path / 'd.csv'
    blocked.mkdir()
    pick_features.log_features([_feat()], path=str(blocked))  # log 인자 없이도 안전


def test_log_features_broken_logger_does_not_raise(tmp_path):
    def boom(_):
        raise RuntimeError('로거 고장')

    blocked = tmp_path / 'd.csv'
    blocked.mkdir()
    pick_features.log_features([_feat()], path=str(blocked), log=boom)


def test_log_features_successful_write_returns_row_count(tmp_path):
    logs, log = _logs()
    n = pick_features.log_features([_feat('005930'), _feat('000660')],
                                    path=str(tmp_path / 'd.csv'), log=log)

    assert n == 2
    assert not logs, f'정상 기록이 로그를 더럽힌다: {logs}'
    assert (tmp_path / 'd.csv').exists()


def test_log_features_header_rotates_on_column_change(tmp_path):
    """옛 헤더 파일이 있으면 옆으로 비켜놓고 정규 경로에 새로 쓴다."""
    path = tmp_path / 'd.csv'
    path.write_text('old,header\n1,2\n', encoding='utf-8')

    n = pick_features.log_features([_feat()], path=str(path))

    assert n == 1
    assert (tmp_path / 'd_v1.csv').exists()
    with open(path, encoding='utf-8') as f:
        assert f.readline().strip() == ','.join(pick_features.COLUMNS)


def test_month_path_uses_kst_month():
    assert pick_features.month_path('20260811') == os.path.join(
        'data', 'pick_features_2026-08.csv')


# ── rank_top — 순위 결합(Borda), 원값 합산 금지 ─────────────────────────

def _cand(code, fact_score=0.0, tick_power=0.0):
    return {'code': code, 'name': code, 'fact_score': fact_score, 'tick_power': tick_power}


def test_rank_top_picks_best_by_combined_rank():
    """fact_score 1등 + tick_power 1등인 종목이 최상위여야 한다."""
    candidates = [
        _cand('A', fact_score=0.9, tick_power=150.0),  # 둘 다 1등
        _cand('B', fact_score=0.5, tick_power=100.0),
        _cand('C', fact_score=0.1, tick_power=80.0),
    ]

    top = rank_top(candidates, n=2)

    assert [c['code'] for c in top] == ['A', 'B']
    assert top[0]['rank'] == 1
    assert top[1]['rank'] == 2


def test_rank_top_uses_rank_not_raw_sum():
    """스케일이 다른 원값을 그대로 더하면 tick_power가 fact_score를 압도한다 —
    순위 결합은 그 함정에 안 걸려야 한다."""
    candidates = [
        # fact_score 최상위, tick_power 최하위
        _cand('A', fact_score=1.0, tick_power=0.0),
        # fact_score 최하위, tick_power가 원값으로는 압도적으로 큼
        _cand('B', fact_score=0.0, tick_power=100000.0),
    ]

    top = rank_top(candidates, n=1)

    # 순위 결합(Borda)이면 둘 다 (1등+2등=3)으로 동률 — 원래 순서(A 먼저)가
    # 안정 정렬로 유지되어 A가 뽑힌다. 원값을 더했다면 B가 압도적으로 이겼을 것.
    assert top[0]['code'] == 'A'


def test_rank_top_caps_at_n():
    candidates = [_cand(str(i), fact_score=float(i)) for i in range(10)]

    top = rank_top(candidates, n=5)

    assert len(top) == 5
    assert [c['rank'] for c in top] == [1, 2, 3, 4, 5]


def test_rank_top_empty_input_returns_empty():
    assert rank_top([], n=5) == []


def test_rank_top_fewer_than_n_returns_all():
    candidates = [_cand('A', fact_score=0.5), _cand('B', fact_score=0.3)]

    top = rank_top(candidates, n=5)

    assert len(top) == 2
