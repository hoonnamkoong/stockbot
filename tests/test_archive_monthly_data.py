# -*- coding: utf-8 -*-
"""월간 아카이브: 지난달 데이터를 메일로 보내고, 보낸 것만 지운다.

db-data는 2026-09-04 기준 1.0GB이고 그 86%가 이력이다. 데이터를 계속 쌓으면
public 레포가 GitHub 권장 상한을 넘는다. 그래서 서버에는 **2개월치만** 두고
지난달치는 메일로 내보낸다.

여기서 제일 중요한 규칙은 **보낸 것만 지운다**는 것이다. KIS 분봉·체결은 당일치만
조회되므로 지운 달은 복구할 방법이 없다. 메일이 안 나갔는데 지우면 그 달이
영영 사라진다 — 그래서 판정은 fail-closed다.

두 번째 규칙은 **파일별로 나눠 보낸다**는 것이다. 2026-08 한 달치가 약 95MB인데
(minute 33.8 + post_titles 24.8 + money 24.4 + diag 7.4 …) Gmail 첨부 한도는
25MB이고 base64 인코딩이 33%를 더한다. 한 통에 못 넣는다.
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.archive_monthly_data import (
    group_by_month, month_of, month_to_archive, months_to_delete,
)


def test_파일명에서_달을_읽는다():
    """월별·일별·레거시 형식이 섞여 있다 — 일별 분할(2026-09-04) 전후."""
    assert month_of('money_2026-09-04.csv') == '2026-09'
    assert month_of('money_2026-09.csv') == '2026-09'
    assert month_of('sim12_diag_2026-08.csv') == '2026-08'
    assert month_of('sim1_diag_2026-08_v1.csv') == '2026-08'
    assert month_of('minute_2026-08.csv') == '2026-08'
    assert month_of('trending_integrated_2026-08.xlsx') == '2026-08'
    assert month_of('post_titles_2026072.csv') == '2026-07', '구분자 없는 레거시'
    # 마지막 날짜 토큰을 쓰면 시각(225705)을 2257-05로 읽는다 — 실측 오탐이다.
    assert month_of('trending_integrated_20260209_225705.csv') == '2026-02'
    assert month_of('premarket_news_20260831.csv') == '2026-08'


def test_달이_없는_파일은_대상이_아니다():
    """상태 파일은 아카이브 대상이 아니다 — 지우면 매매가 백지에서 시작한다."""
    assert month_of('rank_state.json') is None
    assert month_of('sim_donchian_state.json') is None
    assert month_of('kospi_top100_close.csv') is None
    assert month_of('sim11_watchlist.json') is None


def test_지난달을_보낸다():
    assert month_to_archive(dt.date(2026, 9, 1)) == '2026-08'
    assert month_to_archive(dt.date(2026, 1, 3)) == '2025-12', '연말 경계'


def test_보낸_달만_지운다():
    """fail-closed. 메일이 안 나갔으면 그 달은 남긴다 — 복구가 없다."""
    log = {'2026-06': {'sent_at': '2026-07-01T09:00:00+09:00'}}
    months = ['2026-06', '2026-07', '2026-08', '2026-09']
    got = months_to_delete(dt.date(2026, 9, 1), log, months)
    assert got == ['2026-06'], (
        f'2026-07은 아카이브 기록이 없어 남아야 한다 — 실제 {got}')


def test_최근_두_달은_보내도_안_지운다():
    """서버에 2개월치를 남긴다 — 지난달은 보냈어도 유예로 한 달 더 둔다."""
    log = {m: {'sent_at': 'x'} for m in ('2026-07', '2026-08', '2026-09')}
    got = months_to_delete(dt.date(2026, 9, 15), log, ['2026-07', '2026-08', '2026-09'])
    assert got == ['2026-07'], f'2026-08(지난달)·2026-09(이번달)은 남는다 — 실제 {got}'


def test_파일을_달별로_묶는다(tmp_path):
    for n in ('money_2026-08-01.csv', 'money_2026-08-02.csv',
              'minute_2026-07.csv', 'rank_state.json'):
        (tmp_path / n).write_text('x', encoding='utf-8')
    got = group_by_month([str(tmp_path / n) for n in os.listdir(tmp_path)])
    assert sorted(got) == ['2026-07', '2026-08']
    assert len(got['2026-08']) == 2
    assert 'rank_state.json' not in json.dumps(got), '상태 파일이 섞이면 안 된다'


def test_작은_파일이_많은_달은_한_통으로_묶인다():
    """파일당 한 통이면 2026-06처럼 파일 180개인 달에 180통이 나간다."""
    from scripts.archive_monthly_data import plan_batches
    sized = [(f'f{i}.csv', 10_000) for i in range(180)]     # 합계 1.8MB
    assert len(plan_batches(sized, cap=15_000_000)) == 1


def test_큰_달은_한도_아래로_쪼개진다():
    """2026-08은 96.3MB다 — Gmail 첨부 한도(25MB, base64로 실질 18MB) 위."""
    from scripts.archive_monthly_data import plan_batches
    sized = [('a', 9_000_000), ('b', 9_000_000), ('c', 9_000_000)]
    got = plan_batches(sized, cap=15_000_000)
    assert [len(b) for b in got] == [1, 1, 1], f'각 통이 한도 아래여야 한다 — {got}'


def test_혼자_한도를_넘는_파일은_쪼개지_않는다():
    """쪼갠 조각은 사람이 다시 붙여야 하고, 그 절차가 없으면 복구가 안 된다."""
    from scripts.archive_monthly_data import plan_batches
    got = plan_batches([('huge', 40_000_000), ('small', 1_000)], cap=15_000_000)
    assert got == [['huge'], ['small']]
