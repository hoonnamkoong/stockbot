# -*- coding: utf-8 -*-
"""워크플로 실패 알림은 **실패 연속당 한 번**이다.

2026-08-30 실측: 실패 알림(`if: failure()`)이 있는 워크플로는 trading·scraper·
monthly_report 셋뿐이고, 최근 30런 실패가 0이다. 알림이 없는 나머지에만 실패가
쌓여 있었다 — premarket 9/10, token_refresh 10/30, us_eod_watchlist 2/8. 빨간불이
나도 아무도 안 불렀기 때문에 몇 주씩 방치됐다.

**그런데 런마다 보내면 안 된다.** trading은 하루 196런, us_trading은 태스커
전환 뒤 세션당 100런 남짓이다. 지속 실패에 수백 통이 나가면 사람이 알림을
끄고, 그러면 알림이 없는 것과 같아진다.

직전 **완료** 런의 결과를 보고 그것도 실패였으면 생략한다. 상태 파일이 필요 없고
(런이 깨진 상황에서 db-data 왕복은 못 믿는다), 사람이 알고 싶은 사건
'언제부터 깨졌나'와 정확히 맞는다.
"""
from unittest import mock

from scripts import notify_workflow_failure as n


def _runs(*pairs):
    """(id, status, conclusion) → API 응답 모양."""
    return [{'id': i, 'status': s, 'conclusion': c} for i, s, c in pairs]


def test_첫_실패면_보낸다():
    runs = _runs((100, 'completed', 'failure'), (99, 'completed', 'success'))
    assert n.should_notify(runs, current_run_id=100) is True


def test_연속_실패는_한_번만():
    runs = _runs((100, 'completed', 'failure'), (99, 'completed', 'failure'))
    assert n.should_notify(runs, current_run_id=100) is False


def test_진행중인_런은_직전으로_치지_않는다():
    """동시에 도는 런이 있어도 판단 기준은 '완료된' 직전 런이다."""
    runs = _runs((101, 'in_progress', None),
                 (100, 'completed', 'failure'),
                 (99, 'completed', 'success'))
    assert n.should_notify(runs, current_run_id=100) is True


def test_자기_자신은_직전이_아니다():
    runs = _runs((100, 'completed', 'failure'))
    assert n.should_notify(runs, current_run_id=100) is True


def test_취소된_런_뒤의_실패는_보낸다():
    """cancelled는 고장이 아니다 — 그 뒤 첫 실패는 새 소식이다."""
    runs = _runs((100, 'completed', 'failure'),
                 (99, 'completed', 'cancelled'),
                 (98, 'completed', 'success'))
    assert n.should_notify(runs, current_run_id=100) is True


def test_이력_조회_실패면_보낸다():
    """억제를 못 하겠으면 시끄러운 쪽으로 실패한다 — 실패 알림은 놓치면 안 된다."""
    assert n.should_notify(None, current_run_id=100) is True


def test_텔레그램이_없으면_조용히_끝난다(monkeypatch):
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
    monkeypatch.delenv('TELEGRAM_CHAT_ID', raising=False)
    with mock.patch.object(n.request, 'urlopen') as up:
        assert n.main(log=lambda *_: None) == 'no-telegram'
    up.assert_not_called()
