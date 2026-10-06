"""SEC companyfacts → 재무 신호(US Sim4 입력).

여기서 지키는 것은 세 가지다.
  1. **시점 정보만 쓴다** — `filed <= asof`가 아닌 값이 끼면 과거 재생이 미래를 본다.
  2. **전년 대비는 같은 공시의 비교 열로** — 분할한 회사가 주식을 10배 찍은 것으로
     읽히면 안 된다(2026-10-06 연구 1차판이 그렇게 읽었다).
  3. **못 구하면 None** — 0은 "변화 없음"이라는 주장이다.
"""
import datetime as dt

from src.data import us_factors as m

D = dt.date


def _f(start, end, val, filed, pri=0):
    return {'start': start, 'end': end, 'val': val, 'filed': filed, 'pri': pri}


def _quarter(end, val, filed, pri=0):
    return _f(end - dt.timedelta(days=90), end, val, filed, pri)


def _year(end, val, filed):
    return _f(end - dt.timedelta(days=364), end, val, filed)


# ── yoy_pair ────────────────────────────────────────────────────────

def test_yoy_pair_uses_latest_filing_quarter_and_its_prior_year():
    rows = [_quarter(D(2025, 6, 30), 80, D(2025, 8, 1)),
            _quarter(D(2026, 6, 30), 100, D(2026, 8, 1)),
            _quarter(D(2025, 6, 30), 80, D(2026, 8, 1))]
    p = m.yoy_pair(rows, D(2026, 9, 30))
    assert (p['cur'], p['prior'], p['kind'], p['end']) == (100, 80, 'q', D(2026, 6, 30))


def test_yoy_pair_ignores_filings_after_asof():
    """8월 1일에 공시된 2분기 값을 7월 말에 알 수는 없다."""
    rows = [_quarter(D(2025, 3, 31), 50, D(2025, 5, 1)),
            _quarter(D(2026, 3, 31), 70, D(2026, 5, 1)),
            _quarter(D(2026, 6, 30), 100, D(2026, 8, 1)),
            _quarter(D(2025, 6, 30), 80, D(2025, 8, 1))]
    p = m.yoy_pair(rows, D(2026, 7, 31))
    assert (p['cur'], p['prior'], p['end']) == (70, 50, D(2026, 3, 31))


def test_yoy_pair_prefers_restated_comparative_from_same_filing():
    """10:1 분할 뒤 공시는 전년 주식수도 분할 후 기준으로 다시 싣는다.
    1년 전 공시의 값(100)을 쓰면 주식수가 10배 늘어난 것으로 읽힌다."""
    rows = [_quarter(D(2025, 6, 30), 100, D(2025, 8, 1)),       # 분할 전 기준
            _quarter(D(2026, 6, 30), 1010, D(2026, 8, 1)),      # 분할 후
            _quarter(D(2025, 6, 30), 1000, D(2026, 8, 1))]      # 같은 공시의 비교 열
    p = m.yoy_pair(rows, D(2026, 9, 30))
    assert p['prior'] == 1000


def test_yoy_pair_falls_back_to_annual_when_filing_has_no_quarter():
    """10-K에는 분기 열이 없다 — 연간끼리 비교한다."""
    rows = [_year(D(2025, 12, 31), 400, D(2026, 2, 20)), _year(D(2024, 12, 31), 320, D(2026, 2, 20)),
            _quarter(D(2025, 9, 30), 100, D(2025, 11, 1))]
    p = m.yoy_pair(rows, D(2026, 3, 31))
    assert (p['cur'], p['prior'], p['kind']) == (400, 320, 'y')


def test_yoy_pair_is_none_for_stale_filers():
    rows = [_quarter(D(2024, 6, 30), 100, D(2024, 8, 1)), _quarter(D(2023, 6, 30), 80, D(2024, 8, 1))]
    assert m.yoy_pair(rows, D(2026, 9, 30)) is None


def test_yoy_pair_is_none_without_prior_year():
    rows = [_quarter(D(2026, 6, 30), 100, D(2026, 8, 1))]
    assert m.yoy_pair(rows, D(2026, 9, 30)) is None


# ── ttm ─────────────────────────────────────────────────────────────

def test_ttm_is_the_annual_value_right_after_a_10k():
    rows = [_year(D(2025, 12, 31), 400, D(2026, 2, 20))]
    assert m.ttm(rows, D(2026, 3, 31)) == 400


def test_ttm_builds_from_year_to_date_cash_flows():
    """현금흐름표는 연초 누적만 싣는다: 직전 연간 + 올해 6개월 − 작년 6개월."""
    rows = [_year(D(2025, 12, 31), 400, D(2026, 2, 20)),
            _f(D(2026, 1, 1), D(2026, 6, 30), 250, D(2026, 8, 1)),
            _f(D(2025, 1, 1), D(2025, 6, 30), 180, D(2026, 8, 1))]
    assert m.ttm(rows, D(2026, 9, 30)) == 400 + 250 - 180


def test_ttm_picks_the_cumulative_row_not_the_single_quarter():
    """손익은 같은 분기말에 '이번 분기'와 '연초 누적'이 같이 나온다. 분기 값을 누적으로
    착각하면 TTM이 한 분기만큼 모자란다."""
    rows = [_year(D(2025, 12, 31), 400, D(2026, 2, 20)),
            _quarter(D(2026, 6, 30), 130, D(2026, 8, 1)),
            _f(D(2026, 1, 1), D(2026, 6, 30), 250, D(2026, 8, 1)),
            _f(D(2025, 1, 1), D(2025, 6, 30), 180, D(2026, 8, 1))]
    assert m.ttm(rows, D(2026, 9, 30)) == 470


def test_ttm_is_none_when_a_piece_is_missing():
    rows = [_f(D(2026, 1, 1), D(2026, 6, 30), 250, D(2026, 8, 1))]
    assert m.ttm(rows, D(2026, 9, 30)) is None


# ── compute_signals ─────────────────────────────────────────────────

def _facts():
    f1, f0 = D(2026, 8, 1), D(2026, 2, 20)
    q, q0 = D(2026, 6, 30), D(2025, 6, 30)
    return {
        'revenue': [_quarter(q, 1000, f1), _quarter(q0, 800, f1)],
        'op_income': [_quarter(q, 250, f1), _quarter(q0, 160, f1)],
        'net_income': [_quarter(q, 200, f1), _quarter(q0, 120, f1), _year(D(2025, 12, 31), 600, f0),
                       _f(D(2026, 1, 1), q, 380, f1), _f(D(2025, 1, 1), q0, 230, f1)],
        'cfo': [_year(D(2025, 12, 31), 700, f0), _f(D(2026, 1, 1), q, 300, f1), _f(D(2025, 1, 1), q0, 280, f1)],
        'assets': [{'start': None, 'end': q, 'val': 5000, 'filed': f1, 'pri': 0},
                   {'start': None, 'end': q0, 'val': 4000, 'filed': D(2025, 8, 1), 'pri': 0}],
        'shares': [_quarter(q, 98, f1), _quarter(q0, 100, f1)],
    }


def test_compute_signals_values_and_direction():
    s = m.compute_signals(_facts(), D(2026, 9, 30))
    ni_ttm, cfo_ttm = 600 + 380 - 230, 700 + 300 - 280
    assert s['accr'] == -(ni_ttm - cfo_ttm) / 5000
    assert abs(s['ag'] - -(5000 / 4000 - 1)) < 1e-12
    assert abs(s['issue'] - 0.02) < 1e-12, '주식수가 줄면 양수(좋다)'
    assert abs(s['d_opm'] - (0.25 - 0.20)) < 1e-12
    assert abs(s['ni_chg'] - (200 - 120) / 800) < 1e-12


def test_compute_signals_missing_inputs_are_none_not_zero():
    facts = _facts()
    facts['cfo'] = []
    facts['shares'] = []
    s = m.compute_signals(facts, D(2026, 9, 30))
    assert s['accr'] is None and s['issue'] is None
    assert s['ag'] is not None


def test_compute_signals_does_not_mix_quarter_revenue_with_annual_income():
    """매출은 분기, 영업이익은 연간만 잡히면 마진을 계산하지 않는다."""
    facts = _facts()
    f1 = D(2026, 8, 1)
    facts['op_income'] = [_year(D(2026, 6, 30), 900, f1), _year(D(2025, 6, 30), 700, f1)]
    assert m.compute_signals(facts, D(2026, 9, 30))['d_opm'] is None


def test_compute_signals_empty_company():
    assert m.compute_signals({}, D(2026, 9, 30)) == dict.fromkeys(m.SIGNALS)


# ── normalize / 요청 헤더 ───────────────────────────────────────────

def test_normalize_merges_revenue_tags_and_skips_malformed_rows():
    body = {'facts': {'us-gaap': {
        'Revenues': {'units': {'USD': [{'start': '2026-04-01', 'end': '2026-06-30', 'val': 10, 'filed': '2026-08-01'},
                                       {'end': '2026-06-30', 'filed': '2026-08-01'}]}},
        'SalesRevenueNet': {'units': {'USD': [{'start': '2012-04-01', 'end': '2012-06-30', 'val': 3, 'filed': '2012-08-01'}]}},
        'Assets': {'units': {'USD': [{'end': '2026-06-30', 'val': 99, 'filed': '2026-08-01'}]}},
    }}}
    out = m.normalize(body)
    assert [r['val'] for r in out['revenue']] == [10.0, 3.0]
    assert out['assets'][0]['start'] is None and out['assets'][0]['end'] == D(2026, 6, 30)
    assert out['cfo'] == []


def test_user_agent_has_no_url():
    """SEC는 UA에 URL이 있으면 403을 준다(us_fundamentals.py와 같은 제약)."""
    assert 'http' not in m.HEADERS['User-Agent'] and '.' not in m.HEADERS['User-Agent']
