# -*- coding: utf-8 -*-
"""장중 생존 감시를 태스커 경로에서 깨운다 — 그리고 그 창이 장중과 맞아야 한다.

[왜 옮기나] heartbeat_watch.yml의 네이티브 cron은 `0 0-6 * * 1-5`로 세션당 7회를
기대하는데, 2026-09-08~09-15 6거래일 실측 발화는 **하루 정확히 2회**였다
(12/42 = 28.6%). 게다가 뒤엣것은 전부 장 마감 뒤라 판정이 off_session이다
(09-15 17:14 런: `[Heartbeat] 판정=off_session`) — **장중 유효 커버리지는
6/42 = 14.3%**이고, 09:00~11:30과 12:00~15:30이 통째로 무감시였다.
워크플로 버그가 아니라 이 레포의 cron 드롭이다. us_trading이 같은 이유로
2026-08-27부터 발화 0회였고, 거기서 얻은 규칙이 "태스커 → /api/cron"이다.

[왜 창을 검사하나] 자주 깨우는 것만으로는 부족하다. 장 밖에서 깨우면
check_heartbeat.py는 off_session을 찍고 **아무것도 보지 않는다** — 초록 런이
쌓이는데 감시는 0이다. 스킵과 미발화가 또 같은 모양이 된다.

[왜 09:00 정각이 아닌가] 태스커는 08:00에 잠들고 09:00에 깬다. 09:00 정각의
마지막 완주는 07:5x이라 임계(15분)를 이미 넘겼다 — 그 시각에 깨우면 **살아 있는
날에도 매일 거짓 경보**가 나간다. 첫 감시는 개장 + MAX_AGE_MIN 뒤여야 한다.

창과 격자는 TS(src/lib/cron-target.ts)에 있고 판정은 파이썬(src/heartbeat.py)에
있다. 두 언어로 갈라진 상수는 조용히 어긋난다 — 그 결합을 여기서 고정한다.
"""
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src import heartbeat  # noqa: E402
from src.core import clock  # noqa: E402
from src.session_gate import kr_session_open  # noqa: E402

REPO = os.path.join(os.path.dirname(__file__), '..')
TARGET_TS = os.path.join(REPO, 'src', 'lib', 'cron-target.ts')
ROUTE_TS = os.path.join(REPO, 'src', 'app', 'api', 'cron', 'route.ts')
WATCH_YML = os.path.join(REPO, '.github', 'workflows', 'heartbeat_watch.yml')

_KST = clock.KST
# 2026-09-07은 월요일. 요일 게이트는 라우트가 주말을 먼저 걸러 이미 평일이다.
MONDAY = dt.date(2026, 9, 7)


def _read(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


def _hhmm(name: str) -> tuple[int, int]:
    m = re.search(name + r'[^=]*=\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]', _read(TARGET_TS))
    assert m, f'{name}이 cron-target.ts에 없다 — 감시 창이 선언되지 않았다'
    return int(m.group(1)), int(m.group(2))


def _num(name: str) -> int:
    m = re.search(name + r'[^=]*=\s*(\d+)', _read(TARGET_TS))
    assert m, f'{name}이 cron-target.ts에 없다'
    return int(m.group(1))


def _wakes(phase: int) -> list[tuple[int, int]]:
    """태스커 2분 격자(위상 phase)에서 감시가 깨어나는 (시, 분) 목록.

    태스커 격자가 짝수 분에 놓일지 홀수 분에 놓일지는 폰 프로파일이 정하고
    코드가 모른다. 정각만 보는 조건(`minute % 15 === 0`)은 격자가 홀수 위상일 때
    **한 번도 안 걸린다** — 위상 둘 다에서 검사한다.
    """
    open_hhmm, close_hhmm = _hhmm('HEARTBEAT_OPEN_HHMM'), _hhmm('HEARTBEAT_CLOSE_HHMM')
    grid, window = _num('HEARTBEAT_GRID_MIN'), _num('HEARTBEAT_WINDOW_MIN')
    out = []
    for hour in range(24):
        for minute in range(60):
            if minute % 2 != phase:
                continue
            if not (open_hhmm <= (hour, minute) < close_hhmm):
                continue
            if minute % grid >= window:
                continue
            out.append((hour, minute))
    return out


def test_감시가_깨는_모든_시각이_장중이다():
    """장 밖에서 깨우면 off_session — 런은 초록인데 본 것은 없다."""
    for phase in (0, 1):
        for hour, minute in _wakes(phase):
            now = dt.datetime.combine(MONDAY, dt.time(hour, minute), tzinfo=_KST)
            assert kr_session_open(now), f'{hour:02d}:{minute:02d}는 장 밖이다'
            verdict = heartbeat.judge(now, now - dt.timedelta(minutes=2),
                                      trading_day=True)
            assert verdict != heartbeat.OFF_SESSION, (
                f'{hour:02d}:{minute:02d} 판정={verdict} — 헛도는 감시다')


def test_첫_감시는_개장_직후_거짓경보를_피한다():
    """태스커는 08:00~09:00에 잔다 — 09:00 정각의 마지막 완주는 07:5x다.

    그 시각에 깨우면 봇이 정상인 날에도 매일 stale 경보가 나간다. 도배는
    침묵과 같다. 첫 감시는 개장 + 임계(MAX_AGE_MIN) 이후여야 한다.
    """
    earliest = min(min(_wakes(0)), min(_wakes(1)))
    floor_min = clock.KR_OPEN[0] * 60 + clock.KR_OPEN[1] + heartbeat.MAX_AGE_MIN
    assert earliest[0] * 60 + earliest[1] >= floor_min, (
        f'첫 감시 {earliest[0]:02d}:{earliest[1]:02d}가 개장+{heartbeat.MAX_AGE_MIN}분'
        f'보다 이르다 — 매일 거짓 경보가 난다')


def test_감시_상한이_판정_세션_마감과_어긋나지_않는다():
    """창의 상한은 kr_session_open의 상한(KR_JUDGMENT_CLOSE)을 넘을 수 없다."""
    assert _hhmm('HEARTBEAT_CLOSE_HHMM') <= clock.KR_JUDGMENT_CLOSE


# 최대 발견 지연 = 격자 + 임계. 실측 장중 유효 발화 1회(= 사실상 세션 전체)를
# 한 시간 안으로 끌어내리는 것이 이 작업의 목표다.
MAX_DETECTION_MIN = 60
# 고장 한 건당 텔레그램 통수의 상한. check_heartbeat.py는 send_alert(쿨다운 없음)를
# 쓰므로 격자가 곧 알림 볼륨이다 — 도배는 침묵과 같다. 원 설계가 받아들인 볼륨은
# 세션당 7통(시간당 1회)이었고, 그 두 배까지만 허용한다.
MAX_ALERTS_PER_OUTAGE = 14


def test_발견_지연과_알림_볼륨을_동시에_지킨다():
    """격자는 커버리지와 도배 사이의 유일한 손잡이다 — 양쪽에 상한을 둔다.

    쿨다운을 붙이기 전에 격자를 임계(15분)까지 좁히면 세션당 27통이 된다.
    """
    grid, window = _num('HEARTBEAT_GRID_MIN'), _num('HEARTBEAT_WINDOW_MIN')
    assert grid + heartbeat.MAX_AGE_MIN <= MAX_DETECTION_MIN, (
        f'격자 {grid}분 + 임계 {heartbeat.MAX_AGE_MIN}분 = '
        f'최대 발견 지연 {grid + heartbeat.MAX_AGE_MIN}분')
    assert window >= 2, '태스커 2분 격자보다 좁은 창에는 아무 틱도 안 들어온다'

    for phase in (0, 1):
        wakes = _wakes(phase)
        assert 12 <= len(wakes) <= MAX_ALERTS_PER_OUTAGE, (
            f'위상 {phase} 세션당 발화 {len(wakes)}회 (실측 cron은 장중 1회)')
        gaps = [(b[0] * 60 + b[1]) - (a[0] * 60 + a[1])
                for a, b in zip(wakes, wakes[1:])]
        assert max(gaps) <= grid + window, (
            f'위상 {phase} 최대 공백 {max(gaps)}분 — 격자 {grid}분이 안 지켜졌다')


def test_라우트가_이_판단을_실제로_부른다():
    """순수 함수만 만들고 라우트가 안 부르면 테스트는 초록이고 감시는 0이다.

    2026-08-07에 이 레포가 정확히 그 반대 모양으로 하루를 잃었다 — 대상은
    파일로 존재했지만 트리거가 도달하지 못했고, 실행 이력 0건은 어떤 실패
    목록에도 안 떴다.
    """
    assert 'pickSideWorkflows' in _read(TARGET_TS), \
        'cron-target.ts가 부수 dispatch 대상을 정하지 않는다'
    assert 'pickSideWorkflows' in _read(ROUTE_TS), \
        '/api/cron 라우트가 pickSideWorkflows를 부르지 않는다 — 감시는 안 깨어난다'


def test_네이티브_cron_백업이_남아_있다():
    """태스커가 죽으면 감시자도 같이 죽는다 — 그 한계를 다 없앨 수는 없다.

    감시 대상(trading.yml)과 감시자가 같은 폰에 달리므로, 폰이 멈추면 둘 다
    조용해진다. 세션당 1회뿐이라도 **폰과 무관한** 발화는 이 cron 하나다
    (느린 그물은 data_audit_backup.yml이 13:00 KST cron으로 따로 있다).
    드롭돼도 실패 모드는 '알림이 안 감'이라 더 나빠지지 않는다 — 지우지 않는다.
    """
    on_block = re.split(r'^jobs:', _read(WATCH_YML), flags=re.M)[0]
    assert re.search(r'^\s*-\s*cron:', on_block, flags=re.M), \
        '폰과 무관한 유일한 발화 경로가 사라졌다'
    assert re.search(r'^\s*workflow_dispatch:', on_block, flags=re.M), \
        'workflow_dispatch가 없으면 태스커 경로 dispatch가 422로 실패한다'
