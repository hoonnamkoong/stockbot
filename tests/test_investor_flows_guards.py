# -*- coding: utf-8 -*-
"""수급 CSV에 장중 0행이 쌓이지 않게 하고, 이미 쌓인 0행은 다시 받는다.

2026-09-11 실측: `investor_flows.csv`의 20260911 행 399개가 전부 0이었고, 20260910에도
0행이 44개 남아 있었다. 그 44개는 **전부 다음 날 유니버스에서 빠진 종목**이었고,
41개는 09-09에는 실제 값이 있었다.

구조는 이렇다. KIS FHKST01010900은 최근 30거래일을 주는데, 장중에 받으면 오늘 행이
전부 0으로 온다(그 세션이 아직 안 끝났으니까). 병합 규칙은 "같은 (date, code)는 새
값으로 덮는다"라, 다음 날 그 종목을 다시 받으면 고쳐진다 — **유니버스에 남아 있는
동안만.** 빠지면 0이 영구히 남는다.

프리마켓 워크플로는 늦게 발화한 cron 런이 장중에 도는 일이 잦아(PR #122로 직렬화한
뒤에도 11:30 이후에 돈다) 이 경로는 예외가 아니라 정상이다.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from scripts.fetch_investor_flows import unsettled_today, zero_flow_codes


def test_장중이면_오늘_행은_저장하지_않는다():
    """09:14 KST — 그 세션은 아직 안 끝났다. 0이 아니라 '아직 없음'이다."""
    assert unsettled_today(dt.datetime(2026, 9, 11, 9, 14)) == '20260911'


def test_마감_뒤에는_오늘_행을_저장한다():
    assert unsettled_today(dt.datetime(2026, 9, 11, 16, 0)) is None


def test_마감_정각은_확정으로_본다():
    assert unsettled_today(dt.datetime(2026, 9, 11, 15, 30)) is None


def _rows(*triples):
    """(date, code, net) → 병합 딕셔너리. net=0이면 순매수 3종이 전부 0인 행."""
    out = {}
    for d, c, net in triples:
        out[(d, c)] = {'date': d, 'code': c, 'close': '1000',
                       'prsn_net': str(net), 'frgn_net': str(net), 'orgn_net': str(net)}
    return out


def test_0행_종목은_유니버스에_없어도_다시_받는다():
    """09-10의 44종목이 이 경로로 복구된다. 그중 41개는 09-09에 실제 값이 있었다 —
    창 안에 값이 있는 날이 하나라도 있으면 '진짜 0'이 아니라 장중에 쓰인 0이다."""
    rows = _rows(('20260909', '000660', 54321), ('20260910', '000660', 0),
                 ('20260910', '005930', 12345))
    assert zero_flow_codes(rows) == ['000660']


def test_창_밖의_0행은_다시_받지_않는다():
    """TR이 최근 30거래일만 준다 — 그보다 오래된 0행은 요청해도 안 고쳐진다."""
    old = [(f'202607{d:02d}', '000660', 0) for d in range(1, 2)]
    recent = [(f'202609{d:02d}', '005930', 999) for d in range(1, 31)]
    rows = _rows(*old, *recent)
    assert zero_flow_codes(rows) == []


def test_창_내내_0인_종목은_다시_받지_않는다():
    """ETF처럼 실제로 순매수가 0으로만 오는 종목이 있다. 이런 걸 계속 재요청하면
    자기치유가 아니라 매 런 붙는 상수 비용이 된다(실측 0.885초/종목)."""
    rows = _rows(('20260909', '069500', 0), ('20260910', '069500', 0),
                 ('20260909', '000660', 0), ('20260910', '000660', 777))
    assert zero_flow_codes(rows) == ['000660']
