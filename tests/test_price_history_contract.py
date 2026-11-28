from src.strategy.simulators.base_simulator import (
    prior_closes, history_of, prior_closes_for, hist_fingerprint)

H = [{'date': f'202611{d:02d}', 'close': 100.0 + d} for d in (16,17,18,19,20,23,24,25,26,27)]

def test_excludes_today_by_date():
    out = prior_closes(H + [{'date': '20261130', 'close': 999.0}], '20261130', 3)
    assert out == [125.0, 126.0, 127.0]        # 11/25, 11/26, 11/27 — 999는 없다

def test_returns_last_n_not_all():
    assert len(prior_closes(H, '20261130', 5)) == 5
    assert prior_closes(H, '20261130', 5) == [123.0, 124.0, 125.0, 126.0, 127.0]

def test_none_when_shorter_than_n():
    assert prior_closes(H[:3], '20261130', 5) is None   # 패딩하지 않는다

def test_none_when_empty_or_missing():
    assert prior_closes([], '20261130', 1) is None
    assert prior_closes(None, '20261130', 1) is None

def test_drops_nonpositive_close_then_checks_length():
    h = [dict(r) for r in H]; h[0]['close'] = 0
    assert len(prior_closes(h, '20261130', 9)) == 9     # 0 한 행은 버리고 계속
    assert prior_closes(h, '20261130', 10) is None      # 버린 뒤 길이 미달

def test_none_when_any_date_malformed():
    h = [dict(r) for r in H]; h[2]['date'] = '2026-11-18'
    assert prior_closes(h, '20261130', 3) is None       # 날짜는 계약의 근거다

def test_none_when_dates_duplicated():
    h = H + [dict(H[-1])]
    assert prior_closes(h, '20261130', 3) is None

def test_holiday_gap_is_not_an_error():
    """추석 연휴로 9일 비어도 정상이다 — 거짓 None이 적응형 청산을 끈다."""
    h = [{'date': '20261001', 'close': 100.0}, {'date': '20261012', 'close': 101.0},
         {'date': '20261013', 'close': 102.0}]
    assert prior_closes(h, '20261130', 3) == [100.0, 101.0, 102.0]

def test_none_when_unsorted():
    assert prior_closes(list(reversed(H)), '20261130', 3) is None

def test_history_of_prefers_candidate_over_supplied():
    cand = {'A': {'price_history': [{'date': '20261127', 'close': 1.0}]}}
    supplied = {'A': [{'date': '20261127', 'close': 2.0}]}
    assert history_of('A', cand, supplied)[0]['close'] == 1.0

def test_history_of_falls_back_to_supplied():
    assert history_of('A', {}, {'A': [{'date': '20261127', 'close': 2.0}]})[0]['close'] == 2.0

def test_history_of_none_when_neither():
    assert history_of('A', {}, {}) is None

def test_prior_closes_for_reads_view():
    view = {'price_history': {'A': H}}
    assert len(prior_closes_for('A', {}, view, '20261130', 4)) == 4

def test_prior_closes_for_tolerates_view_without_key():
    assert prior_closes_for('A', {}, {}, '20261130', 4) is None

def test_fingerprint_changes_with_window():
    assert hist_fingerprint(H) != hist_fingerprint(H[:-1])
    assert hist_fingerprint([]) == ''


def test_nan_and_inf_close_dropped_like_nonpositive():
    h = [dict(r) for r in H]; h[0]['close'] = float('nan'); h[1]['close'] = float('inf')
    assert prior_closes(h, '20261130', 8) == [118.0, 119.0, 120.0, 123.0, 124.0, 125.0, 126.0, 127.0]
    assert prior_closes(h, '20261130', 9) is None


def test_future_dated_rows_are_dropped_not_fatal():
    h = H + [{'date': '20261202', 'close': 999.0}]
    assert prior_closes(h, '20261130', 3) == [125.0, 126.0, 127.0]


def test_fingerprint_survives_nonnumeric_close():
    h = [dict(r) for r in H]; h[0]['close'] = 'abc'
    assert isinstance(hist_fingerprint(h), str)
    z = [dict(r) for r in H]; z[0]['close'] = 0
    assert hist_fingerprint(h) == hist_fingerprint(z)  # 변환 불가 값은 건너뛴다


def test_history_of_empty_candidate_list_falls_back_to_supplied():
    cand = {'A': {'price_history': []}}
    supplied = {'A': [{'date': '20261127', 'close': 2.0}]}
    assert history_of('A', cand, supplied)[0]['close'] == 2.0


import re as _re

# 필드 접근 형태 전부. 딕셔너리 리터럴 키(`'x': ...`)도 생산 형태다 —
# scripts/run_eod_sims.py가 정확히 그 형태로 만든다. 빠지면 그 줄을 판단 경로로
# 복사해도 가드가 통과한다.
FIELD_ACCESS = _re.compile(
    r"""\.get\(\s*['"](?:range_history|sparkline_price)['"]"""
    r"""|\[\s*['"](?:range_history|sparkline_price)['"]\s*\]"""
    r"""|['"](?:range_history|sparkline_price)['"]\s*\]"""
    # 쓰기·점검 목록 형태도 접근이다 — setdefault 생산과 결손 점검 튜플.
    r"""|setdefault\(\s*['"](?:range_history|sparkline_price)['"]"""
    r"""|^\s*\(\s*['"](?:range_history|sparkline_price)['"]\s*,"""
    r"""|['"](?:range_history|sparkline_price)['"]\s*:""")


def test_old_fields_gone_from_decision_paths():
    """매매 판단 경로에만 적용한다 — 심9-1(EOD)과 표시용 소비자는 범위 밖이다.

    **식별자가 아니라 필드 접근을 센다.** 2026-11-28 실측: 맨 식별자로 세면
    `base_simulator.py`(세 통계 함수의 파라미터 이름)와 `sim10_orchestrator.py:56`
    (docstring 언급)이 거짓으로 걸린다. 둘 다 결함이 아니다.

    소스 텍스트 검사가 정당한 드문 경우다 — "필드가 없다"는 불변식은 동작으로는
    표현할 수 없다. 다시 읽기 시작하는 코드가 들어오면 값이 조용히 비어 거래 0건이 된다.
    """
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parent.parent
    EXEMPT = {'sim9_1_donchian.py',      # EOD — 생산자(run_eod_sims)가 이미 오늘을 뺀 직전 20일
              'sim0_libero.py',           # breadth 표시용
              'us_sim2_donchian.py',      # 미국 심 — 별도 데이터 원천
              'notifier.py'}              # 런마다 append하는 표시용 시계열(의미가 다르다)
    access = FIELD_ACCESS
    hits = []
    for sub in ('src/strategy', 'src/pipeline'):
        for p in (root / sub).rglob('*.py'):
            if p.name in EXEMPT:
                continue
            for i, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1):
                if access.search(line):
                    hits.append(f'{p.relative_to(root)}:{i}')
    assert not hits, hits


def test_monthly_excel_sparkline_comes_from_price_history(tmp_path):
    """구 sparkline_price 생산을 걷어도 월별 엑셀 'Sparkline' 열이 비면 안 된다 —
    값 없는 열이 정상처럼 쌓이는 게 가장 오래 산다. 마지막 5개 종가(과거->최신)."""
    from datetime import datetime
    import pandas as pd
    from src.data.storage_manager import StorageManager
    sm = object.__new__(StorageManager)
    sm.REPORTS_DIR = str(tmp_path)
    sm._load_market_regime = lambda: ('', 0, 0, 0, 0, 0, 0)
    sm.rebuild_reports_index = lambda now: None
    hist = [{'date': f'202611{d:02d}', 'close': 100.0 + d} for d in range(1, 9)]
    now = datetime(2026, 11, 28, 11, 0)
    path = sm.update_monthly_excel([{'code': '005930', 'price_history': hist}], now)
    assert pd.read_excel(path)['Sparkline'][0] == '104.0,105.0,106.0,107.0,108.0'


def test_field_guard_catches_dict_literal_key():
    """딕셔너리 리터럴 키 `'range_history': ...`도 생산 형태다. 이 형태를 놓치면
    run_eod_sims의 그 줄을 판단 경로로 복사해도 가드가 통과한다."""
    pat = FIELD_ACCESS
    assert pat.search("    'range_history': [x for x in y],")
    assert pat.search('{"sparkline_price" : 1}')
    assert not pat.search("# range_history 는 제거됨")
    assert not pat.search("x = {'price_history': h}")
