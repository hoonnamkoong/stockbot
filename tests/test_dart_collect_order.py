# -*- coding: utf-8 -*-
"""DART 수집 순서 — 심이 보는 유니버스를 먼저 받는다.

2026-11-28 실측이 이 파일의 존재 이유다. 수집은 종목당 8.5초(호출 4회 × 왕복 ~2초)라
상장사 4,022개가 **9.5시간**이고 잡 타임아웃은 120분이다. 그날 114분을 써서 800개를
받았는데 종목코드 순서(`000010`부터)로 돌아서 **정작 심이 보는 top100 중 38개만**
들어왔다. 심3은 나머지 62종목에서 `no_ttm_val`, 심11은 `no_eps`로 계속 탈락한다.

유니버스를 앞세우면 같은 120분 안에 그 100개가 먼저 끝난다(100 × 8.5초 ≈ 15분).
토요일 보충 cron을 5주 기다리는 것과 한 런의 차이다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from collect_dart_fundamentals import load_universe_codes, order_todo  # noqa: E402

TARGET = '2026-11014'


def _todo(*codes):
    """(종목코드, 법인코드) 쌍. 법인코드는 순서 판정에 쓰이지 않는다."""
    return [(c, f'corp{c}') for c in codes]


def test_universe_codes_come_first():
    """번호가 뒤라도 유니버스면 앞으로 온다 — 373220(LG에너지솔루션)이 그 사례다."""
    todo = _todo('000010', '000020', '373220')
    out = order_todo(todo, cache={}, target=TARGET, universe={'373220'})
    assert [c for c, _ in out] == ['373220', '000010', '000020']


def test_retry_rule_still_dominates():
    """1차 키는 재시도다 — 자료 없음으로 확인된 유니버스 종목이 자료 있는
    신규 종목을 밀어내면 안 된다. 두 키를 뒤집으면 이 단언이 깨진다."""
    cache = {'373220': {'tried': TARGET}}        # 유니버스인데 이미 빈 것으로 확인
    todo = _todo('000010', '373220')             # 000010은 미시도
    out = order_todo(todo, cache=cache, target=TARGET, universe={'373220'})
    assert [c for c, _ in out] == ['000010', '373220']


def test_universe_ordering_applies_inside_each_retry_group():
    """각 묶음 안에서 유니버스가 앞선다 — 미시도 묶음과 재시도 묶음 모두."""
    cache = {'000020': {'tried': TARGET}, '005930': {'tried': TARGET}}
    todo = _todo('000010', '000020', '005930', '373220')
    out = order_todo(todo, cache=cache, target=TARGET,
                     universe={'005930', '373220'})
    #   미시도: 373220(유니버스) → 000010      재시도: 005930(유니버스) → 000020
    assert [c for c, _ in out] == ['373220', '000010', '005930', '000020']


def test_stable_within_same_key():
    """같은 키 안에서는 종목코드 순서가 유지된다(안정 정렬)."""
    todo = _todo('000030', '000010', '000020')
    out = order_todo(todo, cache={}, target=TARGET, universe=set())
    assert [c for c, _ in out] == ['000030', '000010', '000020']


def test_empty_universe_keeps_previous_behavior():
    """유니버스를 못 읽어도 수집을 멈추지 않는다 — 종전 순서로 돈다."""
    cache = {'000020': {'tried': TARGET}}
    todo = _todo('000010', '000020', '000030')
    out = order_todo(todo, cache=cache, target=TARGET, universe=set())
    assert [c for c, _ in out] == ['000010', '000030', '000020']


def test_load_universe_codes_reads_csv(tmp_path):
    (tmp_path / 'ohlcv_top100.csv').write_text(
        'date,code,name,close\n20261127,005930,삼성전자,179500\n'
        '20261127,373220,LG에너지솔루션,400000\n'
        '20261126,005930,삼성전자,171500\n',
        encoding='utf-8')
    assert load_universe_codes(str(tmp_path)) == {'005930', '373220'}


def test_load_universe_codes_missing_file_is_empty_not_error(tmp_path):
    """없으면 빈 집합이다 — 유니버스 파일 결손이 수집 전체를 죽이면 안 된다."""
    assert load_universe_codes(str(tmp_path)) == set()
