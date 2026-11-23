# -*- coding: utf-8 -*-
"""우리 주문 기록으로 매도일을 특정한다 — 수량만으로는 못 가린다.

2026-11-23 첫 정산에서 3건이 막혔다. 사유가 전부 같았다:

    000111 수량이 맞는 매도를 특정하지 못했습니다
    (원장 2주 vs 조회 [('20261016', 2), ('20261023', 2), ('20261106', 2)])

한투 조회는 **계좌 전체**를 본다. 그 구간에 같은 수량 매도가 세 번 있었는데,
앞의 둘은 **프로그램이 낸 매도**였다(프로그램이 낸 타임스탑·손절). 사람이
낸 매도는 11-06 하나뿐이었다. 수량만 보면 셋이 똑같아 보인다.

**우리는 그 주문을 낼 때 이미 기록했다.** 프로그램 주문도 수동 주문도 전부
`/api/trade/order`를 지나고 라우트가 history.json에 적는다. 그 기록을 보면
어느 날 팔렸는지 알 수 있고, 날짜가 특정되면 한투에 **그 하루만** 물으면 된다.

왜 '수동 매도'를 찾나: 프로그램이 낸 매도는 원장이 그 자리에서 정산하므로
미정산으로 남지 않는다. 미정산 항목은 정의상 **프로그램이 내지 않은 매도**로
사라진 포지션이다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.pipeline.workers.program_trader import exit_date_from_orders


def _o(time, symbol, action, qty, origin=None):
    r = {'time': time, 'symbol': symbol, 'action': action, 'qty': qty}
    if origin:
        r['origin'] = origin
    return r


# 2026-11-23에 실제로 막힌 모양. 프로그램 매도 둘 + 수동 매도 하나.
REAL = [
    _o('2026-10-16 09:01:26', '000111', 'SELL', 2, 'program'),
    _o('2026-10-19 11:11:08', '000111', 'BUY', 2, 'program'),
    _o('2026-10-23 09:49:49', '000111', 'SELL', 2, 'program'),
    _o('2026-10-26 15:02:19', '000111', 'BUY', 2, 'program'),
    _o('2026-11-06 08:40:11', '000111', 'SELL', 2, 'manual'),
]


def test_실제로_막혔던_건을_수동_매도로_특정한다():
    assert exit_date_from_orders(REAL, '000111', 2, '20261011', '20261110') == '20261106'


def test_프로그램_매도는_고르지_않는다():
    """프로그램 매도는 원장이 이미 정산했다. 그걸 고르면 두 번 계상된다."""
    only_program = [r for r in REAL if r.get('origin') != 'manual']
    assert exit_date_from_orders(only_program, '000111', 2, '20261011', '20261110') == ''


def test_출처가_없는_옛_기록은_창_안_마지막_매도를_쓴다():
    """origin은 2026-11-24부터 적힌다. 그 전 기록에도 답을 줘야 한다.

    미정산으로 남았다는 것 자체가 '프로그램이 안 판 매도'라는 뜻이고, 원장이
    발견 직전까지 들고 있었으므로 앞선 매도는 되산 뒤의 다른 왕복이다.
    """
    old = [{k: v for k, v in r.items() if k != 'origin'} for r in REAL]
    assert exit_date_from_orders(old, '000111', 2, '20261011', '20261110') == '20261106'


def test_창_밖_매도는_보지_않는다():
    assert exit_date_from_orders(REAL, '000111', 2, '20261011', '20261105') == ''


def test_수량이_다르면_고르지_않는다():
    assert exit_date_from_orders(REAL, '000111', 5, '20261011', '20261110') == ''


def test_다른_종목은_섞이지_않는다():
    assert exit_date_from_orders(REAL, '000222', 2, '20261011', '20261110') == ''


def test_매수는_매도가_아니다():
    buys = [_o('2026-11-06 09:00:00', '000111', 'BUY', 2, 'manual')]
    assert exit_date_from_orders(buys, '000111', 2, '20261011', '20261110') == ''


def test_수동_매도가_여럿이면_마지막을_쓴다():
    rows = REAL + [_o('2026-11-09 10:00:00', '000111', 'SELL', 2, 'manual')]
    assert exit_date_from_orders(rows, '000111', 2, '20261011', '20261110') == '20261109'


def test_읽을_수_없는_기록은_건너뛴다():
    """망가진 한 줄 때문에 전체를 포기하지 않는다."""
    rows = [{'time': None}, {'symbol': '000111'}, 'garbage', None] + REAL
    assert exit_date_from_orders(rows, '000111', 2, '20261011', '20261110') == '20261106'


def test_기록이_없으면_빈_문자열():
    assert exit_date_from_orders([], '000111', 2, '20261011', '20261110') == ''
    assert exit_date_from_orders(None, '000111', 2, '20261011', '20261110') == ''


def test_수량_문자열도_읽는다():
    rows = [_o('2026-11-06 08:40:11', '000111', 'SELL', '2', 'manual')]
    assert exit_date_from_orders(rows, '000111', 2, '20261011', '20261110') == '20261106'


def test_action_대소문자를_가리지_않는다():
    rows = [_o('2026-11-06 08:40:11', '000111', 'sell', 2, 'manual')]
    assert exit_date_from_orders(rows, '000111', 2, '20261011', '20261110') == '20261106'
