# -*- coding: utf-8 -*-
"""국면 관측 이력 CSV — 10분 해상도 축적.

지금까지 _hour_label('%H:00')이 10분 관측의 5/6을 버렸다. 여기서 분까지 남긴다.
"""
import io
import os

from src.strategy.regime_observations import (
    MAX_DISTINCT_DATES, OBS_EXTRA, OBS_HEADER, append_observation, format_row,
    parse_observations, trim_to_recent_dates,
)


def _read(path):
    with io.open(path, encoding='utf-8-sig') as f:
        return f.read()


def test_헤더가_계약이다():
    assert OBS_HEADER == [
        'ts_kst', 'breadth', 'momentum', 'trend', 'sample', 'source',
        'breadth_cap', 'p10', 'p25', 'p75', 'p90', 'up', 'down', 'turnover',
    ], '기존 6열의 이름과 순서는 불변이다 — db-data에 426행이 이 스키마로 쌓여 있다'
    assert list(OBS_EXTRA) == OBS_HEADER[6:]


def test_구_스키마_6열_행을_읽는다():
    # db-data의 아카이브가 이 모양이다. 새 파서가 이걸 못 읽으면 426행이 통째로 사라진다.
    text = 'ts_kst,breadth,momentum,trend,sample,source\n' \
           '2026-08-07 09:01,37.0,0.00,13.1,100,top100_live\n'
    rows = parse_observations(text)
    assert len(rows) == 1
    assert rows[0]['breadth'] == 37.0
    assert rows[0]['trend'] == 13.1
    for col in OBS_EXTRA:
        assert rows[0][col] is None, f'{col}은 없는 것이지 0이 아니다'


def test_신규_열_왕복(tmp_path):
    p = str(tmp_path / 'obs.csv')
    extra = {'breadth_cap': 63.2, 'p10': -2.15, 'p25': -0.80,
             'p75': 1.44, 'p90': 3.07, 'up': 61, 'down': 37, 'turnover': 128450}
    assert append_observation(p, '2026-08-17 09:10', 61.0, 0.42, 44.9, 100,
                              'top100_live', extra=extra) is True
    row = parse_observations(_read(p))[0]
    for col, want in extra.items():
        assert row[col] == want


def test_신규_열이_없으면_빈_칸이고_None으로_읽힌다(tmp_path):
    p = str(tmp_path / 'obs.csv')
    append_observation(p, '2026-08-17 09:10', 61.0, 0.42, 44.9, 100, 'top100_live')
    line = _read(p).strip().splitlines()[1]
    assert line.endswith(',,,,,,,,'), '신규 8열이 빈 칸이어야 한다 — 0으로 채우지 않는다'
    row = parse_observations(_read(p))[0]
    for col in OBS_EXTRA:
        assert row[col] is None


def test_모르는_열은_시끄럽게_거절한다(tmp_path):
    # 오타가 조용히 버려지면 그 기간의 열이 통째로 빈다. 몇 달 뒤에 발견된다.
    import pytest
    p = str(tmp_path / 'obs.csv')
    with pytest.raises(ValueError):
        append_observation(p, '2026-08-17 09:10', 61.0, 0.42, 44.9, 100,
                           'top100_live', extra={'turnovr': 1})


def test_정수열은_소수점_없이_쓴다(tmp_path):
    p = str(tmp_path / 'obs.csv')
    append_observation(p, '2026-08-17 09:10', 61.0, 0.42, 44.9, 100, 'top100_live',
                       extra={'up': 61, 'down': 37, 'turnover': 128450})
    line = _read(p).strip().splitlines()[1]
    assert ',61,37,128450' in line


def test_새_파일은_헤더와_한_행을_쓴다(tmp_path):
    p = str(tmp_path / 'obs.csv')
    assert append_observation(p, '2026-07-30 09:10', 51.0, -0.12, 39.0, 100, 'top100_live') is True
    rows = parse_observations(_read(p))
    assert len(rows) == 1
    assert rows[0]['ts'] == '2026-07-30 09:10'
    assert rows[0]['breadth'] == 51.0
    assert rows[0]['momentum'] == -0.12
    assert rows[0]['trend'] == 39.0
    assert rows[0]['sample'] == 100
    assert rows[0]['source'] == 'top100_live'


def test_같은_분에_두_번_돌면_한_행이다(tmp_path):
    p = str(tmp_path / 'obs.csv')
    append_observation(p, '2026-07-30 09:10', 51.0, -0.12, 39.0, 100, 'top100_live')
    assert append_observation(p, '2026-07-30 09:10', 99.0, 9.9, 1.0, 80, 'candidates') is False
    rows = parse_observations(_read(p))
    assert len(rows) == 1
    assert rows[0]['breadth'] == 51.0, '첫 값을 유지한다 — 같은 분의 재실행이 값을 흔들면 안 된다'


def test_10분_간격_관측이_전부_남는다(tmp_path):
    p = str(tmp_path / 'obs.csv')
    for i, m in enumerate(range(0, 60, 10)):
        append_observation(p, f'2026-07-30 09:{m:02d}', 50.0 + i, 0.0, 10.0, 100, 'top100_live')
    rows = parse_observations(_read(p))
    assert len(rows) == 6, '_hour_label 시절에는 1건만 남았다'
    assert [r['ts'] for r in rows] == [f'2026-07-30 09:{m:02d}' for m in range(0, 60, 10)]


def test_표본이_적어도_기록한다(tmp_path):
    # 현행 _fetch_top100_breadth는 표본 80 미만이면 None을 반환해 통째로 버린다.
    # 확률 모형에서는 약한 증거이므로 버리지 않는다.
    p = str(tmp_path / 'obs.csv')
    assert append_observation(p, '2026-07-30 09:10', 40.0, -1.0, 5.0, 55, 'top100_live') is True
    assert parse_observations(_read(p))[0]['sample'] == 55


def test_trend가_없으면_빈_칸이고_None으로_읽힌다(tmp_path):
    p = str(tmp_path / 'obs.csv')
    append_observation(p, '2026-07-30 09:10', 40.0, -1.0, None, 100, 'top100_live')
    assert parse_observations(_read(p))[0]['trend'] is None


def test_롤링은_거래일_단위다():
    rows = [{'ts': f'2026-{m:02d}-{d:02d} 09:10', 'breadth': 1.0, 'momentum': 0.0,
             'trend': None, 'sample': 100, 'source': 's'}
            for m in (5, 6, 7) for d in range(1, 26)]
    kept = trim_to_recent_dates(rows, max_dates=10)
    assert len({r['ts'][:10] for r in kept}) == 10
    assert kept[-1] is rows[-1], '최신 행이 남는다'


def test_append가_거래일_상한을_지킨다(tmp_path):
    # 상한(60)을 실제로 넘겨야 의미가 있다 — 월 경계를 넘어 65개 날짜를 만든다.
    p = str(tmp_path / 'obs.csv')
    made = []
    for month, last in ((6, 30), (7, 31), (8, 31)):
        for d in range(1, last + 1):
            if len(made) >= MAX_DISTINCT_DATES + 5:
                break
            made.append(f'2026-{month:02d}-{d:02d} 09:10')
    assert len(made) == MAX_DISTINCT_DATES + 5, '상한을 넘기지 못하면 이 테스트는 아무것도 검증하지 않는다'
    for ts in made:
        append_observation(p, ts, 50.0, 0.0, None, 100, 's')

    rows = parse_observations(_read(p))
    dates = sorted({r['ts'][:10] for r in rows})
    assert len(dates) == MAX_DISTINCT_DATES, '오래된 5일이 잘려나간다'
    assert dates[-1] == made[-1][:10], '최신 날짜가 남는다'
    assert made[0][:10] not in dates, '가장 오래된 날짜는 사라진다'


def test_임시파일이_남지_않는다(tmp_path):
    # 임시파일 + os.replace로 쓴다(중간에 죽어도 이력이 반토막 나지 않게).
    # 뒷정리가 안 되면 db-data에 .tmp가 쌓여 배포된다.
    p = str(tmp_path / 'obs.csv')
    append_observation(p, '2026-07-30 09:10', 50.0, 0.0, None, 100, 's')
    append_observation(p, '2026-07-30 09:20', 50.0, 0.0, None, 100, 's')
    assert not os.path.exists(p + '.tmp')
    assert len(parse_observations(_read(p))) == 2


def test_깨진_행은_건너뛰고_나머지를_읽는다():
    blank_extra = ',' * len(OBS_EXTRA)
    text = ','.join(OBS_HEADER) + '\n' \
           + f'2026-07-30 09:10,51.0,-0.12,39.0,100,top100_live{blank_extra}\n' \
           + 'garbage\n' \
           + f'2026-07-30 09:20,52.0,0.05,39.0,100,top100_live{blank_extra}\n'
    rows = parse_observations(text)
    assert [r['ts'] for r in rows] == ['2026-07-30 09:10', '2026-07-30 09:20']


def test_format_row는_문자열_리스트다():
    rec = {'ts': '2026-07-30 09:10', 'breadth': 51.0, 'momentum': -0.125,
           'trend': None, 'sample': 100, 'source': 'x'}
    assert format_row(rec) == ['2026-07-30 09:10', '51.0', '-0.13', '', '100', 'x',
                               '', '', '', '', '', '', '', '']
