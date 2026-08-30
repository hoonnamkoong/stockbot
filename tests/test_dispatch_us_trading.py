# -*- coding: utf-8 -*-
"""국내 트리거가 미국 장중 루프를 깨우는 경로.

태스커가 2분마다 부르는데 us_trading 런은 30초~3분 걸린다. 확인 없이 매번
dispatch하면 concurrency 그룹(us-trading)에 런이 쌓이고, 세 번째가 들어올 때
대기 중이던 런이 취소된다 — 그 사이클 판단이 통째로 사라진다
(2026-08-07 국내에서 실측 196런 중 26런, 13%).

**조회에 실패하면 부르지 않는다.** scraper 쪽(dispatch_scraper)은 반대로 부르는
쪽에 실패하는데, 거기는 스크래퍼가 자체 게이트로 중복을 걸러내고 여기는 안
걸러낸다. 다음 트리거가 2분 뒤이므로 한 번 거르는 손해는 작고, 대기열이
취소되는 손해는 사이클 하나다. 이 선택 때문에 '영영 안 부름'이 조용해질 수
있어, 세션 밖 미발화 감지기(scripts/check_us_loop_fired.py)가 짝이다.
"""
import io
import json
from unittest import mock

from scripts import dispatch_us_trading as d


class _Res(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(json.dumps(payload).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _env(monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 't0ken')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'owner/repo')
    monkeypatch.setenv('GITHUB_REF_NAME', 'main')


def test_토큰이_없으면_부르지_않는다(monkeypatch):
    monkeypatch.delenv('GH_PAT', raising=False)
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    assert d.dispatch_us_trading(log=lambda *_: None) == 'no-token'


def test_이미_실행_중이면_생략한다(monkeypatch):
    _env(monkeypatch)
    with mock.patch.object(d.request, 'urlopen',
                           return_value=_Res({'total_count': 1})) as up:
        assert d.dispatch_us_trading(log=lambda *_: None) == 'skipped'
    # POST가 나가지 않았는지 — 조회 GET만 있어야 한다.
    assert all(getattr(c.args[0], 'method', 'GET') != 'POST' for c in up.call_args_list)


def test_한가하면_dispatch한다(monkeypatch):
    _env(monkeypatch)
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        if req.get_method() == 'POST':
            return _Res({}, status=204)
        return _Res({'total_count': 0})

    with mock.patch.object(d.request, 'urlopen', side_effect=fake_urlopen):
        assert d.dispatch_us_trading(log=lambda *_: None) == 'dispatched'
    post = [c for c in calls if c.get_method() == 'POST']
    assert len(post) == 1
    assert post[0].full_url.endswith('/workflows/us_trading.yml/dispatches')
    assert json.loads(post[0].data)['ref'] == 'main'


def test_조회_실패면_부르지_않는다(monkeypatch):
    """fail-open이면 대기열이 취소돼 사이클이 사라진다."""
    _env(monkeypatch)
    with mock.patch.object(d.request, 'urlopen', side_effect=OSError('boom')) as up:
        assert d.dispatch_us_trading(log=lambda *_: None) == 'skipped'
    assert all(c.args[0].get_method() != 'POST' for c in up.call_args_list)


def test_dispatch_실패는_결과로_드러난다(monkeypatch):
    _env(monkeypatch)

    def fake_urlopen(req, timeout=None):
        if req.get_method() == 'POST':
            raise OSError('403')
        return _Res({'total_count': 0})

    with mock.patch.object(d.request, 'urlopen', side_effect=fake_urlopen):
        assert d.dispatch_us_trading(log=lambda *_: None) == 'failed'
