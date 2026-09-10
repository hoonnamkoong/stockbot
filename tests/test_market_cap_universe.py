"""중립 유니버스 — 방향이 없는 종목 풀.

기존 유니버스는 전부 방향이 있다(오늘 오른 종목 / 내린 종목 / 고ROE / 버즈).
방향이 있는 풀은 방향이 반대인 전략과 구조적으로 안 맞는다. 2026-08-14 실측:

    [레인지] 진입 없음 — 채널폭 통과 19개 중
    저점에 가장 가까운 000660 저점 대비 +24.4% (기준 +3% 이내)

심5(레인지 스윙)는 "박스권 저점 매수"인데 버즈 후보(인기·급등주)를 받고 있었다.
저점 근처 후보가 한 종목도 들어올 수 없는 조합이었다. 심10도 SIDEWAYS 국면에서
같은 판단 함수를 쓴다.

[2026-09-11] 원천이 네이버 JSON API(src/data/naver_api.py)로 바뀌었다. 목록 조회·
페이지·중복·ETF 제외는 tests/test_naver_api.py가 본다. 여기는 유니버스 행 변환만 본다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data.market_cap_universe import fetch_top100, to_universe_rows


def _row(code, price=1000.0, volume=10, rate=1.0):
    return {'code': code, 'name': f'종목{code}', 'price': price, 'change_rate': rate,
            'volume': volume, 'amount': None, 'market_cap': 1.0}


def test_parses_code_name_price():
    rows = to_universe_rows([_row('005930'), _row('000660')])

    assert [r['code'] for r in rows] == ['005930', '000660']
    assert rows[0]['price'] == 1000


def test_rows_without_price_are_skipped():
    rows = to_universe_rows([_row('005930', price=None), _row('000660', price=0),
                             _row('035420')])

    assert [r['code'] for r in rows] == ['035420']


def test_amount_is_price_times_volume():
    """심5는 amount < 10억이면 continue — 키가 없으면 후보 전량이 첫 게이트에서 탈락했다."""
    assert to_universe_rows([_row('005930', price=1000.0, volume=10)])[0]['amount'] == 10_000


def test_missing_volume_leaves_no_amount_key():
    """0을 넣으면 '유동성 0'으로 오판된다. 모르면 키를 넣지 않는다."""
    assert 'amount' not in to_universe_rows([_row('005930', volume=None)])[0]


def test_change_rate_is_signed_percent_text():
    assert to_universe_rows([_row('005930', rate=-0.5)])[0]['change_rate'] == '-0.50%'
    assert 'change_rate' not in to_universe_rows([_row('005930', rate=None)])[0]


def test_fetch_failure_is_none_not_empty():
    """조회 실패를 빈 리스트로 돌려주면 '후보가 없다'가 되어 그날 그 심이
    조용히 아무것도 안 한다. 호출부가 둘을 정반대로 처리한다."""
    def boom(*a):
        raise RuntimeError('네트워크 차단')

    assert fetch_top100(fetch=lambda *a: None) is None
    assert fetch_top100(fetch=boom) is None


def test_limit_is_respected():
    out = fetch_top100(limit=2, fetch=lambda kind, market, limit: [
        _row('005930'), _row('000660'), _row('035420')])

    assert len(out) == 2
