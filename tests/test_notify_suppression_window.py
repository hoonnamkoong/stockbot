# -*- coding: utf-8 -*-
"""실패 알림 억제는 **연속**이 아니라 **시간창**으로 잰다.

2026-09-08에 실전매매 실패 알림이 12:59·14:15·14:24·14:43 네 통 나갔다.
네 번 다 잡 타임아웃(3분)에 잘린 `cancelled`이었고, 발화 게이트가
`always() && job.status != 'success'`라 취소에서도 울린다.

억제가 한 번도 안 걸린 이유는 `cancelled`를 안 세서가 아니다. **취소가
성공 런들 사이에 산발적으로 끼어 있어서** 직전 완료 런이 매번 `success`였다.
즉 `cancelled`를 `failure`로 취급하도록 고쳐도 네 통 그대로 나간다 —
연속 기준 자체가 이 고장 유형을 못 잡는다.

시간창으로 바꾸면:
  - 지속 장애: 매 런이 직전 실패를 창 안에서 보므로 계속 억제 → 통틀어 한 통
  - 산발 장애: 조용한 30분이 지난 뒤 첫 건만 → "새 소식"과 뜻이 맞는다
"""
import datetime as dt

from scripts import notify_workflow_failure as n

_NOW = dt.datetime(2026, 9, 8, 14, 43, tzinfo=dt.timezone.utc)


def _run(rid, conclusion, minutes_ago, status='completed'):
    done = _NOW - dt.timedelta(minutes=minutes_ago)
    return {'id': rid, 'status': status, 'conclusion': conclusion,
            'updated_at': done.strftime('%Y-%m-%dT%H:%M:%SZ')}


def test_창_안에_이미_취소가_있으면_보내지_않는다():
    """2026-09-08 14:24 취소 뒤 14:43 취소 — 19분 간격이라 새 소식이 아니다."""
    runs = [_run(100, None, 0, status='in_progress'),
            _run(99, 'success', 2),
            _run(98, 'cancelled', 19),
            _run(97, 'success', 21)]
    assert n.should_notify(runs, current_run_id=100, now=_NOW) is False


def test_창_밖의_취소는_억제하지_않는다():
    """12:56 취소와 14:12 취소는 76분 떨어져 있다 — 별개 사건이다."""
    runs = [_run(100, None, 0, status='in_progress'),
            _run(99, 'success', 2),
            _run(98, 'cancelled', 76)]
    assert n.should_notify(runs, current_run_id=100, now=_NOW) is True


def test_직전이_성공이어도_창_안의_실패를_본다():
    """연속 기준의 맹점 — 실패 뒤 성공 한 번이 억제를 풀어버리면 안 된다."""
    runs = [_run(100, None, 0, status='in_progress'),
            _run(99, 'success', 2),
            _run(98, 'failure', 5)]
    assert n.should_notify(runs, current_run_id=100, now=_NOW) is False


def test_창_안이_전부_성공이면_보낸다():
    runs = [_run(100, None, 0, status='in_progress'),
            _run(99, 'success', 2),
            _run(98, 'success', 4)]
    assert n.should_notify(runs, current_run_id=100, now=_NOW) is True


def test_진행중인_런은_결과가_없으므로_세지_않는다():
    """동시에 도는 런의 conclusion은 null이다. 그걸 non-success로 세면
    억제가 항상 걸려 알림이 통째로 죽는다."""
    runs = [_run(100, None, 0, status='in_progress'),
            _run(99, None, 1, status='in_progress'),
            _run(98, 'success', 3)]
    assert n.should_notify(runs, current_run_id=100, now=_NOW) is True


def test_자기_자신은_억제_근거가_아니다():
    """알림 스텝은 잡이 끝나기 전에 도는데, API가 자기 런을 이미
    non-success로 보고할 수 있다. 자기 실패로 자기를 억제하면 한 통도 안 간다."""
    runs = [_run(100, 'cancelled', 0), _run(99, 'success', 2)]
    assert n.should_notify(runs, current_run_id=100, now=_NOW) is True


def test_시각을_못_읽으면_시끄러운_쪽으로_실패한다():
    """억제를 못 하겠으면 보낸다 — 실패 알림은 놓치는 쪽이 더 나쁘다."""
    runs = [{'id': 99, 'status': 'completed', 'conclusion': 'cancelled'}]
    assert n.should_notify(runs, current_run_id=100, now=_NOW) is True


# trading.yml은 태스커가 2분마다 깨운다. 30분 창을 보려면 최소 15런이 필요하다.
_FASTEST_TRIGGER_MIN = 2


def test_가져오는_런_수가_억제_창을_덮는다(monkeypatch):
    """창을 넓혔는데 per_page를 안 늘리면 창이 조용히 좁아진다.

    응답에 없는 런은 '없었던 일'이 되므로, 억제는 가져온 만큼만 작동한다.
    두 상수가 따로 놀 수 있는 자리라 관계를 여기 못박는다."""
    seen = {}

    class _Res:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        @staticmethod
        def read():
            return b'{"workflow_runs": []}'

    def _fake_urlopen(req, timeout=None):
        seen['url'] = req.full_url
        return _Res()

    monkeypatch.setenv('GH_PAT', 'x')
    monkeypatch.setattr(n.request, 'urlopen', _fake_urlopen)
    n._fetch_runs('trading.yml', log=lambda *_: None)

    per_page = int(seen['url'].split('per_page=')[1].split('&')[0])
    assert per_page >= n.SUPPRESS_WINDOW_MIN / _FASTEST_TRIGGER_MIN
