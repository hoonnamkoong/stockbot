# -*- coding: utf-8 -*-
"""신선도 감사는 '갱신됐나'뿐 아니라 '내용이 있나'도 본다.

2026-09-11 점검에서 드러난 구멍: 09-10 EOD가 헤더만 든 2,201바이트 종가 CSV를
배포했는데(정상 약 66KB) 감사는 **결손 0건**이었다. 파일이 그날 갱신됐기 때문이다.
같은 부류가 09-11 장중 아카이브(0.57MB, 평소 14~38MB)에서도 반복됐다.

크기로 재는 이유: 감사기가 이미 받는 트리 API 응답에 blob 크기가 들어 있어 추가
호출이 0이다. 행 수로 재려면 파일을 매일 내려받아야 하고(분봉은 12MB) 항목마다
날짜 열·형식이 달라 코드가 커진다. 누적 파일의 '하루치 결손'은 이 방식으로 못
잡지만, 그건 수집 시점에서 실패로 올리는 게 맞다.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core import clock
from src.data_freshness import audit

NOW = dt.datetime(2026, 9, 11, 8, 40, tzinfo=clock.KST)
FRESH = dt.datetime(2026, 9, 11, 7, 2, tzinfo=clock.KST)   # 오늘 아침 갱신됨
CAL = {'20260910': 'Y', '20260911': 'Y'}


def _entry(**kw):
    e = {'path': 'data/kospi_top100_close.csv', 'producer': 'eod_data.yml',
         'calendar': 'kr', 'max_age_sessions': 1, 'why': '종가 CSV'}
    e.update(kw)
    return e


def test_크기가_하한_미만이면_결손이다():
    """그 2,201바이트 파일이 이 경로로 잡힌다."""
    found = audit([_entry(min_bytes=16000)], lambda p: FRESH, NOW, CAL,
                  sizes={'data/kospi_top100_close.csv': 2201})
    assert [f['kind'] for f in found] == ['small']
    assert found[0]['bytes'] == 2201


def test_크기가_충분하면_결손이_아니다():
    assert audit([_entry(min_bytes=16000)], lambda p: FRESH, NOW, CAL,
                 sizes={'data/kospi_top100_close.csv': 66530}) == []


def test_min_bytes가_없는_항목은_영향이_없다():
    assert audit([_entry()], lambda p: FRESH, NOW, CAL,
                 sizes={'data/kospi_top100_close.csv': 10}) == []


def test_크기를_모르면_보고하지_않는다():
    """측정 불가를 결손으로 보고하면 거짓 경보가 된다 — 트리에 없으면 조용히 넘긴다."""
    assert audit([_entry(min_bytes=16000)], lambda p: FRESH, NOW, CAL, sizes={}) == []


def test_sizes를_안_주면_예전처럼_동작한다():
    """호출부가 아직 크기를 안 넘기는 경로(테스트·옛 스크립트)를 깨지 않는다."""
    assert audit([_entry(min_bytes=16000)], lambda p: FRESH, NOW, CAL) == []


def test_매니페스트에_크기_하한이_설정돼_있다():
    """정본 항목 셋에 하한이 붙어 있어야 실제로 잡힌다."""
    from src.data_freshness import load_manifest
    by = {e['path']: e for e in load_manifest()}
    for p in ('data/kospi_top100_close.csv', 'data/premarket_daily.csv'):
        assert by[p].get('min_bytes'), f'{p}에 min_bytes가 없다'
