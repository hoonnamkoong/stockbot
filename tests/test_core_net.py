# -*- coding: utf-8 -*-
"""외부 호출 정책은 한 곳에서만 정한다 — `src/core/net.py`.

## 왜 필요했나 (2026-09-08 실측)

`requests.get/post` 호출이 **46곳**이고 타임아웃이 **7종**이었다
(3·5·6·8·10·15·20초). connect와 read를 나눈 곳은 1곳, 차단기가 있는 곳도 1곳
(둘 다 그날 KIS에 넣은 것)이다.

그날 아침 사고가 이 구조에서 나왔다. **어느 한 호출도 틀리지 않았다:**

    한 호출의 재시도 예산 = 3 + 0.3 + 3 + 0.6 + 3 = 9.9초   (합리적)
    5종목                 = 49.5초                          (실측 50.0초)
    구간 3개              = 132초                           (잡 예산 180초)

호출부는 각자 맞았는데 **곱해져서** 잡이 잘렸다. 그래서 곱셈을 막는 일은
호출부가 아니라 이 모듈이 한다.

## 오늘 KIS 차단기가 못 하는 것

`KISDataProvider._conn_fail_streak`는 클래스 레벨이라 **대상 구분이 없다.**
네이버가 죽어도 KIS 차단기는 모르고, 반대도 마찬가지다. 차단기는 대상별로
격리돼야 한 서비스의 장애가 다른 서비스를 막지 않는다.

## 청산은 막지 않는다

주문 등급(`CRITICAL`)은 차단기를 걸지 않는다. "청산은 무조건 나가야 한다"가
이 레포의 규칙이고, 매도를 차단기가 막으면 리스크를 줄이는 행동이 봉쇄된다.
"""
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core import net

REPO = os.path.join(os.path.dirname(__file__), '..')


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    """차단기 상태는 프로세스 상태다 — 테스트마다 격리한다."""
    monkeypatch.setattr(net, '_STREAKS', {})
    monkeypatch.setattr(net.time, 'sleep', lambda _s: None)


class _Res:
    def __init__(self, status=200):
        self.status_code = status


def _spy(monkeypatch, results):
    calls = []

    def fake_get(url, **kw):
        calls.append(kw)
        item = results[min(len(calls) - 1, len(results) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(net.requests, 'get', fake_get)
    return calls


# ── 등급이 정책을 정한다 ────────────────────────────────────────────

def test_등급이_connect와_read를_나눠_넘긴다(monkeypatch):
    """하나의 숫자로 묶으면 '연결은 빨리 포기하고 응답은 기다린다'를 못 한다.
    46곳 중 이걸 하던 곳은 1곳뿐이었다."""
    calls = _spy(monkeypatch, [_Res()])

    net.get('https://x/y', policy=net.FAST, target='x')

    assert calls[0]['timeout'] == (net.FAST.connect, net.FAST.read)


def test_호출부는_숫자를_고르지_않는다():
    """정책은 이름으로 고른다 — 숫자를 호출부에 두면 다시 7종으로 갈라진다."""
    assert {net.FAST.name, net.BULK.name, net.CRITICAL.name} == {
        'FAST', 'BULK', 'CRITICAL'}


# ── 재시도 ──────────────────────────────────────────────────────────

def test_연결_실패는_재시도한다(monkeypatch):
    """러너 egress의 짧은 blip을 흡수한다(2026-08-13)."""
    calls = _spy(monkeypatch, [requests.ConnectTimeout('boom'), _Res()])

    assert net.get('https://x/y', policy=net.FAST, target='x') is not None
    assert len(calls) == 2


def test_서버가_대답한_실패는_재시도하지_않는다(monkeypatch):
    """HTTP 500은 서버가 대답한 것이다. 다시 던지면 유량제한만 키운다."""
    calls = _spy(monkeypatch, [_Res(500)])

    assert net.get('https://x/y', policy=net.FAST, target='x') is None
    assert len(calls) == 1


def test_예산을_소진하면_None이지_지어낸_값이_아니다(monkeypatch):
    _spy(monkeypatch, [requests.ConnectionError('boom')])

    assert net.get('https://x/y', policy=net.FAST, target='x') is None


# ── 차단기: 예산 곱셈을 막는다 ───────────────────────────────────────

def test_연속_소진이_임계를_넘으면_네트워크를_안_탄다(monkeypatch):
    """이게 132초를 만든 곱셈을 끊는 자리다."""
    calls = _spy(monkeypatch, [requests.ConnectTimeout('boom')])

    for _ in range(net.FAST.breaker_streak):
        net.get('https://x/y', policy=net.FAST, target='naver')
    burned = len(calls)

    assert net.get('https://x/y', policy=net.FAST, target='naver') is None
    assert len(calls) == burned, '차단됐는데도 요청이 나갔다'


def test_차단기는_대상별로_격리된다(monkeypatch):
    """오늘 KIS 차단기가 못 하는 것 — 네이버가 죽어도 KIS는 계속 시도해야 한다."""
    calls = _spy(monkeypatch, [requests.ConnectTimeout('boom')])

    for _ in range(net.FAST.breaker_streak):
        net.get('https://naver/x', policy=net.FAST, target='naver')
    burned = len(calls)

    net.get('https://kis/x', policy=net.FAST, target='kis')

    assert len(calls) > burned, '네이버 장애가 KIS 호출까지 막았다'


def test_한_번_닿으면_차단이_풀린다(monkeypatch):
    boom = requests.ConnectTimeout('boom')
    _spy(monkeypatch, [boom, boom, boom, _Res()])

    net.get('https://x/y', policy=net.FAST, target='x')      # 소진 1회
    assert net._STREAKS.get('x') == 1

    assert net.get('https://x/y', policy=net.FAST, target='x') is not None
    assert net._STREAKS.get('x', 0) == 0


def test_주문_등급은_차단하지_않는다(monkeypatch):
    """청산은 무조건 나가야 한다. 매도를 차단기가 막으면 리스크를 못 줄인다."""
    calls = _spy(monkeypatch, [requests.ConnectTimeout('boom')])

    for _ in range(net.CRITICAL.breaker_streak + 3):
        net.get('https://kis/order', policy=net.CRITICAL, target='kis-order')
    burned = len(calls)

    net.get('https://kis/order', policy=net.CRITICAL, target='kis-order')

    assert len(calls) > burned, '주문 경로가 차단기에 막혔다'


# ── 실패 이유 ───────────────────────────────────────────────────────

def test_실패_이유를_상태코드까지_남긴다(monkeypatch):
    """429인지 503인지가 유량 제한 판정의 핵심이다.
    'HTTPError'로 뭉뚱그리면 못 쓴다(2026-09-08 수집 실패율 92%에서 배웠다)."""
    _spy(monkeypatch, [_Res(429)])
    reasons = {}

    net.get('https://x/y', policy=net.FAST, target='x', reasons=reasons)

    assert reasons == {'HTTP 429': 1}, reasons


def test_연결_실패는_예외_이름으로_남는다(monkeypatch):
    _spy(monkeypatch, [requests.ConnectTimeout('boom')])
    reasons = {}

    net.get('https://x/y', policy=net.FAST, target='x', reasons=reasons)

    assert 'ConnectTimeout' in reasons


# ── 가드 ────────────────────────────────────────────────────────────

def _production_py():
    skip = ('_legacy_backups', 'scratch', 'tests', 'node_modules', '.git',
            '.next', 'out', 'dist', '__pycache__')
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f.endswith('.py') and not f.startswith('tmp_') and 'legacy' not in f:
                yield os.path.join(root, f)


# 이관은 단계적이다 — 네이버(이번) → KIS 조회 → 주문(별도 승인).
# 아직 net을 안 쓰는 파일은 여기 적어 두고, 이 목록은 **줄어들기만 한다.**
_NOT_YET = {
    'src/diagnose_company.py', 'src/diagnose_research.py', 'src/research_scraper.py',
    'src/trade_executor.py', 'src/data/market_cap_universe.py',
    'src/data/us_fundamentals.py', 'src/data/us_ohlcv.py', 'src/data/us_universe.py',
    'src/market_calendar.py', 'src/strategy/analyzer.py', 'src/strategy/engine.py',
    'src/strategy/hybrid_advisor_sandbox.py', 'src/trade/auth.py',
    'src/trade/balance.py', 'src/trade/executions.py', 'src/trade/gemini_trade.py',
    'src/trade/kis_data_provider.py', 'src/trade/order_cancel.py',
    'src/trade/realized_pnl.py', 'src/trade/secret_store.py',
    'src/pipeline/workers/program_trader.py', 'src/pipeline/workers/trade_engine.py',
    'scripts/collect_kis_realtime.py', 'scripts/debug_naver_parsing.py',
    'scripts/diag_kis_provider.py', 'scripts/fetch_kis_history.py',
    'scripts/fetch_us_market.py', 'scripts/migrate_timezone.py',
    'scripts/test_kis.py', 'scripts/token_manager.py', 'scripts/trade_loop.py',
    # [2026-09-08] 단건 호출 둘은 이 PR에서 옮겼다. 남은 것은 `fetch_page`
    # 하나인데, **어제 PR #100으로 바꿔서 내일 장중 검증을 기다리는 코드**다.
    # 검증 전에 다시 쓰면 그 검증이 무의미해진다 — 검증 뒤에 옮긴다.
    'src/pipeline/workers/data_fetcher.py',
}


def test_아직_이관_안_된_목록이_늘지_않는다():
    """46곳을 한 번에 옮기면 돈 경로까지 한 PR에 들어간다. 단계적으로 가되,
    **새 직접 호출이 생기는 것은 지금 막는다** — 목록은 줄어들기만 한다."""
    offenders = []
    for path in _production_py():
        rel = os.path.relpath(path, REPO).replace(os.sep, '/')
        if rel in _NOT_YET or rel == 'src/core/net.py':
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            body = f.read()
        if 'requests.get(' in body or 'requests.post(' in body:
            offenders.append(rel)

    assert not offenders, (
        f'{offenders}가 requests를 직접 부른다 — src.core.net을 쓰거나, '
        '단계적 이관 중이면 _NOT_YET에 적고 이 PR에서 옮길 것')
