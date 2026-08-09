"""마감 후 1분봉 저장 — 4분짜리 신호를 10분 격자로 재던 미스매치를 없앤다.

2026-08-08 측정에서 게시글 신호가 4분 안에 소멸하는 것이 드러났다. 그런데 지금
가격은 diag의 10분 격자에만 있어서, 향후 수익률의 대부분이 신호와 무관한 구간이다.
표본을 늘리지 않고 검정력을 올리는 유일한 항목이 가격 해상도다.

KIS 분봉(FHKST03010200)은 **당일치만** 조회된다. 과거로 확장할 수 없으므로
마감 후에 그날치를 저장해 두어야 하고, 그래서 이미 마감 후에 도는 eod_data.yml에 붙인다.

한 번 호출에 30건이 오므로 09:00~15:30(390분)을 덮으려면 30분씩 앵커를 물려
여러 번 부른다. 구간이 겹치면서 같은 분이 중복으로 오므로 병합이 필요하다.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data.minute_bars import anchor_times, parse_rows, merge_bars


# ── 앵커 ────────────────────────────────────────────────────────────

def test_anchors_cover_the_whole_session():
    """마지막 앵커가 09:30보다 늦으면 개장 30분이 통째로 빈다 — 07-29 실측에서
    09:05~09:15가 가장 요동치는 구간이었으므로 거기가 비면 안 된다."""
    a = anchor_times()

    assert a[0] == '153000', '마감부터 거슬러 올라간다'
    assert min(a) <= '093000', f'개장 구간이 덮이지 않는다: 최소 앵커 {min(a)}'


def test_anchors_step_by_thirty_minutes():
    """한 호출에 30건이 오므로 앵커 간격이 30분을 넘으면 사이가 빈다."""
    a = anchor_times()
    mins = [int(t[:2]) * 60 + int(t[2:4]) for t in a]
    gaps = {mins[i] - mins[i + 1] for i in range(len(mins) - 1)}

    assert gaps == {30}, f'간격이 30분이 아니다: {gaps}'


def test_anchor_count_is_enough_but_not_wasteful():
    """390분 / 30분 = 13구간. 훨씬 많으면 KIS 호출을 낭비하는 것이다."""
    assert 13 <= len(anchor_times()) <= 15


def test_anchors_have_no_duplicates():
    """같은 앵커를 두 번 부르면 종목마다 KIS 호출 하나가 통째로 낭비된다."""
    a = anchor_times()
    assert len(a) == len(set(a))


# ── 파싱 ────────────────────────────────────────────────────────────

def _row(hhmmss, price, vol='100'):
    return {'stck_cntg_hour': hhmmss, 'stck_prpr': price, 'cntg_vol': vol}


def test_parses_time_price_volume():
    rows = parse_rows({'output2': [_row('101500', '70100', '250')]})

    assert rows == [{'hhmm': '1015', 'price': 70100, 'volume': 250}]


def test_zero_price_rows_are_dropped_not_zeroed():
    """가격 0은 '0원'이 아니라 미집계다. 남겨두면 그 분의 수익률이 −100%가 된다."""
    rows = parse_rows({'output2': [_row('101500', '0'), _row('101600', '70100')]})

    assert [r['hhmm'] for r in rows] == ['1016']


def test_missing_output_is_empty_not_an_error():
    """KIS가 빈 응답을 주는 건 흔하다(휴장·거래정지). 예외로 올리면 나머지
    종목 수집까지 죽는다."""
    assert parse_rows({}) == []
    assert parse_rows({'output2': None}) == []


def test_malformed_row_is_skipped():
    rows = parse_rows({'output2': [{'stck_cntg_hour': 'xx'}, _row('101500', '70100')]})

    assert [r['hhmm'] for r in rows] == ['1015']


# ── 병합 ────────────────────────────────────────────────────────────

def test_overlapping_calls_do_not_duplicate_minutes():
    """앵커 구간이 겹치므로 같은 분이 두 번 온다. 중복을 남기면 그 분의
    거래량이 두 배로 보인다."""
    a = [{'hhmm': '1015', 'price': 70100, 'volume': 250}]
    b = [{'hhmm': '1015', 'price': 70100, 'volume': 250},
         {'hhmm': '1016', 'price': 70200, 'volume': 100}]

    merged = merge_bars(a, b)

    assert [r['hhmm'] for r in merged] == ['1015', '1016']


def test_merged_bars_are_time_ordered():
    """as-of 조인이 시각 순서를 전제한다."""
    merged = merge_bars([{'hhmm': '1500', 'price': 1, 'volume': 1}],
                        [{'hhmm': '0901', 'price': 2, 'volume': 2}])

    assert [r['hhmm'] for r in merged] == ['0901', '1500']


# ── 수집 대상 ────────────────────────────────────────────────────────

from src.data.minute_bars import codes_for_date


def test_codes_come_from_that_days_rank_snapshot(tmp_path):
    """1분봉은 순위에 올랐던 종목만 받는다. 전 종목을 받으면 KIS 유량을 태우고,
    분석에 쓸 일도 없다 — 신호가 순위 차분에서 나오기 때문이다."""
    p = tmp_path / 'money_2026-08.csv'
    p.write_text('cycle_id,ts,code,name\n'
                 '1,2026-08-10T09:00:00,005930,삼성전자\n'
                 '1,2026-08-10T09:00:00,000660,SK하이닉스\n'
                 '2,2026-08-11T09:00:00,035420,NAVER\n', encoding='utf-8')

    assert codes_for_date(str(p), '20260810') == ['000660', '005930']


def test_codes_are_deduped():
    """같은 종목이 하루 195사이클 나온다."""
    import io, csv, tempfile, os
    d = tempfile.mkdtemp(); p = os.path.join(d, 'm.csv')
    with open(p, 'w', encoding='utf-8') as f:
        f.write('cycle_id,ts,code\n')
        for i in range(5):
            f.write(f'{i},2026-08-10T09:0{i}:00,005930\n')

    assert codes_for_date(p, '20260810') == ['005930']


def test_missing_file_is_empty_not_an_error(tmp_path):
    """순위 스냅샷이 아직 없는 날(최초 배포)에 EOD 잡이 죽으면 안 된다."""
    assert codes_for_date(str(tmp_path / 'nope.csv'), '20260810') == []


# ── 전량 결손 (2026-08-09) ──────────────────────────────────────────
# KISDataProvider._get은 실패해도 예외 없이 {}를 돌려준다(토큰 만료·유량 초과·
# rt_cd≠0). 예외만 세면 토큰이 죽은 날 13앵커 × 전 종목이 조용히 비는데 로그에는
# `0행 저장`이 성공처럼 찍힌다. KIS 분봉은 당일치만 조회되므로 **그날 데이터는
# 영구 손실**이고, 다음 날 알아채도 복구할 방법이 없다.

def _run_main(monkeypatch, tmp_path, bars_for_call):
    import scripts.save_minute_bars as smb
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data').mkdir(exist_ok=True)   # 재실행 테스트가 두 번 부른다
    from datetime import datetime, timezone, timedelta
    now = (datetime.now(timezone.utc) + timedelta(hours=9))
    (tmp_path / 'data' / f"money_{now.strftime('%Y-%m')}.csv").write_text(
        f"cycle_id,ts,code\n1,{now.strftime('%Y-%m-%d')}T09:00:00,005930\n",
        encoding='utf-8')

    provider = mock.MagicMock()
    provider.get_minute_bars.side_effect = bars_for_call
    monkeypatch.setattr('src.trade.kis_data_provider.KISDataProvider',
                        lambda *a, **k: provider)
    monkeypatch.setattr(smb.time, 'sleep', lambda *_: None)
    alert = mock.MagicMock(return_value=True)
    monkeypatch.setattr(smb.alerts, 'send_alert', alert)
    smb.main()
    return alert


def test_all_empty_responses_raise_a_human_alert(monkeypatch, tmp_path):
    """예외 없이 전부 빈 응답 = 토큰이 죽었다. 워크플로는 초록색이라 여기서
    안 알리면 아무도 모른다."""
    alert = _run_main(monkeypatch, tmp_path, lambda *a, **k: [])

    assert alert.call_count == 1
    assert '분봉' in alert.call_args[0][0]


def test_a_normal_day_does_not_alert(monkeypatch, tmp_path):
    alert = _run_main(monkeypatch, tmp_path,
                      lambda *a, **k: [{'hhmm': '0900', 'price': 100, 'volume': 10}])

    alert.assert_not_called()


# ── 재실행 (2026-08-09) ─────────────────────────────────────────────
# EOD 잡은 db-data에서 그달 파일을 받아온 뒤 덧붙인다. 실패해서 다시 돌리면
# 이미 들어 있는 당일 행 위에 같은 분이 또 쌓여, 그 분의 거래량이 두 배로 보이고
# as-of 조인이 1:N이 된다.

from src.data.minute_bars import drop_date  # noqa: E402


def test_drop_date_removes_only_that_day(tmp_path):
    p = tmp_path / 'minute_2026-08.csv'
    p.write_text('date,code,hhmm,price,volume\n'
                 '20260810,005930,0900,100,10\n'
                 '20260811,005930,0900,200,20\n'
                 '20260810,000660,0901,300,30\n', encoding='utf-8')

    assert drop_date(str(p), '20260810') == 2
    lines = p.read_text(encoding='utf-8').strip().split('\n')
    assert len(lines) == 2 and lines[1].startswith('20260811')


def test_drop_date_on_a_missing_file_is_zero(tmp_path):
    """최초 배포일에는 그달 파일이 없다 — 여기서 죽으면 그날 분봉을 통째로 잃는다."""
    assert drop_date(str(tmp_path / 'nope.csv'), '20260810') == 0


def test_rerunning_the_day_replaces_instead_of_duplicating(monkeypatch, tmp_path):
    import csv as _csv
    bars = lambda *a, **k: [{'hhmm': '0900', 'price': 100, 'volume': 10}]
    _run_main(monkeypatch, tmp_path, bars)
    _run_main(monkeypatch, tmp_path, bars)

    p = next((tmp_path / 'data').glob('minute_*.csv'))
    with open(p, encoding='utf-8') as f:
        rows = list(_csv.DictReader(f))
    keys = [(r['date'], r['code'], r['hhmm']) for r in rows]
    assert len(keys) == len(set(keys)), f'재실행분이 중복으로 쌓였다: {keys}'
