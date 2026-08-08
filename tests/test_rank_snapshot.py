"""순위 차분 — 게시글 증분의 돈 버전. 추가 API 호출이 0인 신호.

2026-08-09 재구성. 게시글 증분은 가격에 후행한다(직전 10분 수익률과 +0.082).
행동경제학이 말하는 건 "글을 쓴다"가 아니라 "비합리적으로 사들인다"이고,
사는 행위는 KIS 순위에 먼저 나타난다.

KIS 순위 API는 몇 종목을 가져오든 호출 1번이다(`rows[:limit]`으로 자를 뿐).
그런데 지금 그 결과는 매 호출마다 버려진다 — `_set_rank_cache`가 TTL 캐시라
직전 스냅샷이 남지 않는다. **저장만 하면 신호가 생긴다.**

여기에는 네트워크가 없다. 차분 계산만 순수 함수로 둔다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data.rank_snapshot import rank_map, diff_ranks, RANK_ABSENT


def _rows(*codes):
    return [{'code': c, 'name': f'종목{c}'} for c in codes]


# ── 순위 매기기 ──────────────────────────────────────────────────────

def test_rank_is_one_based_in_list_order():
    """KIS 응답은 이미 순위 순이다. 1위가 1이어야 사람이 로그를 읽을 수 있다."""
    assert rank_map(_rows('A', 'B', 'C')) == {'A': 1, 'B': 2, 'C': 3}


def test_duplicate_codes_keep_the_best_rank():
    """여러 순위 API를 합치면 같은 종목이 두 번 올 수 있다."""
    assert rank_map(_rows('A', 'B', 'A'))['A'] == 1


def test_rows_without_code_are_skipped():
    assert rank_map([{'name': '이름만'}, {'code': 'A'}]) == {'A': 1}


# ── 차분 ────────────────────────────────────────────────────────────

def test_rank_rise_is_positive():
    """5위 → 2위는 +3. 부호가 직관과 같아야 로그를 잘못 읽지 않는다."""
    d = diff_ranks({'A': 5}, {'A': 2})

    assert d['A']['rank'] == 2
    assert d['A']['prev_rank'] == 5
    assert d['A']['delta'] == 3


def test_rank_fall_is_negative():
    assert diff_ranks({'A': 2}, {'A': 5})['A']['delta'] == -5 + 2


def test_new_entry_has_no_delta_not_zero():
    """순위 밖에 있다가 들어온 종목의 상승폭은 **모르는 값**이다.
    0으로 적으면 '변화 없음'과 구분되지 않고, 큰 수로 적으면 지어낸 값이다."""
    d = diff_ranks({}, {'A': 3})

    assert d['A']['is_new'] is True
    assert d['A']['delta'] is None
    assert d['A']['prev_rank'] == RANK_ABSENT


def test_dropped_out_codes_are_not_reported():
    """순위에서 빠진 종목은 이번 사이클의 관측 대상이 아니다 — 현재가도 없다."""
    assert 'B' not in diff_ranks({'A': 1, 'B': 2}, {'A': 1})


def test_no_previous_snapshot_marks_everything_new_but_not_a_signal():
    """첫 사이클(직전 스냅샷 없음)에는 전 종목이 신규다. 그걸 '급등 신호'로
    읽으면 매일 09:00에 전 종목이 트리거된다 — 워밍업으로 구분해야 한다."""
    d = diff_ranks(None, {'A': 1, 'B': 2})

    assert all(v['is_new'] and v['warmup'] for v in d.values())


def test_warmup_is_false_once_a_previous_snapshot_exists():
    d = diff_ranks({'A': 1}, {'A': 1, 'B': 2})

    assert d['A']['warmup'] is False and d['B']['warmup'] is False
    assert d['B']['is_new'] is True


# ── 저장 ────────────────────────────────────────────────────────────

from src.data.rank_snapshot import (
    load_state, save_state, build_records, COLUMNS, append_records, month_path,
)
from datetime import datetime


def test_state_round_trips(tmp_path):
    """컨테이너가 매 런 새로 뜬다. 직전 스냅샷이 db-data를 왕복하지 못하면
    매 사이클이 warmup이 되어 delta가 영원히 None이다."""
    save_state({'A': 1, 'B': 2}, datetime(2026, 8, 10, 10, 0), str(tmp_path))

    assert load_state(str(tmp_path)) == {'A': 1, 'B': 2}


def test_missing_state_is_none_not_empty(tmp_path):
    """빈 dict를 돌려주면 '직전에 아무 종목도 없었다'가 되어 전 종목이 신규로
    잡히는데 warmup 표시가 안 붙는다. 모르는 것은 None이다."""
    assert load_state(str(tmp_path)) is None


def test_corrupt_state_is_none(tmp_path):
    (tmp_path / 'rank_state.json').write_text('{{{', encoding='utf-8')

    assert load_state(str(tmp_path)) is None


def test_records_carry_the_join_key_and_the_diff():
    rows = [{'code': 'A', 'name': '가', 'price': 1000, 'change_rate': '+3.00%',
             'amount': 5_000_000_000, 'acml_vol': 1234}]
    recs = build_records(cycle_id=999, now=datetime(2026, 8, 10, 10, 0),
                         rows=rows, diff=diff_ranks({'A': 4}, {'A': 1}))

    r = recs[0]
    assert r['cycle_id'] == 999 and r['code'] == 'A'
    assert r['rank'] == 1 and r['prev_rank'] == 4 and r['delta'] == 3
    assert r['price'] == 1000 and r['amount'] == 5_000_000_000


def test_new_entry_delta_is_blank_in_csv(tmp_path):
    """None을 0으로 적으면 '변화 없음'과 뭉개진다. CSV에서는 빈칸이어야 한다."""
    rows = [{'code': 'A', 'name': '가'}]
    recs = build_records(1, datetime(2026, 8, 10, 10, 0), rows, diff_ranks({}, {'A': 1}))
    p = str(tmp_path / 'm.csv')
    append_records(recs, p)

    import csv
    got = list(csv.DictReader(open(p, encoding='utf-8')))
    assert got[0]['delta'] == '' and got[0]['prev_rank'] == RANK_ABSENT


def test_appends_do_not_rewrite_the_header(tmp_path):
    p = str(tmp_path / 'm.csv')
    rows = [{'code': 'A', 'name': '가'}]
    d = diff_ranks({'A': 1}, {'A': 1})
    append_records(build_records(1, datetime(2026, 8, 10, 10, 0), rows, d), p)
    append_records(build_records(2, datetime(2026, 8, 10, 10, 2), rows, d), p)

    lines = open(p, encoding='utf-8').read().strip().split('\n')
    assert lines[0].startswith(COLUMNS[0]) and len(lines) == 3


def test_monthly_file_name():
    assert month_path(datetime(2026, 8, 10), 'data').endswith('money_2026-08.csv')
