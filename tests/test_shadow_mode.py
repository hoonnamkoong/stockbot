# -*- coding: utf-8 -*-
"""그림자 운전 — 폰이 계좌를 못 바꾸게 한다 (이관 3단계).

폰과 옛 경로는 **같은 계좌**를 본다. 폰이 무엇이든 실행하면 그건 시험이 아니라
중복 실행이다. 5거래일 내내 이 가드 하나에 계좌가 걸려 있다.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.trade import shadow

REPO = os.path.join(os.path.dirname(__file__), '..')


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv('SHADOW_MODE', raising=False)
    monkeypatch.delenv('STOCKBOT_RUNNER', raising=False)


# ── 판정 ────────────────────────────────────────────────────────

def test_기본은_그림자가_아니다():
    """지금 도는 옛 경로가 막히면 안 된다."""
    assert shadow.is_shadow() is False


def test_SHADOW_MODE_1이면_그림자다(monkeypatch):
    monkeypatch.setenv('SHADOW_MODE', '1')
    assert shadow.is_shadow() is True


def test_폰은_환경변수와_무관하게_그림자다(monkeypatch):
    """**SHADOW_MODE를 빠뜨리는 실수의 대가가 돈이다.** 그래서 환경변수 하나에
    걸지 않는다 — runner가 폰이면 그것만으로 주문 권한이 없다."""
    monkeypatch.setenv('STOCKBOT_RUNNER', 'phone')
    assert shadow.is_shadow() is True


def test_승격은_한_곳에서만_일어난다():
    """4단계에서 'phone'을 이 집합에서 빼는 것이 승격 결정 그 자체다.
    지점이 하나여야 리뷰에서 보인다."""
    assert 'phone' in shadow._SHADOW_RUNNERS
    assert 'actions-trading' not in shadow._SHADOW_RUNNERS


def test_차단_결과는_예외가_아니라_실패값이다():
    """예외를 던지면 상위 except가 '주문 실패' 알림을 보내 5일 내내 텔레그램이
    울린다. 차단은 장애가 아니다."""
    res = shadow.blocked_order_result('buy', '005930')
    assert res['success'] is False
    assert res['shadow'] is True


def test_차단은_조용하지_않다():
    """시도가 기록되지 않으면 '결정이 없었다'와 구분되지 않는다."""
    said = []
    shadow.refused('주문', 'buy 005930', log=said.append)
    assert said and '차단' in said[0]


# ── 두 출구가 실제로 막히는가 ────────────────────────────────────

def test_그림자에서_주문이_HTTP를_타지_않는다(monkeypatch):
    monkeypatch.setenv('SHADOW_MODE', '1')
    from src import trade_executor

    def boom(*a, **k):
        raise AssertionError('그림자인데 주문이 나갔다')

    monkeypatch.setattr(trade_executor.requests, 'post', boom)
    res = trade_executor.place_order_via_vercel('buy', '005930', 1, 70000)
    assert res['success'] is False and res['shadow'] is True


def test_그림자에서_주문취소가_KIS를_타지_않는다(monkeypatch):
    """취소는 Vercel을 우회하므로 WEBHOOK_SECRET 부재로도 안 막힌다.
    폰이 취소하면 **옛 경로가 낸 진짜 주문**이 거둬진다."""
    monkeypatch.setenv('SHADOW_MODE', '1')
    from src.trade import order_cancel

    monkeypatch.setattr(order_cancel, 'get_access_token',
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError('그림자인데 취소가 나갔다')))
    assert order_cancel.cancel_order('0001', '005930', 1) is False


# ── 가드: 새 출구가 생기면 여기서 잡는다 ─────────────────────────

# 계좌를 바꾸는 엔드포인트. 이 문자열이 프로덕션에 나타나는 파일은 아래
# 목록에 있어야 하고, **목록은 늘리기 전에 그 파일이 is_shadow를 보게 만든다.**
_MUTATING = ('/api/trade/order', 'order-rvsecncl', 'order-cash')

# 각 파일이 이 엔드포인트를 언급하는 이유. 값이 True면 **그 파일 안에서**
# is_shadow를 확인해야 한다(직접 호출한다는 뜻).
_KNOWN = {
    'src/trade_executor.py': True,          # 신규 주문 — Vercel 경유
    'src/trade/order_cancel.py': True,      # 미체결 취소 — KIS 직접
    'src/pipeline/workers/program_trader.py': False,  # 독스트링 언급뿐(위 둘을 호출한다)
}


def _production_py():
    skip = ('_legacy_backups', 'scratch', 'tests', 'node_modules', '.git',
            '.next', 'out', 'dist', '__pycache__')
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f.endswith('.py') and not f.startswith('tmp_') and 'legacy' not in f:
                yield os.path.join(root, f)


def test_계좌를_바꾸는_파일은_전부_알려져_있다():
    """새 주문·취소 경로가 생기면 여기서 빨개진다. 그때 할 일은 목록에 줄을
    더하는 게 아니라 **그 경로에 is_shadow를 붙이는 것**이다."""
    found = set()
    for path in _production_py():
        rel = os.path.relpath(path, REPO).replace(os.sep, '/')
        if rel.startswith('src/trade/shadow.py'):
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            body = f.read()
        if any(m in body for m in _MUTATING):
            found.add(rel)
    assert found == set(_KNOWN), (
        f'계좌를 바꾸는 엔드포인트를 언급하는 파일이 바뀌었다.\n'
        f'  새로 생김: {sorted(found - set(_KNOWN))}\n'
        f'  사라짐   : {sorted(set(_KNOWN) - found)}')


def test_직접_부르는_파일은_is_shadow를_본다():
    for rel, must_guard in _KNOWN.items():
        if not must_guard:
            continue
        with open(os.path.join(REPO, rel), encoding='utf-8') as f:
            body = f.read()
        assert 'is_shadow' in body, f'{rel}이 계좌를 바꾸는데 그림자 가드가 없다'


def test_가드가_실제로_무언가를_잡는다():
    """**헛통과를 막는다.** 오늘(2026-09-09) net 가드가 정규식에 리터럴
    백스페이스가 박혀 아무것도 검사하지 않은 채 초록이었다."""
    assert any(m in open(os.path.join(REPO, 'src/trade_executor.py'),
                         encoding='utf-8').read() for m in _MUTATING)
    assert re.search(r'order-rvsecncl',
                     open(os.path.join(REPO, 'src/trade/order_cancel.py'),
                          encoding='utf-8').read())
