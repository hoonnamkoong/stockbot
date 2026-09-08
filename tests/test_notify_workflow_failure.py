# -*- coding: utf-8 -*-
"""워크플로 실패 알림은 **실패 연속당 한 번**이다.

2026-08-30 실측: 실패 알림(`if: failure()`)이 있는 워크플로는 trading·scraper·
monthly_report 셋뿐이고, 최근 30런 실패가 0이다. 알림이 없는 나머지에만 실패가
쌓여 있었다 — premarket 9/10, token_refresh 10/30, us_eod_watchlist 2/8. 빨간불이
나도 아무도 안 불렀기 때문에 몇 주씩 방치됐다.

**그런데 런마다 보내면 안 된다.** trading은 하루 196런, us_trading은 태스커
전환 뒤 세션당 100런 남짓이다. 지속 실패에 수백 통이 나가면 사람이 알림을
끄고, 그러면 알림이 없는 것과 같아진다.

최근 시간창 안에 이미 성공이 아닌 완료 런이 있으면 생략한다. 상태 파일이
필요 없고(런이 깨진 상황에서 db-data 왕복은 못 믿는다), 사람이 알고 싶은 사건
'언제부터 깨졌나'와 정확히 맞는다.

[2026-09-08] 기준을 '직전 완료 런 하나'에서 '시간창'으로 바꿨다. 왜 바꿨는지와
창 경계 자체는 test_notify_suppression_window.py가 지킨다. 여기서는 그 변경이
원래 성질(연속 실패는 한 통, 조회 실패는 시끄러운 쪽)을 깨지 않았는지를 본다.
"""
import datetime as dt
from unittest import mock

from scripts import notify_workflow_failure as n

_NOW = dt.datetime(2026, 9, 8, 14, 43, tzinfo=dt.timezone.utc)


def _runs(*pairs):
    """(id, status, conclusion[, minutes_ago]) → API 응답 모양.

    minutes_ago 기본값은 억제 창 안이다 — 이 파일의 테스트는 창 경계가 아니라
    결과 조합을 보기 때문에, 시각 때문에 판정이 흔들리면 안 된다.
    """
    out = []
    for p in pairs:
        i, s, c = p[0], p[1], p[2]
        ago = p[3] if len(p) > 3 else 2
        done = _NOW - dt.timedelta(minutes=ago)
        out.append({'id': i, 'status': s, 'conclusion': c,
                    'updated_at': done.strftime('%Y-%m-%dT%H:%M:%SZ')})
    return out


def test_첫_실패면_보낸다():
    runs = _runs((100, 'completed', 'failure'), (99, 'completed', 'success'))
    assert n.should_notify(runs, current_run_id=100, now=_NOW) is True


def test_연속_실패는_한_번만():
    runs = _runs((100, 'completed', 'failure'), (99, 'completed', 'failure'))
    assert n.should_notify(runs, current_run_id=100, now=_NOW) is False


def test_진행중인_런은_직전으로_치지_않는다():
    """동시에 도는 런이 있어도 판단 기준은 '완료된' 직전 런이다."""
    runs = _runs((101, 'in_progress', None),
                 (100, 'completed', 'failure'),
                 (99, 'completed', 'success'))
    assert n.should_notify(runs, current_run_id=100, now=_NOW) is True


def test_자기_자신은_직전이_아니다():
    runs = _runs((100, 'completed', 'failure'))
    assert n.should_notify(runs, current_run_id=100, now=_NOW) is True


def test_창_안의_취소_뒤_실패는_보내지_않는다():
    """[2026-09-08 뒤집음] 예전 이름은 test_취소된_런_뒤의_실패는_보낸다였고
    "cancelled는 고장이 아니다"를 근거로 True를 기대했다.

    그 전제가 틀렸다. trading.yml의 알림 게이트는 `failure()`가 아니라
    `always() && job.status != 'success'`다 — **취소에서도 울린다**(잡 타임아웃을
    잡으려고 일부러 넓힌 것이다). 발화가 취소를 고장으로 세는데 억제만 안 세면,
    취소는 억제를 통과하는 구멍이 된다. 2026-09-08에 그 구멍으로 네 통이 나갔다.

    발화 조건과 억제 조건은 같은 집합을 봐야 한다."""
    runs = _runs((100, 'completed', 'failure'),
                 (99, 'completed', 'cancelled'),
                 (98, 'completed', 'success'))
    assert n.should_notify(runs, current_run_id=100, now=_NOW) is False


def test_이력_조회_실패면_보낸다():
    """억제를 못 하겠으면 시끄러운 쪽으로 실패한다 — 실패 알림은 놓치면 안 된다."""
    assert n.should_notify(None, current_run_id=100, now=_NOW) is True


def test_텔레그램이_없으면_조용히_끝난다(monkeypatch):
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
    monkeypatch.delenv('TELEGRAM_CHAT_ID', raising=False)
    with mock.patch.object(n.request, 'urlopen') as up:
        assert n.main(log=lambda *_: None) == 'no-telegram'
    up.assert_not_called()
