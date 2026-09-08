# -*- coding: utf-8 -*-
"""텔레그램으로 나가는 길은 하나다 — `src/core/notify.py`.

## 왜 필요했나 (2026-09-08 실측)

발신자가 셋이었고, **기능이 서로 달랐다:**

    파일                              HTTP       4096자 분할  실패 재시도
    src/telegram_manager.py           requests   O            O
    scripts/notify_workflow_failure.py urllib    X            X
    scripts/audit_data_freshness.py   urllib     X            X

텔레그램 sendMessage의 상한은 4096자다. **넘으면 API가 그냥 거부한다.**
분할이 telegram_manager에만 있으므로, 실패 알림이나 신선도 감사 보고가 길어지면
그대로 사라진다 — 그리고 그 둘은 "뭔가 잘못됐다"를 알리는 경로다. 길어질 때는
대개 문제가 많을 때다.

## 왜 표준 라이브러리여야 하나

urllib 쪽 둘은 실수가 아니다. 두 파일 모두 "실패 지점이 pip install일 수도 있다"를
근거로 표준 라이브러리만 쓴다. 공용 코어가 `requests`를 요구하면 그 성질이 깨진다.

거꾸로, 코어가 표준 라이브러리면 셋이 다 모이면서 **분할과 재시도를 나머지 둘도
갖게 된다.** 잃는 것 없이 얻는 쪽이다.

## 이 파일이 지키는 것

[[test_core_clock]]과 같다 — 통합이 아니라 **재분열 금지**가 본체다.
마지막 가드가 새 발신 지점을 막는다.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.core import notify

REPO = os.path.join(os.path.dirname(__file__), '..')


@pytest.fixture
def sent(monkeypatch):
    """보낸 조각을 모은다. 반환값은 각 조각의 성공 여부."""
    calls = []

    def fake_post(url, data, timeout):
        calls.append(data)
        return True

    monkeypatch.setattr(notify, '_post', fake_post)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'tok')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', 'chat')
    return calls


# ── 발송 ────────────────────────────────────────────────────────────

def test_짧은_메시지는_한_번에_간다(sent):
    assert notify.send('안녕') is True
    assert len(sent) == 1


def test_상한을_넘으면_나눠_보낸다(sent):
    """지금은 이걸 telegram_manager만 한다. 실패 알림·감사 보고는 그냥 잘렸다."""
    text = '\n\n'.join(['가' * 1000] * 8)      # 약 8,000자

    assert notify.send(text) is True
    assert len(sent) > 1
    assert all(len(c['text']) <= notify.SAFE_LEN for c in sent)


def test_나눠도_내용이_보존된다(sent):
    text = '\n\n'.join(f'문단{i}' + '나' * 900 for i in range(6))

    notify.send(text)

    joined = ''.join(c['text'] for c in sent)
    for i in range(6):
        assert f'문단{i}' in joined


def test_한_조각이라도_실패하면_False(monkeypatch):
    """일부만 갔는데 성공으로 기록되면 나머지가 조용히 사라진다.

    실패를 **예외**로 흉내낸다 — 실제 `_post`는 False를 돌려주지 않고
    urlopen이 4xx/5xx에 raise 한다.

    한 조각을 **평문 폴백까지 포함해** 막는다. 첫 시도만 막으면 폴백이 성공해서
    전체가 True가 되는데, 그건 올바른 동작이라 이 테스트가 재려는 게 아니다.
    """
    doomed = '라' * 1000

    def flaky(url, data, timeout):
        if doomed in data['text']:
            raise OSError('boom')
        return True

    monkeypatch.setattr(notify, '_post', flaky)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'tok')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', 'chat')

    text = '\n\n'.join(['다' * 1000] * 4 + [doomed] + ['마' * 1000] * 3)
    assert notify.send(text) is False


def test_시크릿이_없으면_보내지_않는다(monkeypatch):
    posted = []
    monkeypatch.setattr(notify, '_post',
                        lambda url, data, timeout: posted.append(data) or True)
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
    monkeypatch.delenv('TELEGRAM_CHAT_ID', raising=False)

    assert notify.send('x') is False
    assert not posted


def test_HTML이_거부되면_평문으로_다시_보낸다(monkeypatch):
    """LLM 요약에 <, > 가 섞여 파싱이 깨지는 일이 실제로 있었다.
    지금은 telegram_manager에만 있는 폴백이다."""
    tries = []

    def fake_post(url, data, timeout):
        tries.append(data.get('parse_mode'))
        if len(tries) == 1:            # 첫 시도(HTML)를 텔레그램이 거부
            raise OSError('Bad Request: cannot parse entities')
        return True

    monkeypatch.setattr(notify, '_post', fake_post)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'tok')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', 'chat')

    assert notify.send('<b>깨진 태그') is True
    assert tries == ['HTML', None], tries


def test_발송_실패는_예외로_올라가지_않는다(monkeypatch):
    """알림이 터져서 매매 경로가 죽으면 원래 알리려던 문제보다 나빠진다."""
    def boom(url, data, timeout):
        raise OSError('network down')

    monkeypatch.setattr(notify, '_post', boom)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'tok')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', 'chat')

    assert notify.send('x', log=lambda *_: None) is False


# ── 분할은 순수 함수다 ───────────────────────────────────────────────

def test_문단_경계로_나눈다():
    chunks = notify.split_chunks('가' * 100 + '\n\n' + '나' * 100, limit=150)

    assert len(chunks) == 2
    assert chunks[0].endswith('가')


def test_한_문단이_상한을_넘으면_강제로_자른다():
    chunks = notify.split_chunks('가' * 500, limit=200)

    assert len(chunks) == 3
    assert all(len(c) <= 200 for c in chunks)


# ── 가드 ────────────────────────────────────────────────────────────

def test_코어는_표준_라이브러리만_쓴다():
    """pip install이 실패한 런에서도 알림은 나가야 한다 —
    실패 지점이 pip install 자신일 수 있기 때문이다."""
    src = open(os.path.join(REPO, 'src', 'core', 'notify.py'),
               encoding='utf-8').read()

    assert 'import requests' not in src
    assert 'from requests' not in src


def _production_py():
    skip = ('_legacy_backups', 'scratch', 'tests', 'node_modules', '.git',
            '.next', 'out', 'dist', '__pycache__')
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f.endswith('.py') and not f.startswith('tmp_') and 'legacy' not in f:
                yield os.path.join(root, f)


def test_텔레그램_API를_직접_부르는_파일이_없다():
    """발신 지점이 셋으로 갈려 있었고, 그중 둘에는 분할도 재시도도 없었다.
    파일 목록이 아니라 규칙으로 막는다 — 새 발신자가 생겨도 잡힌다."""
    allowed = {os.path.normpath('src/core/notify.py')}

    offenders = []
    for path in _production_py():
        rel = os.path.normpath(os.path.relpath(path, REPO))
        if rel in allowed:
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            if 'api.telegram.org' in f.read():
                offenders.append(rel)

    assert not offenders, (
        f'{offenders}가 텔레그램 API를 직접 부른다 — '
        'src.core.notify.send 하나여야 한다')
