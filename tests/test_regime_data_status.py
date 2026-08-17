# -*- coding: utf-8 -*-
"""충분성 리포트 — "언제 학습을 시작하나"에 답한다."""
from scripts.regime_data_status import column_coverage, naive_mae, pair_observations


def _row(ts, breadth, **kw):
    r = {'ts': ts, 'breadth': breadth, 'momentum': 0.0, 'trend': None,
         'sample': 100, 'source': 'top100_live'}
    for col in ('breadth_cap', 'p10', 'p25', 'p75', 'p90', 'up', 'down', 'turnover'):
        r[col] = kw.get(col)
    return r


def test_30분_뒤_관측과_짝짓는다():
    rows = [_row('2026-08-17 09:00', 50.0), _row('2026-08-17 09:30', 60.0)]
    pairs = pair_observations(rows)
    assert len(pairs) == 1
    assert pairs[0][1]['breadth'] == 60.0


def test_관측_격자가_어긋나도_허용오차_안이면_짝이_된다():
    # 실제 격자는 09:01, 09:13, 09:25, 09:37...로 11~12분 간격이다. 정확히 +30분은 없다.
    rows = [_row('2026-08-17 09:01', 50.0), _row('2026-08-17 09:33', 60.0)]
    assert len(pair_observations(rows)) == 1


def test_허용오차_밖이면_짝이_아니다():
    rows = [_row('2026-08-17 09:00', 50.0), _row('2026-08-17 09:50', 60.0)]
    assert pair_observations(rows) == []


def test_날짜를_넘어_짝짓지_않는다():
    # 15:20의 30분 뒤는 장이 끝난 뒤다. 다음날 09:00과 이으면 오버나이트가 장중으로 둔갑한다.
    rows = [_row('2026-08-17 15:20', 50.0), _row('2026-08-18 09:00', 90.0)]
    assert pair_observations(rows) == []


def test_장_마감_직전_관측은_라벨이_없다():
    rows = [_row('2026-08-17 15:00', 50.0), _row('2026-08-17 15:30', 55.0)]
    assert len(pair_observations(rows)) == 1, '15:00은 짝이 있고 15:30은 없다'


def test_나이브_기준선은_현재값_유지다():
    rows = [_row('2026-08-17 09:00', 50.0), _row('2026-08-17 09:30', 56.0),
            _row('2026-08-17 10:00', 54.0)]
    # |56-50| = 6, |54-56| = 2 → 4.0
    assert naive_mae(pair_observations(rows)) == 4.0


def test_짝이_없으면_MAE는_None이다():
    assert naive_mae([]) is None


def test_열_채움률은_결측을_센다():
    rows = [_row('2026-08-17 09:00', 50.0, turnover=100),
            _row('2026-08-17 09:30', 60.0)]
    cov = column_coverage(rows)
    assert cov['breadth'] == 1.0
    assert cov['turnover'] == 0.5
    assert cov['trend'] == 0.0
