"""중립 유니버스 — 방향이 없는 종목 풀.

기존 유니버스는 전부 방향이 있다(오늘 오른 종목 / 내린 종목 / 고ROE / 버즈).
방향이 있는 풀은 방향이 반대인 전략과 구조적으로 안 맞는다. 2026-08-14 실측:

    [레인지] 진입 없음 — 채널폭 통과 19개 중
    저점에 가장 가까운 000660 저점 대비 +24.4% (기준 +3% 이내)

심5(레인지 스윙)는 "박스권 저점 매수"인데 버즈 후보(인기·급등주)를 받고 있었다.
저점 근처 후보가 한 종목도 들어올 수 없는 조합이었다. 심10도 SIDEWAYS 국면에서
같은 판단 함수를 쓴다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.data.market_cap_universe import fetch_top100, parse_rows

_ROW = ('<tr><td>{n}</td><td><a href="/item/main.naver?code={code}">{name}</a></td>'
        '<td>{price:,}</td><td>0</td><td>+1.00%</td></tr>')


def _page(codes):
    rows = ''.join(_ROW.format(n=i + 1, code=c, name=f'종목{c}', price=1000 + i)
                   for i, c in enumerate(codes))
    return f'<table class="type_2">{rows}</table>'.encode('euc-kr')


class _Res:
    def __init__(self, content):
        self.content = content


def test_parses_code_name_price():
    rows = parse_rows(_page(['005930', '000660']))

    assert [r['code'] for r in rows] == ['005930', '000660']
    assert rows[0]['price'] == 1000


def test_non_six_digit_codes_are_skipped():
    """ETF·우선주 링크나 광고 행이 섞여 들어오면 코드가 아닌 값이 잡힌다."""
    rows = parse_rows(_page(['005930', 'ABCDEF', '12345']))

    assert [r['code'] for r in rows] == ['005930']


def test_fetch_failure_is_none_not_empty():
    """조회 실패를 빈 리스트로 돌려주면 '후보가 없다'가 되어 그날 그 심이
    조용히 아무것도 안 한다. 호출부가 둘을 정반대로 처리한다."""
    def boom(url):
        raise RuntimeError('네트워크 차단')

    assert fetch_top100(get=boom) is None


def test_duplicates_across_pages_are_dropped():
    pages = iter([_Res(_page(['005930', '000660'])), _Res(_page(['000660', '035420']))])
    out = fetch_top100(limit=100, get=lambda url: next(pages))

    assert [r['code'] for r in out] == ['005930', '000660', '035420']


def test_limit_is_respected():
    out = fetch_top100(limit=2, get=lambda url: _Res(_page(['005930', '000660', '035420'])))

    assert len(out) == 2
