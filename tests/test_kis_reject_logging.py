# -*- coding: utf-8 -*-
"""KIS가 거부한 이유를 로그에 남긴다.

2026-09-11 실측: 매매 엔진의 "체결강도 확보"가 09-10 26~27/30에서 09-11 13~17/30으로
떨어지고 보유 종목 현재가가 측정 불가로 찍혔는데, **왜 거부당했는지 알 방법이 없었다.**
`_get`은 rt_cd != '0'을 사유 없이 {}로 바꾼다(그 계약 자체는 유지한다 — 없는 값을
지어내지 않기 위해서다). 같은 날 웹소켓 쪽도 같은 이유로 원인을 못 찾았고, 거기는
PR #122에서 거부 응답을 드러내 고쳤다. REST도 같은 처방이 필요하다.

로그에 **값(토큰·앱키)은 절대 싣지 않는다** — public 레포의 CI 로그가 새 유출 지점이
되면 안 된다(2026-09-10 .env.production 노출 사고).
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.trade.kis_data_provider import KISDataProvider

_TOKEN = 'TOKEN-SHOULD-NOT-APPEAR'
_APPKEY = 'APPKEY-SHOULD-NOT-APPEAR'


class _Res:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._p = payload

    def json(self):
        return self._p


def _provider(monkeypatch, res):
    p = KISDataProvider.__new__(KISDataProvider)
    p._cache = {}
    p._token = _TOKEN
    p._base_url = 'https://example.invalid'
    p._app_key = _APPKEY
    p._app_secret = 'SECRET-SHOULD-NOT-APPEAR'
    monkeypatch.setattr('src.trade.kis_data_provider.requests.get',
                        lambda *a, **k: res)
    # 중복 억제 상태는 클래스 레벨이다(program_trader가 매 호출 새 인스턴스를 만든다).
    monkeypatch.setattr(KISDataProvider, '_logged_rejects', set())
    return p


def test_거부_사유가_로그에_남는다(monkeypatch, capsys):
    p = _provider(monkeypatch, _Res(
        {'rt_cd': '1', 'msg_cd': 'EGW00201', 'msg1': '초당 거래건수를 초과하였습니다.'}))
    assert p._get('/u', 'FHKST01010100', {}) == {}, '반환 계약은 그대로 {}다'
    out = capsys.readouterr().out
    assert 'EGW00201' in out and '초당 거래건수' in out, out
    assert 'FHKST01010100' in out, '어느 TR이 거부당했는지 없으면 추적이 안 된다'


def test_같은_사유는_한_번만_찍는다(monkeypatch, capsys):
    """한 런이 수백 콜을 돈다 — 사유마다 한 줄이면 충분하고, 도배는 침묵과 같다."""
    p = _provider(monkeypatch, _Res(
        {'rt_cd': '1', 'msg_cd': 'EGW00201', 'msg1': '초당 거래건수를 초과하였습니다.'}))
    for _ in range(5):
        p._get('/u', 'FHKST01010100', {})
    assert capsys.readouterr().out.count('EGW00201') == 1


def test_HTTP_실패도_사유가_남는다(monkeypatch, capsys):
    p = _provider(monkeypatch, _Res({}, status=500))
    assert p._get('/u', 'FHKST01010100', {}) == {}
    assert 'HTTP 500' in capsys.readouterr().out


def test_토큰과_앱키는_로그에_없다(monkeypatch, capsys):
    p = _provider(monkeypatch, _Res(
        {'rt_cd': '1', 'msg_cd': 'EGW00123', 'msg1': '토큰 오류'}))
    p._get('/u', 'FHKST01010100', {})
    out = capsys.readouterr().out
    assert _TOKEN not in out and _APPKEY not in out and 'SECRET-SHOULD-NOT-APPEAR' not in out


def test_성공은_조용하다(monkeypatch, capsys):
    p = _provider(monkeypatch, _Res({'rt_cd': '0', 'output': []}))
    assert p._get('/u', 'FHKST01010100', {}) == {'rt_cd': '0', 'output': []}
    assert '[KIS 거부]' not in capsys.readouterr().out
