"""하루 일봉은 하루에 한 번만 확정된다.

2026-09-15 실측으로 드러난 구조: EOD는 매 거래일 두 번 돈다(16:00 태스커
dispatch + 21~23시 지연 cron). 둘 다 같은 파일을 쓰고 **늦은 쪽이 항상 덮는다.**

늦은 바는 이른 바의 순수한 확장이었다 — 20260914 100종목 전수에서 거래량이
줄어든 종목 0, 고저 범위가 좁아진 종목 0, 이른 종가가 늦은 바의 [저,고] 안에
있는 종목 100/100. 즉 이른 스냅샷 이후에도 거래가 계속 붙었다는 뜻이다.

이른 런은 16:01~16:02 KST에 수집한다(Actions 로그 확인). 그 시각은
시간외단일가(16:00~18:00)와 NXT 애프터마켓(15:40~20:00) 한복판이다.
그래서 20260914에는 95/100 종목의 종가가 바뀌었고(82개 하락, 중앙 -0.71%,
최대 -3.08%), 저가 26개가 아래로 늘었다. 실제로 심11 감시목록이
GS+한화생명에서 한화생명 하나로 뒤집혔다.

**정규장 종가를 정본으로 삼기로 했다**(2026-09-15 사용자 판단). 그러면 늦게 붙은
시간외·NXT 체결은 일봉에 들어오면 안 된다. 지금 구조에서 정규장 종가에 더 가까운
쪽은 언제나 **먼저 쓴 바**다(NXT 오염 21분 vs 4시간 20분). 그래서:

  - 오늘 날짜 행: **먼저 쓴 쪽이 이긴다**(나중 런이 덮지 않는다)
  - 과거 날짜 행: **나중 쪽이 이긴다**(수정주가 반영·결손 보충)

⚠ 이건 오염을 줄이는 것이지 없애는 게 아니다. 완전히 깨끗한 정규장 봉을 얻으려면
수집 자체가 15:30~15:40 창에서 일어나거나 KIS 시장구분이 KRX 정규장으로 한정돼야
한다 — 둘 다 이 병합 밖의 일이다.
"""
import csv
import io
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from scripts.merge_ohlcv_bars import merge_rows, kst_today

SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'merge_ohlcv_bars.py')


def _row(date, code, close, volume='100'):
    return {'date': date, 'code': code, 'name': code, 'open': close, 'high': close,
            'low': close, 'close': close, 'volume': volume, 'amount': volume}


def test_todays_bar_is_not_overwritten_by_a_later_run():
    """같은 날 두 번째 런이 오늘 봉을 덮지 않는다 — 이게 이 병합의 존재 이유다."""
    existing = [_row('20260914', '005930', '249000')]
    fresh = [_row('20260914', '005930', '248500')]

    merged = merge_rows(existing, fresh, today='20260914')

    assert len(merged) == 1
    assert merged[0]['close'] == '249000'


def test_past_bars_are_taken_from_the_fresh_file():
    """과거 행은 최신이 이긴다 — 수정주가·결손 보충이 반영돼야 한다."""
    existing = [_row('20260911', '005930', '259500')]
    fresh = [_row('20260911', '005930', '260000')]

    merged = merge_rows(existing, fresh, today='20260914')

    assert merged[0]['close'] == '260000'


def test_a_code_missing_from_the_first_run_is_still_added():
    """선착순은 '있는 행'에만 적용된다.

    2026-09-11 이른 런은 93종목(9300행)만 모았고 늦은 런이 100종목(10000행)을
    모았다. 선착순을 '오늘 행 전체'에 걸면 그 7종목이 영영 안 들어온다.
    """
    existing = [_row('20260914', '005930', '249000')]
    fresh = [_row('20260914', '005930', '248500'), _row('20260914', '000660', '1683000')]

    merged = merge_rows(existing, fresh, today='20260914')

    by_code = {r['code']: r['close'] for r in merged}
    assert by_code == {'005930': '249000', '000660': '1683000'}


def test_first_run_of_the_day_writes_todays_bar_normally():
    """첫 런은 막히지 않는다 — 어제까지만 있는 파일에 오늘이 새로 들어간다."""
    existing = [_row('20260911', '005930', '259500')]
    fresh = [_row('20260911', '005930', '259500'), _row('20260914', '005930', '249000')]

    merged = merge_rows(existing, fresh, today='20260914')

    assert {(r['date'], r['close']) for r in merged} == {
        ('20260911', '259500'), ('20260914', '249000')}


def test_no_existing_file_means_fresh_wins_entirely():
    fresh = [_row('20260914', '005930', '249000')]
    assert merge_rows([], fresh, today='20260914') == fresh


def test_row_order_follows_the_fresh_file():
    """행 순서는 신규 파일을 따른다 — 종목별 묶음 구조가 깨지면 안 된다."""
    existing = [_row('20260914', '000660', '1')]
    fresh = [_row('20260914', '005930', '2'), _row('20260914', '000660', '3')]

    merged = merge_rows(existing, fresh, today='20260914')

    assert [r['code'] for r in merged] == ['005930', '000660']


def test_kst_today_does_not_use_the_runners_utc_date():
    """러너는 UTC다. KST 16:0x은 UTC로 07:0x이라 날짜가 같지만, 자정 근처
    스케줄이 바뀌면 하루가 어긋난다 — 날짜 계산은 KST로 고정한다."""
    import datetime as dt
    assert kst_today(dt.datetime(2026, 9, 14, 22, 0, tzinfo=dt.timezone.utc)) == '20260915'
    assert kst_today(dt.datetime(2026, 9, 14, 7, 0, tzinfo=dt.timezone.utc)) == '20260914'


def test_cli_merges_in_place_and_survives_a_missing_existing_file(tmp_path):
    """워크플로가 부르는 방식 그대로 — 파일 두 개를 받아 결과를 내놓는다."""
    fresh = tmp_path / 'fresh.csv'
    with open(fresh, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(_row('20260914', '005930', '248500').keys()))
        w.writeheader()
        w.writerow(_row('20260914', '005930', '248500'))

    out = subprocess.run(
        [sys.executable, SCRIPT, str(fresh), str(tmp_path / 'nope.csv'), '--today', '20260914'],
        capture_output=True, text=True, encoding='utf-8')
    assert out.returncode == 0, out.stderr

    with open(fresh, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    assert rows[0]['close'] == '248500'


def test_cli_keeps_todays_existing_bar(tmp_path):
    fields = list(_row('20260914', '005930', '0').keys())

    def write(path, rows):
        with open(path, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    fresh = tmp_path / 'fresh.csv'
    prev = tmp_path / 'prev.csv'
    write(fresh, [_row('20260914', '005930', '248500')])
    write(prev, [_row('20260914', '005930', '249000')])

    out = subprocess.run(
        [sys.executable, SCRIPT, str(fresh), str(prev), '--today', '20260914'],
        capture_output=True, text=True, encoding='utf-8')
    assert out.returncode == 0, out.stderr

    with open(fresh, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    assert rows[0]['close'] == '249000', '두 번째 런이 오늘 봉을 덮었다'
    assert '선착순' in out.stdout or '보존' in out.stdout, f'무엇을 했는지 안 알린다: {out.stdout}'


def test_workflow_merges_before_deploying():
    """스크립트가 있어도 워크플로가 안 부르면 아무 일도 안 일어난다."""
    wf_path = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows', 'eod_data.yml')
    with open(wf_path, encoding='utf-8') as f:
        wf = f.read()
    assert 'merge_ohlcv_bars.py' in wf, (
        'eod_data.yml이 병합 스크립트를 부르지 않는다 — 늦은 런이 계속 오늘 봉을 덮는다')


# ── 종가 CSV(넓은 형태)도 같은 결함을 갖는다 ──────────────
# kospi_top100_close.csv는 행이 날짜, 열이 종목인 100×101 형태다. 같은 EOD 두 런이
# 같은 날짜 행을 두고 다투는 구조는 동일하고, 이 파일은 리베로 trend의 입력이다.
# 다만 종목 집합이 런마다 달라질 수 있어(09-11 이른 런은 93종목) 행을 통째로
# 바꾸면 헤더에 없는 열이 섞이거나 있어야 할 열이 빈다 — 필드 단위로 병합한다.
def test_wide_close_row_merges_field_by_field():
    existing = [{'date': '20260914', 'A': '100', 'B': '200'}]
    fresh = [{'date': '20260914', 'A': '99', 'B': '199', 'C': '300'}]

    merged = merge_rows(existing, fresh, today='20260914')

    # A·B는 먼저 쓴 값, C는 이번 런에만 있으니 이번 값
    assert merged == [{'date': '20260914', 'A': '100', 'B': '200', 'C': '300'}]


def test_a_blank_earlier_value_does_not_beat_a_real_one():
    """선착순이 결손까지 지키면 안 된다 — 빈 값은 측정이 아니다."""
    existing = [{'date': '20260914', 'A': '', 'B': '200'}]
    fresh = [{'date': '20260914', 'A': '99', 'B': '199'}]

    merged = merge_rows(existing, fresh, today='20260914')

    assert merged == [{'date': '20260914', 'A': '99', 'B': '200'}]


def test_workflow_merges_the_wide_close_file_too():
    wf_path = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows', 'eod_data.yml')
    with open(wf_path, encoding='utf-8') as f:
        wf = f.read()
    assert 'kospi_top100_close.csv' in wf.split('merge_ohlcv_bars.py')[1][:400], (
        '종가 CSV는 병합되지 않는다 — 같은 날을 두고 OHLCV와 서로 다른 값을 갖게 된다')


# ── 필드마다 확정되는 쪽이 다르다 (2026-09-16 실측) ──────────────
# 같은 날을 여러 스냅샷에 걸쳐 추적하니 가격과 거래량이 정반대로 움직였다.
# 삼성전자 20260914: 이른 249000 → 늦은 248500 → **다음 날 확정 249000**(이른 값으로 복귀).
# SK하이닉스도 1698000 → 1683000 → 1697000. 20260911 행은 여섯 스냅샷 전부 동일하다
# (이틀 지나면 고정). 즉 **늦은 런의 종가가 이상치이고 다음 날 정정된다.**
#
# 반대로 거래량은 늦은 값이 확정이다 — 20260914 거래량은 늦은 커밋 값에서
# 그 뒤 단 한 종목도(0/99) 바뀌지 않았다. 장 마감 뒤에도 체결이 실제로 쌓이기 때문이다.
#
# 그래서 선착순을 전 필드에 걸면 거래량·거래대금이 3~4.5% 낮은 채로 하룻밤 남는다.
# 가격은 선착순, 수량은 최신 — 필드마다 갈라야 한다.
VOLUME_FIELDS = ('volume', 'amount')


def test_volume_takes_the_latest_value_even_for_today():
    existing = [_row('20260914', '005930', '249000', volume='1000')]
    fresh = [_row('20260914', '005930', '248500', volume='1045')]

    merged = merge_rows(existing, fresh, today='20260914')

    assert merged[0]['close'] == '249000', '종가는 먼저 쓴 값이어야 한다'
    assert merged[0]['volume'] == '1045', '거래량은 늦게 쌓인 값이 확정이다'
    assert merged[0]['amount'] == '1045', '거래대금도 거래량과 같이 간다'


def test_volume_never_goes_backwards_in_the_merge():
    """늦은 런이 더 작은 거래량을 주면(있을 수 없지만) 큰 쪽을 지킨다."""
    existing = [_row('20260914', '005930', '249000', volume='2000')]
    fresh = [_row('20260914', '005930', '248500', volume='1000')]

    merged = merge_rows(existing, fresh, today='20260914')

    assert merged[0]['volume'] == '2000', '거래량이 뒤로 갈 수는 없다'


def test_price_fields_still_take_the_earlier_value():
    """가격 쪽 규칙은 그대로다 — 이 변경이 그걸 건드리면 안 된다."""
    existing = [_row('20260914', '005930', '100')]
    fresh = [_row('20260914', '005930', '200')]

    merged = merge_rows(existing, fresh, today='20260914')

    for f in ('open', 'high', 'low', 'close'):
        assert merged[0][f] == '100', f'{f}는 먼저 쓴 값이어야 한다'


def test_wide_close_file_is_unaffected_by_the_volume_rule():
    """종가 CSV에는 volume 열이 없다 — 열 이름이 우연히 겹치지 않는 한 그대로."""
    existing = [{'date': '20260914', 'A': '100'}]
    fresh = [{'date': '20260914', 'A': '99'}]

    assert merge_rows(existing, fresh, today='20260914') == [{'date': '20260914', 'A': '100'}]
