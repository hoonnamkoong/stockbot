# -*- coding: utf-8 -*-
"""top100 응답에서 파생하는 국면 지표 — 추가 요청 0건.

지금까지 cols[4](등락률)만 쓰고 현재가·시가총액·거래량을 버렸다. 등락률 벡터
100개도 상승비율과 median 둘로 뭉개져, "전부 조금씩 올랐다"와 "몇 개가 급등하고
나머지는 빠졌다"가 같은 행으로 기록됐다.
"""
from src.pipeline.workers.trade_engine import market_extras, resolve_market_columns

REAL_HEADER = ['N', '종목명', '현재가', '전일비', '등락률', '액면가', '시가총액',
               '상장주식수', '외국인비율', '거래량', 'PER', 'ROE', '토론']


def test_실제_헤더에서_열_위치를_찾는다():
    # 2026-08-17 실측 응답. 등락률이 현행 고정 인덱스 4와 일치한다.
    cols = resolve_market_columns(REAL_HEADER)
    assert cols == {'price': 2, 'rate': 4, 'cap': 6, 'volume': 9}


def test_열이_밀려도_따라간다():
    shifted = ['N', '종목명', '신규열', '현재가', '전일비', '등락률', '액면가',
               '시가총액', '상장주식수', '외국인비율', '거래량']
    assert resolve_market_columns(shifted)['rate'] == 5


def test_헤더를_못_읽으면_None이다():
    assert resolve_market_columns(['N', '종목명', '???']) is None


def test_시총가중_상승비율은_동일가중과_다르다():
    # 대형주 하나만 오르고 소형주 셋이 빠진 날. 동일가중 25%, 시총가중은 훨씬 높다.
    out = market_extras(rates=[1.0, -1.0, -1.0, -1.0],
                        caps=[900.0, 10.0, 10.0, 10.0],
                        prices=[100.0] * 4, volumes=[1000.0] * 4)
    assert out['breadth_cap'] == 96.8
    assert out['up'] == 1
    assert out['down'] == 3


def test_분위수는_보간하지_않는다():
    out = market_extras(rates=[float(i) for i in range(1, 101)],
                        caps=[1.0] * 100, prices=[1.0] * 100, volumes=[1.0] * 100)
    # floor(q * (n-1))로 뽑는다 — 표본이 85~100으로 흔들려도 정의가 안 변한다.
    assert out['p10'] == 10.0
    assert out['p25'] == 25.0
    assert out['p75'] == 75.0
    assert out['p90'] == 90.0


def test_turnover는_억원_정수다():
    out = market_extras(rates=[1.0, 1.0], caps=[1.0, 1.0],
                        prices=[274500.0, 1645000.0], volumes=[21668266.0, 1000000.0])
    # (274500*21668266 + 1645000*1000000) / 1e8
    assert out['turnover'] == int((274500 * 21668266 + 1645000 * 1000000) / 1e8)


def test_재료가_없으면_그_열을_아예_넣지_않는다():
    # 헤더 해석 실패 시 등락률만 남는다. 0으로 채우면 '측정 못 함'이 값이 된다.
    out = market_extras(rates=[1.0, -1.0], caps=None, prices=None, volumes=None)
    assert 'breadth_cap' not in out
    assert 'turnover' not in out
    assert out['up'] == 1 and out['down'] == 1
    assert out['p10'] == -1.0


def test_시총_합이_0이면_breadth_cap을_넣지_않는다():
    out = market_extras(rates=[1.0, -1.0], caps=[0.0, 0.0],
                        prices=[1.0, 1.0], volumes=[1.0, 1.0])
    assert 'breadth_cap' not in out
