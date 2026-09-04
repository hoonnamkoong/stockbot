# -*- coding: utf-8 -*-
"""수집 창이 이미 닫혔으면 KIS 웹소켓에 붙지 않는다.

2026-09-02 실측 — 이 가드가 대기 루프 **안**에 있어서, 시작 시각을 이미 지나
깨어난 런에서는 한 번도 실행되지 않았다:

    09-02 00:19Z(09:19 KST) → 09:31에 "0800 도달 — 수집 시작" → ConnectionClosedError
    08-28 06:10Z(15:10 KST) → 15:22에 "0800 도달 — 수집 시작" → exit 1
    08-27 03:22Z(12:22 KST) → 12:31에 "0800 도달 — 수집 시작" → exit 1

GitHub cron이 몇 시간씩 미는 이 레포에서는 그게 예외가 아니라 기본 경로였고,
premarket_data.yml이 08-17부터 거의 매일 실패하며 그때마다 사람을 불렀다.
"0800 도달"이라는 로그가 09:31에 찍힌 것도 같은 결함이다 — 기다린 적이 없는데
기다렸다고 말한다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from collect_kis_realtime import window_state


def test_창이_닫힌_뒤_깨어나면_붙지_않는다():
    """이게 그 사고다 — 09:31에 08:00~08:50 창을 수집하려 들었다."""
    assert window_state('0931', '0800', '0850') == 'past'


def test_시작_전이면_기다린다():
    assert window_state('0744', '0800', '0850') == 'wait'


def test_창_안이면_수집한다():
    assert window_state('0815', '0800', '0850') == 'go'


def test_시작_시각_정각은_수집이다():
    assert window_state('0800', '0800', '0850') == 'go'


def test_종료_시각_정각은_이미_지난_것이다():
    """until은 '이 시각까지'가 아니라 '이 시각에 끝'이다 — 수신 루프와 같은 판정."""
    assert window_state('0850', '0800', '0850') == 'past'


def test_start가_없으면_기다리지_않는다():
    """--start 없이 즉시 수집하는 용법을 깨지 않는다."""
    assert window_state('0744', '', '0850') == 'go'


def test_start가_없어도_창이_닫혔으면_붙지_않는다():
    """대기 여부와 무관하게, 지난 창에 접속하는 건 언제나 실패한다."""
    assert window_state('0931', '', '0850') == 'past'


def test_창이_닫혔으면_유니버스가_비어도_실패가_아니다(tmp_path, monkeypatch):
    """가드가 유니버스 판정 **뒤**에 있으면, 늦게 깨어난 런은 그 앞에서 죽는다.

    2026-09-03의 창 가드는 웹소켓 접속만 막았다. 그런데 늦게 깨어난 런은
    유니버스도 비어 있기 십상이라(그날 앞 스텝이 못 돌았거나 개장 전이라),
    `유니버스가 비었다` → exit 1이 먼저 나면서 여전히 사람을 불렀다.
    할 일이 없다는 판정이 무엇보다 먼저 와야 한다.
    """
    import types
    import datetime as _dt

    import collect_kis_realtime as cr

    empty = tmp_path / 'universe.csv'
    empty.write_text('code,name\n', encoding='utf-8')

    class _Now:
        @staticmethod
        def now():
            return _dt.datetime(2026, 9, 4, 9, 31)

    monkeypatch.setattr(cr, 'dt', types.SimpleNamespace(datetime=_Now, date=_dt.date))
    monkeypatch.setattr(sys, 'argv',
                        ['collect_kis_realtime.py', '--universe', str(empty),
                         '--start', '0800', '--until', '0850'])
    assert cr.main() == 0, '창이 닫힌 뒤 깨어난 런은 조용히 끝나야 한다'


def test_끊기면_창이_남은_동안_다시_붙는다():
    """`async with` 하나뿐이던 시절, KIS가 소켓을 한 번 닫으면 잡이 죽었다.

    2.5시간짜리 장중 세션에서 한 번의 절단이 그날 수집분을 통째로 날렸다 —
    예외가 main까지 올라가 exit 1이 되고, 뒤의 커밋 스텝이 skip되기 때문이다
    (2026-09-03 intraday 실패).
    """
    from collect_kis_realtime import should_reconnect
    assert should_reconnect('0930', '1130', drops=1) is True
    assert should_reconnect('0930', '1130', drops=3) is True


def test_창이_닫혔으면_다시_붙지_않는다():
    from collect_kis_realtime import should_reconnect
    assert should_reconnect('1130', '1130', drops=0) is False
    assert should_reconnect('1200', '1130', drops=0) is False


def test_연속_절단은_상한에서_멈춘다():
    """승인키 만료처럼 계속 거절당하면 2초마다 재시도하는 바쁜 루프가 된다."""
    from collect_kis_realtime import MAX_DROPS, should_reconnect
    assert should_reconnect('0930', '1130', drops=MAX_DROPS - 1) is True
    assert should_reconnect('0930', '1130', drops=MAX_DROPS) is False
