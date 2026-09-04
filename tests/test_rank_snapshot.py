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
    """한 블록 안의 중복은 응답 이상이다. 뒤 종목의 순위를 밀지 않는다."""
    assert rank_map(_rows('A', 'B', 'A')) == {'A': 1, 'B': 2}


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
    load_state, save_state, build_records, COLUMNS, append_records, day_path,
)
from datetime import datetime


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
                         source='kospi', rows=rows,
                         diff=diff_ranks({'A': 4}, {'A': 1}))

    r = recs[0]
    assert r['cycle_id'] == 999 and r['code'] == 'A' and r['source'] == 'kospi'
    assert r['rank'] == 1 and r['prev_rank'] == 4 and r['delta'] == 3
    assert r['price'] == 1000 and r['amount'] == 5_000_000_000


def test_new_entry_delta_is_blank_in_csv(tmp_path):
    """None을 0으로 적으면 '변화 없음'과 뭉개진다. CSV에서는 빈칸이어야 한다."""
    rows = [{'code': 'A', 'name': '가'}]
    recs = build_records(1, datetime(2026, 8, 10, 10, 0), 'kospi', rows,
                         diff_ranks({}, {'A': 1}))
    p = str(tmp_path / 'm.csv')
    append_records(recs, p)

    import csv
    got = list(csv.DictReader(open(p, encoding='utf-8')))
    assert got[0]['delta'] == '' and got[0]['prev_rank'] == RANK_ABSENT


def test_appends_do_not_rewrite_the_header(tmp_path):
    p = str(tmp_path / 'm.csv')
    rows = [{'code': 'A', 'name': '가'}]
    d = diff_ranks({'A': 1}, {'A': 1})
    append_records(build_records(1, datetime(2026, 8, 10, 10, 0), 'kospi', rows, d), p)
    append_records(build_records(2, datetime(2026, 8, 10, 10, 2), 'kospi', rows, d), p)

    lines = open(p, encoding='utf-8').read().strip().split('\n')
    assert lines[0].startswith(COLUMNS[0]) and len(lines) == 3


def test_daily_file_name():
    """월별 파일은 하루 100번 통째로 재커밋된다 — 월말에 24MB가 된다.

    2026-09-04 실측: db-data 6737커밋 중 절반이 최근 15일치이고, 레포 1.0GB의
    86%가 이력이다. money_2026-09.csv 하나가 하루 100회 커밋됐다. 일별로 쪼개면
    파일이 1MB 수준이 되고 **지난 날짜는 다시 안 써진다.**
    """
    assert day_path(datetime(2026, 8, 10), 'data').endswith('money_2026-08-10.csv')


# ── 블록별 순위 공간 (2026-08-09) ────────────────────────────────────
# 세 순위(코스피 등락률·코스닥 등락률·외인기관 순매수)를 이어붙여 1..N을 매기던
# 시절의 병:
#   ① 중복 코드가 순위 자리를 소비하지 않아, 사이클마다 달라지는 교집합 크기만큼
#      뒤 블록이 통째로 밀렸다 — 가만히 있던 수백 종목에 가짜 delta가 찍혔다.
#      외인기관 순위의 market 기본값이 '0001'(코스피)이라 1번 블록과 정면으로 겹친다.
#   ② delta가 "등락률 순위가 올랐다"인지 "블록이 바뀌었다"인지 구분되지 않았다.
#   ③ 두 블록에 걸친 종목이 같은 cycle_id로 두 행이 되어 조인이 1:N이었다.
# 순위 공간을 블록별로 나누면 셋이 한꺼번에 사라진다.

from src.data.rank_snapshot import snapshot  # noqa: E402


def _blocks(**by_source):
    return [(src, _rows(*codes)) for src, codes in by_source.items()]


def test_each_block_counts_from_one():
    """코스닥 1위는 1위다. 코스피 200종목 뒤에 붙여 201위로 적으면 그 숫자는
    아무 뜻도 없고, 앞 블록 크기가 흔들릴 때마다 같이 흔들린다."""
    _, recs = snapshot(_blocks(kospi=('A', 'B'), kosdaq=('C',)),
                       prev=None, cycle_id=1, now=datetime(2026, 8, 10, 10, 0))

    by = {(r['source'], r['code']): r['rank'] for r in recs}
    assert by[('kospi', 'A')] == 1 and by[('kospi', 'B')] == 2
    assert by[('kosdaq', 'C')] == 1


def test_a_shrinking_block_does_not_shift_another_blocks_ranks():
    """이게 A1의 본체다. 한 블록의 종목 수가 사이클마다 달라져도(중복·파싱 실패)
    다른 블록의 순위는 움직이면 안 된다 — 움직이면 그 delta는 전부 가짜다."""
    now = datetime(2026, 8, 10, 10, 0)
    state1, _ = snapshot(_blocks(kospi=('A', 'B', 'C'), frgn=('X', 'Y')),
                         prev=None, cycle_id=1, now=now)
    _, recs2 = snapshot(_blocks(kospi=('A',), frgn=('X', 'Y')),
                        prev=state1, cycle_id=2, now=now)

    frgn = {r['code']: r for r in recs2 if r['source'] == 'frgn'}
    assert frgn['X']['rank'] == 1 and frgn['Y']['rank'] == 2
    assert frgn['X']['delta'] == 0 and frgn['Y']['delta'] == 0


def test_a_code_in_two_blocks_is_one_row_per_block():
    """겹침은 정상이다(외인기관 기본 시장이 코스피다). 두 행이되 source로
    갈려야 (cycle_id, source, code) 조인이 1:1이 된다."""
    _, recs = snapshot(_blocks(kospi=('A',), frgn=('A',)),
                       prev=None, cycle_id=1, now=datetime(2026, 8, 10, 10, 0))

    keys = [(r['cycle_id'], r['source'], r['code']) for r in recs]
    assert len(keys) == len(set(keys)) == 2


def test_a_duplicate_inside_one_block_is_a_single_row():
    """같은 블록 안의 중복은 응답 이상이다 — 행을 두 번 적으면 조인이 1:N이 된다."""
    _, recs = snapshot([('kospi', _rows('A', 'B', 'A'))],
                       prev=None, cycle_id=1, now=datetime(2026, 8, 10, 10, 0))

    assert [r['code'] for r in recs] == ['A', 'B']


def test_a_brand_new_block_is_warmup_not_a_surge():
    """블록을 추가한 첫 사이클에 그 블록 전체가 '신규 진입'으로 트리거되면 안 된다."""
    now = datetime(2026, 8, 10, 10, 0)
    state1, _ = snapshot(_blocks(kospi=('A',)), prev=None, cycle_id=1, now=now)
    _, recs2 = snapshot(_blocks(kospi=('A',), kosdaq=('C',)),
                        prev=state1, cycle_id=2, now=now)

    kosdaq = next(r for r in recs2 if r['source'] == 'kosdaq')
    assert kosdaq['warmup'] == 1 and kosdaq['is_new'] == 1
    assert next(r for r in recs2 if r['source'] == 'kospi')['warmup'] == 0


# ── 상태 파일도 블록별이다 ──────────────────────────────────────────

def test_state_round_trips_per_source(tmp_path):
    save_state({'kospi': {'A': 1}, 'frgn': {'A': 3}},
               datetime(2026, 8, 10, 10, 0), str(tmp_path))

    assert load_state(str(tmp_path)) == {'kospi': {'A': 1}, 'frgn': {'A': 3}}


def test_an_empty_previous_block_is_warmup_not_a_mass_entry():
    """직전 상태에 그 source 키는 있는데 안이 빈 경우.

    KIS가 응답 shape를 바꿔 전 행에서 code를 못 뽑으면 rank_map이 {}가 되고,
    그게 그대로 저장된다(fetch는 성공했으니 결손 검사에 안 걸린다). 다음 사이클에
    `{}`를 '직전에 아무것도 없었다'로 읽으면 200종목이 warmup 표시 없이 전부
    '신규 진입'으로 잡혀 급등 신호가 된다 — load_state가 빈 상태를 None으로
    돌려주는 것과 같은 이유로, 빈 블록도 '모른다'여야 한다.
    """
    _, recs = snapshot(_blocks(kospi=('A', 'B')), prev={'kospi': {}},
                       cycle_id=1, now=datetime(2026, 8, 10, 10, 0))

    assert all(r['warmup'] == 1 for r in recs), '빈 직전 블록이 급등으로 읽혔다'


def test_flat_legacy_state_is_discarded(tmp_path):
    """구 포맷({code: rank})을 그대로 읽으면 source 이름 자리에 종목코드가 앉는다.
    한 사이클 warmup을 감수하고 버리는 편이, 뜻이 다른 숫자를 비교하는 것보다 낫다."""
    import json
    (tmp_path / 'rank_state.json').write_text(
        json.dumps({'at': 'x', 'ranks': {'A': 1, 'B': 2}}), encoding='utf-8')

    assert load_state(str(tmp_path)) is None


def test_append_moves_a_file_whose_header_no_longer_matches(tmp_path):
    """스키마가 바뀌면 옛 행은 뜻이 다르다. 헤더 하나에 폭이 다른 행을 이어 붙이면
    그 파일은 조용히 어긋난 채 자란다."""
    p = str(tmp_path / 'm.csv')
    with open(p, 'w', encoding='utf-8') as f:
        f.write('cycle_id,ts,code\n1,2026-08-10T10:00:00,A\n')
    _, recs = snapshot(_blocks(kospi=('A',)), prev=None, cycle_id=2,
                       now=datetime(2026, 8, 10, 10, 2))
    append_records(recs, p)

    import csv
    got = list(csv.DictReader(open(p, encoding='utf-8')))
    assert [r['code'] for r in got] == ['A'] and got[0]['source'] == 'kospi'
    assert os.path.exists(p + '.legacy'), '옛 행을 지우지 않고 옆으로 치운다'
