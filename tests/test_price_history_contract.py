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
    assert len(prior_closes(h, '20261130', 8)) == 8
    assert prior_closes(h, '20261130', 9) is None


def test_future_dated_rows_are_dropped_not_fatal():
    h = H + [{'date': '20261202', 'close': 999.0}]
    assert prior_closes(h, '20261130', 3) == [125.0, 126.0, 127.0]


def test_fingerprint_survives_nonnumeric_close():
    h = [dict(r) for r in H]; h[0]['close'] = 'abc'
    assert isinstance(hist_fingerprint(h), str)
    assert hist_fingerprint(h) == hist_fingerprint(h)


def test_history_of_empty_candidate_list_falls_back_to_supplied():
    cand = {'A': {'price_history': []}}
    supplied = {'A': [{'date': '20261127', 'close': 2.0}]}
    assert history_of('A', cand, supplied)[0]['close'] == 2.0
