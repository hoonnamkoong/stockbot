# -*- coding: utf-8 -*-
"""웹소켓 구독 거부는 로그에 남아야 하고, 구독 요청은 천천히 보낸다.

2026-09-11 실측 — 장중 수집이 7,909건(09-10은 609,180건)이었다. 파일을 (TR, 종목)
으로 세 보니 **구독 40개 중 3개만** 살아 있었다(유니버스 맨 앞 3종목의 체결만,
호가는 0건). 그런데 로그에는 거부 사유가 한 줄도 없었다. 응답 필터가
`'SUBSCRIBE' not in msg1`이라 "SUBSCRIBE SUCCESS"와 함께 "MAX SUBSCRIBE OVER"·
"ALREADY IN SUBSCRIBE"까지 숨겼기 때문이다.

그날은 KIS 앱키를 재발급한 다음 첫 거래일이었다(09-10 19:22 KST). 신규 앱키
유량 제한이 유력하지만 확정하지 못했다 — 사유가 숨어 있었으니까. 요청 간격은
0.05초(초당 20건)였다.
"""
import asyncio
import datetime as _dt
import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import collect_kis_realtime as cr  # noqa: E402


def test_구독_성공만_성공이다():
    assert cr.is_subscribe_success({'msg1': 'SUBSCRIBE SUCCESS'}) is True


def test_SUBSCRIBE가_들어간_거부는_성공이_아니다():
    """옛 필터가 숨긴 게 바로 이것들이다."""
    assert cr.is_subscribe_success({'msg1': 'MAX SUBSCRIBE OVER'}) is False
    assert cr.is_subscribe_success({'msg1': 'ALREADY IN SUBSCRIBE'}) is False


def test_구독_요청은_초당_3건을_넘지_않는다():
    """신규 앱키 제한(초당 3건) 가설 아래에서도 전부 받아들여지는 간격이다."""
    assert 1 / cr.SUBSCRIBE_GAP_SEC <= 3


def test_구독에_걸리는_시간은_30초를_넘지_않는다():
    """너무 느리면 09:00 개장 직후 체결을 놓친다. 한도(40건) 전부를 보내는 시간."""
    assert cr.MAX_SUBSCRIBE * cr.SUBSCRIBE_GAP_SEC <= 30


class _FakeWS:
    """구독 응답 둘(성공·거부)과 체결 한 줄을 준 뒤 조용해진다."""

    def __init__(self, state):
        self.state = state
        self.sent = []
        self.inbox = [
            json.dumps({'header': {'tr_id': 'H0STCNT0'},
                        'body': {'rt_cd': '0', 'msg1': 'SUBSCRIBE SUCCESS'}}),
            json.dumps({'header': {'tr_id': 'H0STCNT0'},
                        'body': {'rt_cd': '1', 'msg1': 'MAX SUBSCRIBE OVER'}}),
            '0|H0STCNT0|001|005930^090001^70000',
        ]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, msg):
        self.sent.append(msg)

    async def recv(self):
        if self.inbox:
            return self.inbox.pop(0)
        self.state['done'] = True       # 받을 게 없으면 창을 닫는다
        raise asyncio.TimeoutError

    async def pong(self, msg):
        pass


def test_거부_사유는_로그에_남고_요약이_찍힌다(tmp_path, monkeypatch, capsys):
    state = {'done': False}
    sleeps = []

    class _Now:
        @staticmethod
        def now():
            return _dt.datetime(2026, 9, 11, 11, 30 if state['done'] else 9, 30)

    async def _sleep(sec):
        sleeps.append(sec)

    monkeypatch.setattr(cr, 'dt', types.SimpleNamespace(datetime=_Now, date=_dt.date))
    monkeypatch.setattr(cr.websockets, 'connect', lambda *a, **k: _FakeWS(state))
    monkeypatch.setattr(cr.asyncio, 'sleep', _sleep)

    codes = [('005930', '삼성전자'), ('000660', 'SK하이닉스')]
    asyncio.run(cr.collect(codes, ['H0STCNT0'], str(tmp_path / 'rt.csv'), '1130', 'KEY'))
    out = capsys.readouterr().out

    assert 'MAX SUBSCRIBE OVER' in out, '거부 사유가 로그에서 사라졌다'
    assert '성공 1' in out and '거부 1' in out, f'구독 요약이 없다:\n{out}'
    assert sleeps == [cr.SUBSCRIBE_GAP_SEC] * len(codes), '구독 간격 상수를 안 쓴다'
